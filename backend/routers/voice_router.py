"""
Voice / text input API routes.
"""

import logging
import os
import tempfile

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydub import AudioSegment

from core.pipeline_orchestrator import PipelineOrchestrator
from models.intent_models import LANGUAGE_CONFIG, TextInputRequest

logger = logging.getLogger("VoiceRouter")

router   = APIRouter()
pipeline = PipelineOrchestrator()


# ── Health ────────────────────────────────────────────────────────────────────

@router.get("/health")
async def health():
    return {"status": "healthy", "service": "Banking Voice Agent"}


@router.get("/languages")
async def languages():
    return {
        code: {"name": cfg["name"], "flag": cfg["flag"], "tts_voice": cfg["tts_voice"]}
        for code, cfg in LANGUAGE_CONFIG.items()
    }


# ── Voice input ───────────────────────────────────────────────────────────────

@router.post("/voice-input")
async def voice_input(
    file: UploadFile = File(...),
    language: str = "km-KH",
    region: str = "Others",
):
    """
    Accept a recorded WebM/WAV audio blob, convert to 16 kHz mono WAV,
    run the full pipeline and return a PipelineResult JSON.
    """
    logger.info(f"🎤 Voice input ({language}, region={region})")

    # Save upload to temp file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    wav_path = tmp_path.replace(".webm", ".wav")
    try:
        logger.info("Converting to 16 kHz mono WAV…")
        audio = AudioSegment.from_file(tmp_path)
        audio.export(wav_path, format="wav", parameters=["-ar", "16000", "-ac", "1"])
        os.unlink(tmp_path)
        tmp_path = wav_path
    except Exception as conv_err:
        logger.warning(f"Audio conversion failed ({conv_err}), using original")
        wav_path = tmp_path

    try:
        result = await pipeline.process_audio(wav_path, language, region)
    finally:
        for path in {tmp_path, wav_path}:
            try:
                os.unlink(path)
            except OSError:
                pass

    return result.model_dump()


# ── Text input ────────────────────────────────────────────────────────────────

@router.post("/text-input")
async def text_input(request: TextInputRequest):
    """Skip STT; run translation → intent → workflow → response → TTS."""
    logger.info(
        f"📝 Text input ({request.language}, region={request.region}): {request.text!r}"
    )
    try:
        result = await pipeline.process_text(request.text, request.language, request.region)
        return result.model_dump()
    except Exception as exc:
        logger.error(f"Text input error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


# ── Audio file serving ────────────────────────────────────────────────────────

@router.get("/audio/{filename}")
async def get_audio(filename: str):
    """Serve a generated TTS WAV file inline."""
    path = f"/tmp/{filename}"
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Audio file not found")
    return FileResponse(
        path,
        media_type="audio/wav",
        headers={"Content-Disposition": f"inline; filename={filename}"},
    )
