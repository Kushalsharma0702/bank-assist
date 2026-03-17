"""
Real-time WebSocket voice pipeline.

Wire protocol
─────────────
Client → Server
  binary frames : raw PCM Int16, 16 kHz, mono — streamed continuously while recording
  text  JSON    : {"type":"stop"}  — user releases the mic

Server → Client
  text  JSON    : stage updates, partial transcript, intent, response tokens
  binary frames : one complete WAV per translated sentence (in order, played seamlessly)

Latency design
──────────────
• Azure STT push-stream: partial transcripts appear while the user is still speaking
• Sentence-level TTS: sentence 1 is synthesised (and sent) while Claude is still
  generating sentence 2 → user hears the first audio before the full response exists
• Claude Bedrock streaming: tokens stream out → sentence boundary detection → TTS queue
"""

import asyncio
import json
import logging
import os
import re
import tempfile
import threading
import time
from typing import AsyncIterator

import azure.cognitiveservices.speech as speechsdk
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from config import (
    AZURE_SPEECH_KEY,
    AZURE_SPEECH_REGION,
    CLAUDE_MODEL_ID,
    get_bedrock_client,
)
from models.intent_models import LANGUAGE_CONFIG, SUPPORTED_LANGUAGES
from services.intent_router import get_intent_router
from services.translation_service import TranslationService
from services.tts_service import VOICE_MAP
from services.workflow_engine import WorkflowEngine

logger     = logging.getLogger("WSRouter")
router     = APIRouter()
translator = TranslationService()
workflow   = WorkflowEngine()

_SYSTEM_PROMPT = """\
You are Maya, a highly professional, human-like banking and collections specialist on a live call.

GOAL:
- Help the customer clearly and confidently.
- Sound natural and human.
- Provide precise financial information.
- Guide the conversation to resolution or payment commitment.

VOICE STYLE:
- Speak like a real person using phrases like "okay", "got it", "let me check", "just a second".
- Keep responses short: 1-3 sentences maximum.
- Do not repeat the customer's full question.
- Vary sentence structure and openings.
- Always sound active: "I'm checking that right now", "Let me pull that up", "I'm taking care of it".

DOMAIN CONTROL:
- Only handle banking and collections topics: balance, KYC, cards, statements, loans, EMI, repayment, collections.
- If off-topic, reply exactly: "I can help with your banking or payment queries—tell me what you need there."

FINANCIAL VALUE RULE (CRITICAL):
- Always use specific, confident numbers.
- Never use: "approx", "around", "roughly".
- Stay consistent within the same conversation. If you state one value, keep it unchanged later.
- Use realistic fixed values when needed:
    EMI: ₹4,850 / ₹5,200 / ₹6,750
    Partial payment: ₹2,000 / ₹3,500 / ₹5,000
    Outstanding: ₹18,400 / ₹42,750 / ₹96,200

COLLECTIONS AND NEGOTIATION FLOW:
- If customer hesitates: "I understand, that happens sometimes."
- Offer flexibility naturally: "You don't have to clear everything today" and "We can start with a smaller amount".
- Suggest clear amounts: "You can start with ₹2,000 today" or "Let's do ₹3,500 now and handle the rest later".
- Push commitment every time with one direct question: "What amount can you manage today?" or "When can you make that payment?"
- Confirm commitment clearly: "Alright, ₹3,000 works. You'll do that today, right?"

INTENT GUIDANCE:
- GREETING: welcome naturally and offer immediate help.
- BALANCE: provide a confident balance figure and offer mini-statement by SMS.
- STATEMENT: say you are generating the 3-month statement now and it will arrive by email within 2 minutes.
- CARD_BLOCK: block immediately, card deactivates in seconds, replacement in 5-7 days.
- TX_DISPUTE: raise dispute now, include amount when available, case ID via SMS.
- KYC_STATUS: check now, list pending docs clearly.
- EMI_DUE: provide one fixed EMI value and due status confidently.
- FORECLOSURE: provide confident next step and charges clearly.
- ADDRESS_CHANGE: initiate now, OTP confirmation, update timeline.
- COLLECTIONS_PTP: acknowledge and lock commitment date, reinforce payment plan.
- COLLECTIONS_PAYLINK: generate and send secure link immediately.
- PAYMENT_DIFFICULTY: show empathy, normalize partial payment, propose a concrete amount.
- PARTIAL_PAYMENT: send link now and confirm exact amount to pay today.
- FULL_PAYMENT: send link now and confirm exact amount for full closure.
- CALLBACK: schedule now and give clear callback window.
- REQUEST_AGENT: connect now with context handoff.
- THANKS: warm close and check if anything else is needed.
- UNKNOWN: ask one focused clarifying question.

STRICT OUTPUT RULES:
- Maximum 3 sentences.
- No bullet points.
- No placeholders.
- No markdown or JSON.
- Only spoken text output.
- Never use: "as per system", "kindly be informed", "I cannot", "I'm afraid", "unfortunately".
"""

_SENTENCE_END = re.compile(r'[.!?]["\')\]]*\s')


# ─── Claude streaming ────────────────────────────────────────────────────────

async def _stream_claude(
    transcript_en: str,
    intent: str,
    workflow_ctx: dict,
) -> AsyncIterator[str]:
    """Yield Claude response tokens via Bedrock streaming API."""
    escalate = "  Note: escalate to human agent." if workflow_ctx.get("escalate") else ""
    paylink  = "  Note: send payment link."       if workflow_ctx.get("send_paylink") else ""
    prompt = (
        f"Customer intent: {intent}\n"
        f"Workflow action: {workflow_ctx.get('action', 'unknown')}\n"
        f"Customer message (English): {transcript_en}\n"
        f"{escalate}{paylink}\n\n"
        "Generate the banking response now."
    )
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 500,
        "temperature": 0.35,
        "system": _SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": prompt}],
    }

    loop  = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def _fill():
        try:
            client = get_bedrock_client()
            resp   = client.invoke_model_with_response_stream(
                modelId=CLAUDE_MODEL_ID, body=json.dumps(body)
            )
            for event in resp["body"]:
                chunk = event.get("chunk")
                if chunk:
                    data = json.loads(chunk["bytes"])
                    if data.get("type") == "content_block_delta":
                        text = data.get("delta", {}).get("text", "")
                        if text:
                            asyncio.run_coroutine_threadsafe(queue.put(text), loop)
            asyncio.run_coroutine_threadsafe(queue.put(None), loop)
        except Exception as exc:
            asyncio.run_coroutine_threadsafe(queue.put(exc), loop)

    threading.Thread(target=_fill, daemon=True).start()

    while True:
        item = await queue.get()
        if item is None:
            break
        if isinstance(item, Exception):
            raise item
        yield item


# ─── TTS helper (blocking, runs in thread pool) ──────────────────────────────

def _tts_to_wav(text: str, language: str) -> bytes:
    """Synthesise text → WAV bytes using Azure Neural TTS. Blocking."""
    if not text.strip():
        return b""
    speech_cfg = speechsdk.SpeechConfig(
        subscription=AZURE_SPEECH_KEY, region=AZURE_SPEECH_REGION
    )
    voice = VOICE_MAP.get(language, VOICE_MAP["km-KH"])
    speech_cfg.speech_synthesis_voice_name = voice

    tmp = tempfile.mktemp(suffix=".wav")
    audio_cfg = speechsdk.audio.AudioOutputConfig(filename=tmp)
    synth     = speechsdk.SpeechSynthesizer(
        speech_config=speech_cfg, audio_config=audio_cfg
    )
    result = synth.speak_text_async(text).get()
    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        with open(tmp, "rb") as f:
            data = f.read()
        os.unlink(tmp)
        return data
    logger.warning(f"TTS failed for text: {text[:60]!r}")
    return b""


# ─── WebSocket endpoint ───────────────────────────────────────────────────────

@router.websocket("/ws/voice")
async def voice_websocket(websocket: WebSocket, language: str = "km-KH"):
    """
    Streaming real-time voice pipeline:
      PCM audio → Azure STT (streaming) → Translation → Intent →
      Workflow → Claude (streaming) → Sentence TTS → WAV binary frames
    """
    await websocket.accept()
    language = language if language in SUPPORTED_LANGUAGES else "en-US"
    loop     = asyncio.get_event_loop()

    async def send_json(obj: dict):
        try:
            await websocket.send_json(obj)
        except Exception:
            pass

    async def send_stage(name: str, status: str, **kw):
        await send_json({"type": "stage", "name": name, "status": status, **kw})

    try:
        # ── 1. Set up Azure STT push stream ───────────────────────────────────
        # AudioStreamFormat constructor: samples_per_second, bits_per_sample, channels
        fmt         = speechsdk.audio.AudioStreamFormat(
                          samples_per_second=16000, bits_per_sample=16, channels=1
                      )
        push_stream = speechsdk.audio.PushAudioInputStream(stream_format=fmt)
        speech_cfg  = speechsdk.SpeechConfig(
            subscription=AZURE_SPEECH_KEY, region=AZURE_SPEECH_REGION
        )
        lang_cfg    = LANGUAGE_CONFIG.get(language, LANGUAGE_CONFIG["en-US"])
        auto_detect = speechsdk.languageconfig.AutoDetectSourceLanguageConfig(
            languages=lang_cfg["auto_detect_candidates"]
        )
        recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_cfg,
            auto_detect_source_language_config=auto_detect,
            audio_config=speechsdk.audio.AudioConfig(stream=push_stream),
        )

        transcript_q: asyncio.Queue = asyncio.Queue()
        stt_start = time.perf_counter()

        def on_recognizing(evt):
            if evt.result.text:
                asyncio.run_coroutine_threadsafe(
                    send_json({"type": "partial_transcript", "text": evt.result.text}),
                    loop,
                )

        def on_recognized(evt):
            if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
                asyncio.run_coroutine_threadsafe(
                    transcript_q.put({"ok": True,  "text": evt.result.text}), loop
                )
            elif evt.result.reason == speechsdk.ResultReason.NoMatch:
                asyncio.run_coroutine_threadsafe(
                    transcript_q.put({"ok": False, "text": "No speech detected"}), loop
                )

        def on_canceled(evt):
            asyncio.run_coroutine_threadsafe(
                transcript_q.put({"ok": False, "text": str(evt.reason)}), loop
            )

        recognizer.recognizing.connect(on_recognizing)
        recognizer.recognized.connect(on_recognized)
        recognizer.canceled.connect(on_canceled)

        await send_stage("STT", "running")
        recognizer.start_continuous_recognition_async()

        # ── 2. Receive PCM audio frames from browser ──────────────────────────
        while True:
            msg = await websocket.receive()
            if "bytes" in msg and msg["bytes"]:
                push_stream.write(msg["bytes"])
            elif "text" in msg:
                try:
                    data = json.loads(msg["text"])
                    if data.get("type") == "stop":
                        push_stream.close()
                        break
                except json.JSONDecodeError:
                    pass

        # ── 3. Wait for final transcript ──────────────────────────────────────
        result  = await asyncio.wait_for(transcript_q.get(), timeout=12.0)
        stt_ms  = (time.perf_counter() - stt_start) * 1000
        recognizer.stop_continuous_recognition_async()

        if not result["ok"]:
            await send_json({"type": "error", "message": result["text"]})
            return

        transcript = result["text"]
        await send_stage("STT", "done", output=transcript, latency_ms=round(stt_ms))
        logger.info(f"WS STT ({language}): {transcript!r}  [{stt_ms:.0f}ms]")

        # ── 4. Translate to English ───────────────────────────────────────────
        await send_stage("Translation", "running")
        english, trans_ms = await translator.translate_to_english(transcript, language)
        await send_stage("Translation", "done", output=english, latency_ms=round(trans_ms))

        # ── 5. Intent detection ───────────────────────────────────────────────
        await send_stage("Intent Detection", "running")
        intent, conf, phrase, method, intent_ms = await get_intent_router().route(english)
        await send_stage(
            "Intent Detection", "done",
            output=intent, confidence=round(conf, 3),
            matched_phrase=phrase, latency_ms=round(intent_ms),
        )
        await send_json({
            "type": "intent",
            "intent": intent, "confidence": conf, "matched_phrase": phrase,
        })

        # ── 6. Workflow engine ────────────────────────────────────────────────
        workflow_ctx, wf_ms = await workflow.process(intent, english)
        await send_stage("Workflow Engine", "done",
                         output=workflow_ctx["summary"], latency_ms=round(wf_ms))

        # ── 7. Stream Claude + sentence-level TTS ─────────────────────────────
        # Architecture:
        #   Claude tokens arrive → detect sentence boundaries → push to TTS queue
        #   TTS worker processes sentences sequentially (preserving order)
        #   Audio WAV binary frames arrive at browser in order → seamless playback

        await send_stage("Claude Response",    "running")
        await send_stage("Native Translation", "running")
        await send_stage("TTS Audio",          "running")

        response_en     = ""
        sentence_buffer = ""
        llm_start       = time.perf_counter()

        tts_queue: asyncio.Queue = asyncio.Queue()

        async def tts_worker():
            """
            Sequential TTS worker — processes one sentence at a time
            so audio arrives at the browser in the correct order.
            Starts as soon as sentence 1 is ready (before Claude finishes).
            """
            while True:
                sentence_en = await tts_queue.get()
                if sentence_en is None:
                    break
                # Always translate → Khmer then synthesise with Khmer voice.
                # The `language` variable is the STT/input language — TTS output
                # is always Khmer regardless of what language the customer spoke.
                khmer, _ = await translator.translate_to_khmer(sentence_en)
                await send_json({"type": "khmer_sentence", "text": khmer})

                # Force km-KH voice: Khmer text MUST use Khmer voice (PisethNeural).
                # Passing any other voice code (e.g. en-US-JennyNeural) causes Azure
                # TTS to fail silently when the text contains Khmer Unicode characters.
                wav = await asyncio.get_event_loop().run_in_executor(
                    None, _tts_to_wav, khmer, "km-KH"
                )
                if wav:
                    try:
                        await websocket.send_bytes(wav)
                    except Exception:
                        pass

        worker_task = asyncio.create_task(tts_worker())

        async for token in _stream_claude(english, intent, workflow_ctx):
            response_en     += token
            sentence_buffer += token
            await send_json({"type": "response_token", "text": token})

            # Detect sentence boundary: fire TTS immediately
            if _SENTENCE_END.search(sentence_buffer):
                parts = _SENTENCE_END.split(sentence_buffer)
                # All complete sentences except the trailing fragment
                for s in parts[:-1]:
                    s = s.strip()
                    if s:
                        await tts_queue.put(s)
                sentence_buffer = parts[-1] if parts[-1] else ""

        # Flush any remaining text
        if sentence_buffer.strip():
            await tts_queue.put(sentence_buffer.strip())

        llm_ms = (time.perf_counter() - llm_start) * 1000
        await send_stage("Claude Response", "done",
                         output=response_en, latency_ms=round(llm_ms))

        # Signal TTS worker to stop and wait for all sentences to be sent
        await tts_queue.put(None)
        await worker_task

        await send_stage("Native Translation", "done", output="Streamed per sentence")
        await send_stage("TTS Audio", "done", output="Streamed in sentences")

        await send_json({"type": "done", "response_en": response_en})
        logger.info(f"WS pipeline complete in {llm_ms:.0f}ms total LLM")

    except WebSocketDisconnect:
        logger.info("WS client disconnected")
    except asyncio.TimeoutError:
        await send_json({"type": "error", "message": "Timeout — no speech detected. Please try again."})
    except Exception as exc:
        logger.error(f"WS error: {exc}", exc_info=True)
        try:
            await send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass
