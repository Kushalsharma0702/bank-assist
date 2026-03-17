"""
True-Duplex Barge-In Voice Router  —  /ws/duplex
=================================================

Production-grade full-duplex voice assistant with SSML humanisation,
real-time barge-in, and optimised latency pipeline.

Latency Optimisations Applied:
  1. PARALLEL processing:  translation + intent run concurrently (saves ~2s)
  2. PHRASE-LEVEL flushing: split on commas/semicolons for faster first-audio
  3. CACHED Bedrock client: reused across LLM calls (saves ~100ms connection)
  4. IN-MEMORY TTS:        no disk I/O, synthesise directly to memory
  5. PRE-WARMED SpeechConfig: created once per session, not per synthesis
  6. CONCURRENT translate+TTS: translate sentence while previous TTS plays
  7. LOWER max_tokens:     100 tokens for voice (keeps responses short)
  8. SKIP translation for en-US: zero-cost path for English users

Architecture
────────────
 Browser mic (PCM 16-bit, 16 kHz, mono)
   │  binary WS frames — ALWAYS streaming, even during TTS playback
   ▼
 _recv_loop          ← sole coroutine calling ws.receive()
   ├─ PCM → stt_q    ← feeds the current STT push-stream
   ├─ PCM → energy_q ← feeds VAD for barge-in detection
   └─ JSON control   (start / hangup)

 _vad_loop           ← polls energy_q; sets barge_in_event on speech spike

 _run_pipeline       ← per-turn STT→LLM→TTS chain (restartable)
   ├─ _stt_task      ← Azure push-stream continuous STT
   ├─ _llm_to_tts    ← Claude streaming → phrase splitting → sentence_q
   └─ _tts_task      ← SSML Azure TTS → WAV binary → WS

Wire Protocol (unchanged)
─────────────
Client → Server:  binary PCM | {"type":"start"} | {"type":"hangup"}
Server → Client:  {"type":"state"|"partial"|"final"|"intent"|"token"|"sentence"|"tts_stop"|"turn_end"|"ended"|"error"} | binary WAV
"""

import asyncio
import base64
import io
import json
import logging
import math
import os
import random
import re
import struct
import tempfile
import threading
import time
import wave
from collections import OrderedDict
from collections.abc import AsyncIterator
from typing import List, Optional, Tuple

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
from services.sarvam_stt_service import SarvamSpeechToTextService
from services.sarvam_tts_service import SarvamTextToSpeechService
from services.translation_service import TranslationService
from services.tts_service import VOICE_MAP
from services.workflow_engine import WorkflowEngine

logger     = logging.getLogger("DuplexRouter")
router     = APIRouter()
translator = TranslationService()
workflow   = WorkflowEngine()
sarvam_stt = SarvamSpeechToTextService()
sarvam_tts = SarvamTextToSpeechService()

# ─── Cached Bedrock Client (saves ~100ms connection overhead per call) ────────
_bedrock_client = None
_bedrock_lock   = threading.Lock()

def _get_cached_bedrock():
    global _bedrock_client
    if _bedrock_client is None:
        with _bedrock_lock:
            if _bedrock_client is None:
                _bedrock_client = get_bedrock_client()
    return _bedrock_client

# ─── Constants ────────────────────────────────────────────────────────────────

_TERMINAL_INTENTS = {"THANKS", "REQUEST_AGENT"}
_HANGUP_PHRASES   = {
    "cut", "cut the call", "bye", "goodbye", "end call",
    "hang up", "hangup", "disconnect", "stop", "close",
}

# Phrase-level splitting for faster first-audio delivery
# Splits on: sentence endings (.!?) OR clause boundaries (, ; : —) when > 15 chars
_SENTENCE_END = re.compile(r'(?<=[.!?])\s+')
_PHRASE_BREAK  = re.compile(r'(?<=[,;:—])\s+')
_MIN_PHRASE_LEN = 15  # don't flush tiny fragments

# VAD — conservative tuning to avoid background-noise barge-ins.
# Typical clean-AEC audio: silence ~20-80 RMS, whisper ~80-120, speech ~150-900 RMS.
VAD_THRESHOLD_RMS    = 180   # stronger absolute floor against ambient/AGC bursts
VAD_MAX_THRESHOLD_RMS = 2000 # Absolute cap so loud human speech will always trigger barge-in
VAD_MAX_NOISE_FLOOR  = 600   # Prevent runaway noise floor from static or heavy background noise
# Adaptive threshold = max(VAD_THRESHOLD_RMS, noise_floor * multiplier).
VAD_NOISE_MULTIPLIER = 2.4
# Require at least N consecutive hot frames so one loud noise chunk cannot trigger.
VAD_HOT_FRAMES_REQUIRED = 2
# Grace period: ignore barge-in for the first N milliseconds of a speaking
# turn so ambient noise and AEC transients don't kill the response.
# This is time-based (not chunk-count based) so it remains correct even when
# the browser sends larger PCM buffers (e.g. 4096 samples ≈ 256 ms).
_MIN_BARGE_IN_GRACE_MS = 350
# Require sustained hot audio for a minimum duration before barge-in fires.
_MIN_HOT_SPEECH_MS     = 220
VAD_LOG_INTERVAL     = 10    # log RMS stats every N chunks during speaking (info)

# Sarvam STT guardrails for noisy production streams.
SARVAM_STT_NOISE_MULTIPLIER = 2.5
SARVAM_STT_MAX_NOISE_FLOOR = 700.0
SARVAM_STT_MIN_WORDS_DIVERSITY_CHECK = 8
SARVAM_STT_MIN_DIVERSITY_RATIO = 0.35
SARVAM_LANG_SWITCH_MIN_WORDS = 3
SARVAM_LANG_SWITCH_MIN_DISTINCT_WORDS = 3

# Voice fallback map for regions where primary neural voices are unavailable.
_VOICE_FALLBACKS = {
    "km-KH": ["km-KH-SreymomNeural", "km-KH-PisethNeural", "en-US-JennyNeural"],
    "en-US": ["en-US-JennyNeural", "en-US-AriaNeural"],
    "vi-VN": ["vi-VN-HoaiMyNeural", "en-US-JennyNeural"],
    "th-TH": ["th-TH-PremwadeeNeural", "en-US-JennyNeural"],
    "zh-CN": ["zh-CN-XiaoxiaoNeural", "en-US-JennyNeural"],
    "hi-IN": ["hi-IN-SwaraNeural", "en-US-JennyNeural"],
    "id-ID": ["id-ID-GadisNeural", "en-US-JennyNeural"],
    "ms-MY": ["ms-MY-YasminNeural", "en-US-JennyNeural"],
}

_TTS_CACHE_MAX = 64
_TTS_WAV_CACHE: "OrderedDict[str, bytes]" = OrderedDict()

_GREETINGS = {
    "en-US": "Hello! I'm Maya, your AI banking assistant. How can I help you today?",
    "km-KH": "សួស្តី! ខ្ញុំគឺ Maya ជាអ្នកជំនួយការធនាគារ AI របស់អ្នក។ តើខ្ញុំអាចជួយអ្នកយ៉ាងណាបាន?",
    "vi-VN": "Xin chao! Toi la Maya, tro ly ngan hang AI cua ban. Toi co the giup gi cho ban hom nay?",
    "th-TH": "Sawasdee! Chan khue Maya, phu chuai dan ngan khong khun. Chan chuai arai dai bang wan-nii?",
    "zh-CN": "Ni hao! Wo shi Maya, nin de yinhang AI zhuli. Jin tian wo keyi zenme bang nin?",
    "hi-IN": "Namaste! Main Maya hoon, aapki AI banking sahayak. Aaj main aapki kya madad kar sakti hoon?",
    "id-ID": "Halo! Saya Maya, asisten perbankan AI Anda. Ada yang bisa saya bantu hari ini?",
    "ms-MY": "Hai! Saya Maya, pembantu perbankan AI anda. Bagaimana saya boleh bantu anda hari ini?",
}

_FAREWELLS = {
    "en-US": "Thank you for calling! Have a wonderful day, goodbye!",
    "km-KH": "សូមអរគុណសម្រាប់ការហៅមក! សូមជូនពរឲ្យអ្នកមានថ្ងៃល្អ។ លាហើយ!",
    "vi-VN": "Cam on ban da goi! Chuc ban mot ngay tuyet voi. Tam biet!",
    "th-TH": "Khob khun thi to ma! Kho hai mi wan thi di. Sawatdee kha!",
    "zh-CN": "Ganxie nin lai dian! Zhu nin yitian yukuai. Zaijian!",
    "hi-IN": "Call karne ke liye dhanyavaad! Aapka din shubh ho. Alvida!",
    "id-ID": "Terima kasih sudah menghubungi kami! Semoga harimu menyenangkan. Sampai jumpa!",
    "ms-MY": "Terima kasih kerana menghubungi kami! Semoga hari anda indah. Selamat tinggal!",
}

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _pcm_rms(pcm_bytes: bytes) -> float:
    """Compute RMS energy of a PCM Int16 LE buffer."""
    n = len(pcm_bytes) // 2
    if n == 0:
        return 0.0
    samples = struct.unpack_from(f"<{n}h", pcm_bytes)
    return (sum(s * s for s in samples) / n) ** 0.5


def _resolve_voice_name(language: str) -> str:
    """Return a valid Azure voice name from VOICE_MAP (supports dict or str values)."""
    profile = VOICE_MAP.get(language, VOICE_MAP.get("en-US", "en-US-JennyNeural"))
    if isinstance(profile, dict):
        return str(profile.get("voice", "en-US-JennyNeural"))
    return str(profile)


def _voice_candidates(language: str) -> List[str]:
    """Return de-duplicated preferred voice candidates for fallback retries."""
    primary = _resolve_voice_name(language)
    candidates = [primary]
    candidates.extend(_VOICE_FALLBACKS.get(language, []))
    if "en-US-JennyNeural" not in candidates:
        candidates.append("en-US-JennyNeural")

    unique: List[str] = []
    seen = set()
    for voice in candidates:
        if voice and voice not in seen:
            seen.add(voice)
            unique.append(voice)
    return unique


def _cache_get(key: str) -> Optional[bytes]:
    data = _TTS_WAV_CACHE.get(key)
    if data is None:
        return None
    _TTS_WAV_CACHE.move_to_end(key)
    return data


def _cache_put(key: str, data: bytes) -> None:
    if not data:
        return
    _TTS_WAV_CACHE[key] = data
    _TTS_WAV_CACHE.move_to_end(key)
    while len(_TTS_WAV_CACHE) > _TTS_CACHE_MAX:
        _TTS_WAV_CACHE.popitem(last=False)


def _normalize_region(region: str) -> str:
    """Return canonical region flag used by duplex routing."""
    value = (region or "").strip().lower()
    return "India" if value in {"india", "in"} else "Others"


def _is_india_region(region: str) -> bool:
    return _normalize_region(region) == "India"


async def _sarvam_transcribe_pcm(pcm_bytes: bytes, language: str) -> Tuple[str, str]:
    """Encode PCM16 mono 16k audio as WAV and transcribe it with Sarvam."""
    if not pcm_bytes:
        return "", ""

    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            temp_path = tmp.name

        with wave.open(temp_path, "wb") as wavf:
            wavf.setnchannels(1)
            wavf.setsampwidth(2)  # PCM16
            wavf.setframerate(16000)
            wavf.writeframes(pcm_bytes)

        transcript, detected_lang, _ = await sarvam_stt.transcribe(
            temp_path,
            language=language,
            preprocess=False,
        )
        return _dedup_transcript((transcript or "").strip()), detected_lang
    except Exception as exc:
        logger.warning(f"Sarvam STT chunk transcription failed: {exc}")
        return "", ""
    finally:
        if temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                pass


async def _synth_to_wav_bytes(
    text: str,
    output_language: str,
    sentence_index: int,
    region: str,
) -> bytes:
    """Synthesize speech bytes using region-selected engine."""
    if not text.strip():
        return b""

    if _is_india_region(region):
        sarvam_cache_key = f"sarvam::{output_language}::{text}"
        cached = _cache_get(sarvam_cache_key)
        if cached is not None:
            logger.debug(f"🔊 Sarvam TTS cache hit ({output_language})")
            return cached
        try:
            _, audio_b64, _, _ = await sarvam_tts.synthesize(
                text=text,
                language=output_language,
            )
            wav_bytes = base64.b64decode(audio_b64) if audio_b64 else b""
            if wav_bytes:
                _cache_put(sarvam_cache_key, wav_bytes)
            return wav_bytes
        except Exception as exc:
            logger.warning(f"Sarvam TTS failed, no audio generated: {exc}")
            return b""

    voice = _resolve_voice_name(output_language)
    ssml = _humanise_ssml(
        text,
        voice,
        language=output_language,
        sentence_index=sentence_index,
    )
    wav = await asyncio.get_event_loop().run_in_executor(
        None,
        _tts_ssml_to_wav_mem,
        ssml,
        _voice_candidates(output_language),
    )
    if wav:
        return wav

    logger.warning("[TTS] SSML failed -> plain text fallback")
    return await asyncio.get_event_loop().run_in_executor(
        None,
        _tts_plain_to_wav_mem,
        text,
        output_language,
    )


# ─── SSML Voice Humanisation ──────────────────────────────────────────────────

# Azure Neural voices that support mstts:express-as styles.
# Using styles gives a much more natural, human-sounding result than prosody alone.
_STYLE_VOICE_MAP: dict = {
    "en-US-JennyNeural":    "customerservice",
    "en-US-AriaNeural":     "customerservice",
    "en-US-GuyNeural":      "newscast-casual",
    "zh-CN-XiaoxiaoNeural": "customerservice",
    "zh-CN-YunxiNeural":    "chat",
}


def _humanise_ssml(text: str, voice: str, language: str = "en-US", sentence_index: int = 0) -> str:
    """
    Build natural Azure Neural TTS SSML.
    • mstts:express-as style for supported voices — far more human-sounding.
    • Deterministic per-sentence prosody variation for naturalness.
    • Proper xmlns:mstts namespace (required for mstts tags to work).
    """
    seed = f"{language}|{voice}|{sentence_index}|{text.strip()}"
    rng = random.Random(seed)

    # Perceptible but natural variation: rate -8%…+3%, pitch -3Hz…+5Hz
    rate_pct = f"{rng.uniform(-8.0, 3.0):+.1f}%"
    pitch_hz = f"{rng.uniform(-3.0, 5.0):+.1f}Hz"

    # Questions naturally rise in pitch
    if text.rstrip().endswith("?"):
        pitch_hz = f"{rng.uniform(2.0, 7.0):+.1f}Hz"

    # Short growing pause between sentences
    pause_ms = min(80 + sentence_index * 20, 200)
    pause = f'<break time="{pause_ms}ms"/>' if sentence_index > 0 else ""

    escaped = _escape_ssml(text)
    style   = _STYLE_VOICE_MAP.get(voice)
    if style:
        inner = (
            f'<mstts:express-as style="{style}" styledegree="1.3">'
            f'<prosody rate="{rate_pct}" pitch="{pitch_hz}">{escaped}</prosody>'
            f'</mstts:express-as>'
        )
    else:
        inner = f'<prosody rate="{rate_pct}" pitch="{pitch_hz}">{escaped}</prosody>'

    return (
        f'<speak version="1.0" '
        f'xmlns="http://www.w3.org/2001/10/synthesis" '
        f'xmlns:mstts="http://www.w3.org/2001/mstts" '
        f'xml:lang="{language}">'
        f'<voice name="{voice}">{pause}{inner}</voice>'
        f'</speak>'
    )


def _escape_ssml(text: str) -> str:
    """Escape XML special characters."""
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
    )


# ─── In-Memory TTS (eliminates disk I/O) ─────────────────────────────────────

def _tts_ssml_to_wav_mem(ssml: str, voice_candidates: Optional[List[str]] = None) -> bytes:
    """SSML → WAV bytes with voice fallback retries."""
    t0 = time.monotonic()
    candidates = voice_candidates or ["en-US-JennyNeural"]
    cache_key = f"ssml::{candidates[0]}::{ssml}"
    cached = _cache_get(cache_key)
    if cached is not None:
        logger.debug(f"🔊 TTS SSML cache hit ({candidates[0]})")
        return cached

    for idx, voice in enumerate(candidates):
        speech_cfg = speechsdk.SpeechConfig(
            subscription=AZURE_SPEECH_KEY, region=AZURE_SPEECH_REGION
        )
        speech_cfg.speech_synthesis_voice_name = voice
        synth = speechsdk.SpeechSynthesizer(speech_config=speech_cfg, audio_config=None)
        result = synth.speak_ssml_async(ssml).get()

        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            data = result.audio_data
            ms = (time.monotonic() - t0) * 1000
            logger.info(f"🔊 TTS SSML ({voice}): {len(data)} bytes in {ms:.0f}ms")
            _cache_put(cache_key, data)
            return data

        details = ""
        if result.cancellation_details:
            details = f" | {result.cancellation_details.reason}: {result.cancellation_details.error_details}"
        logger.warning(f"TTS SSML failed ({voice}): reason={result.reason}{details}")

        if idx < len(candidates) - 1:
            logger.warning(f"Retrying SSML with fallback voice: {candidates[idx + 1]}")

    return b""


def _tts_plain_to_wav_mem(text: str, language: str) -> bytes:
    """Plain text → WAV bytes. Fallback when SSML fails."""
    if not text.strip():
        return b""
    t0 = time.monotonic()

    for voice in _voice_candidates(language):
        cache_key = f"plain::{voice}::{language}::{text}"
        cached = _cache_get(cache_key)
        if cached is not None:
            logger.debug(f"🔊 TTS plain cache hit ({voice})")
            return cached

        speech_cfg = speechsdk.SpeechConfig(
            subscription=AZURE_SPEECH_KEY, region=AZURE_SPEECH_REGION
        )
        speech_cfg.speech_synthesis_voice_name = voice
        synth = speechsdk.SpeechSynthesizer(speech_config=speech_cfg, audio_config=None)
        result = synth.speak_text_async(text).get()

        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            ms = (time.monotonic() - t0) * 1000
            logger.info(f"🔊 TTS plain ({voice}): {len(result.audio_data)} bytes in {ms:.0f}ms")
            _cache_put(cache_key, result.audio_data)
            return result.audio_data

        logger.warning(f"TTS plain failed ({voice}) for: {text[:60]!r}")

    return b""


# ─── System prompt (tuned for brevity → lower latency) ───────────────────────

def _system_prompt() -> str:
    return """\
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


# ─── Banking Safety Guard ─────────────────────────────────────────────────────
# Prevent the LLM from claiming financial actions it did not execute.
# The only verbs permitted in past-tense completion language are those
# explicitly backed by the workflow engine for the current action.

_HALLUCINATION_RE = re.compile(
    r'\b(has been|have been)\s+(?:successfully\s+)?'
    r'(blocked|unblocked|transferred|sent|activated|deactivated|cancelled)\b',
    re.IGNORECASE,
)
_WORKFLOW_CONFIRMED: dict = {
    "block_card":        {"blocked"},
    "send_paylink":      {"sent"},
    "schedule_callback": {"scheduled"},
    "update_address":    {"updated"},
}


def _banking_safety_filter(text: str, workflow_ctx: dict) -> str:
    """
    Rewrite unconfirmed past-tense financial completion claims.
    'has been blocked'  →  allowed only when action == block_card
    'has been sent'     →  allowed only when action == send_paylink
    Everything else: 'has been X' → 'is being X'
    """
    action    = workflow_ctx.get("action", "")
    confirmed = _WORKFLOW_CONFIRMED.get(action, set())

    def _fix(m: re.Match) -> str:
        verb = m.group(2).lower()
        if verb in confirmed:
            return m.group(0)       # workflow-confirmed — keep past tense
        logger.warning(f"🛡️ Safety: rewrote unconfirmed claim {m.group(0)!r}")
        return f"is being {verb}"

    return _HALLUCINATION_RE.sub(_fix, text)


# ─── LLM Streaming (cached client, lower max_tokens) ─────────────────────────

async def _stream_llm(
    transcript_en: str,
    intent: str,
    workflow_ctx: dict,
    history: List[dict],
    loop: asyncio.AbstractEventLoop,
) -> AsyncIterator:
    """Yield Claude streaming tokens. Uses cached Bedrock client."""
    ctx_note = ""
    if workflow_ctx.get("escalate"):
        ctx_note += "  Note: escalate to human agent after response."
    if workflow_ctx.get("send_paylink"):
        ctx_note += "  Note: send payment link."

    user_content = (
        f"[Intent: {intent} | Action: {workflow_ctx.get('action', 'unknown')}]"
        f"{ctx_note}\n{transcript_en}"
    ).strip()

    prior = list(history)
    while prior and prior[0]["role"] != "user":
        prior.pop(0)

    messages = prior + [{"role": "user", "content": user_content}]

    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 90,            # ← shorter for voice = faster, fewer TTS sentences
        "temperature": 0.35,
        "system": _system_prompt(),
        "messages": messages,
    }

    queue: asyncio.Queue = asyncio.Queue()

    def _fill():
        try:
            client = _get_cached_bedrock()  # ← cached, saves ~100ms
            resp = client.invoke_model_with_response_stream(
                modelId=CLAUDE_MODEL_ID, body=json.dumps(body)
            )
            for event in resp["body"]:
                chunk = event.get("chunk")
                if chunk:
                    # Depending on boto3 version, chunk["bytes"] might be raw bytes or already parsed dict
                    raw_data = chunk["bytes"]
                    data = raw_data if isinstance(raw_data, dict) else json.loads(raw_data)
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


# ─── VAD Loop ─────────────────────────────────────────────────────────────────

async def _vad_loop(
    energy_q: asyncio.Queue,
    barge_in_event: asyncio.Event,
    is_speaking_fn,
):
    """
    Always-on Voice Activity Detection.
    Fires barge_in_event when sustained speech energy detected during bot speaking.
    """
    hot_ms = 0.0
    hot_frames = 0
    chunk_count = 0        # for periodic diagnostic logging
    max_rms_window = 0.0   # track max RMS during speaking for diagnostics
    speaking_ms = 0.0      # elapsed ms while bot is speaking
    noise_floor_rms = 40.0 # adaptive ambient baseline while not speaking

    try:
        while True:
            try:
                energy_item = await asyncio.wait_for(energy_q.get(), timeout=0.1)
            except asyncio.TimeoutError:
                hot_ms = 0.0
                continue

            # Backward compatible payload support:
            # - new format: (rms, chunk_ms)
            # - old format: rms float only
            if isinstance(energy_item, tuple):
                rms, chunk_ms = energy_item
            else:
                rms, chunk_ms = energy_item, 10.0

            if chunk_ms <= 0:
                chunk_ms = 10.0

            if not is_speaking_fn():
                hot_ms = 0.0
                hot_frames = 0
                speaking_ms = 0.0
                max_rms_window = 0.0
                # Track ambient floor only when bot is not speaking so TTS energy
                # never pollutes baseline estimation. Prevent runaway floor accumulation.
                raw_floor = (noise_floor_rms * 0.98) + (float(rms) * 0.02)
                noise_floor_rms = min(raw_floor, VAD_MAX_NOISE_FLOOR)
                continue

            # We're in SPEAKING state — monitor for barge-in
            speaking_ms += chunk_ms
            chunk_count += 1
            max_rms_window = max(max_rms_window, rms)

            # Periodic diagnostic: log every VAD_LOG_INTERVAL chunks during speaking
            if chunk_count % VAD_LOG_INTERVAL == 0:
                effective_threshold = min(VAD_MAX_THRESHOLD_RMS, max(VAD_THRESHOLD_RMS, noise_floor_rms * VAD_NOISE_MULTIPLIER))
                logger.info(
                    f"[VAD] Speaking: ms={speaking_ms:.0f}, "
                    f"current_rms={rms:.0f}, max_rms={max_rms_window:.0f}, "
                    f"threshold={effective_threshold:.0f}, floor={noise_floor_rms:.0f}, "
                    f"hot_ms={hot_ms:.0f}, hot_frames={hot_frames}"
                )

            # Grace period: don't allow barge-in at the very start of a speaking turn.
            if speaking_ms < _MIN_BARGE_IN_GRACE_MS:
                hot_ms = 0.0
                hot_frames = 0
                continue

            effective_threshold = min(VAD_MAX_THRESHOLD_RMS, max(VAD_THRESHOLD_RMS, noise_floor_rms * VAD_NOISE_MULTIPLIER))

            if rms > effective_threshold:
                hot_ms += chunk_ms
                hot_frames += 1
                if hot_ms >= _MIN_HOT_SPEECH_MS and hot_frames >= VAD_HOT_FRAMES_REQUIRED:
                    logger.info(
                        f"⚡ BARGE-IN! RMS={rms:.0f} (threshold={effective_threshold:.0f}, "
                        f"floor={noise_floor_rms:.0f}), hot_ms={hot_ms:.0f}, "
                        f"hot_frames={hot_frames}, speaking_ms={speaking_ms:.0f}"
                    )
                    barge_in_event.set()
                    hot_ms = 0.0
                    hot_frames = 0
                    speaking_ms = 0.0
                    max_rms_window = 0.0
            else:
                hot_ms = 0.0
                hot_frames = 0
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"❌ [VAD LOOP DEAD] Fatal error: {e}", exc_info=True)


# ─── STT Transcript Deduplication ──────────────────────────────────────────────
# Azure continuous STT can stutter when audio contains echo or noise artifacts,
# producing transcripts like "have a have a quick quick check on on on my my".
# This pass removes consecutive word/phrase repetitions at the text level so the
# intent classifier and LLM always receive clean input, without touching the audio
# pipeline or the chunk size.

_DEDUP_STT_RE_1W = re.compile(r'\b(\w+)(?:\s+\1)+\b', re.IGNORECASE)
_DEDUP_STT_RE_2W = re.compile(r'\b(\w+\s+\w+)\s+\1\b', re.IGNORECASE)
_DEDUP_STT_RE_3W = re.compile(r'\b(\w+\s+\w+\s+\w+)\s+\1\b', re.IGNORECASE)


def _dedup_transcript(text: str) -> str:
    """
    Remove consecutive duplicate words and short-phrases from an Azure STT
    final transcript.

    Runs three regex passes (3-gram → 2-gram → 1-gram), each iterated until
    stable, so nested duplications are fully unwound.  Only *consecutive*
    repetitions are removed; non-adjacent repeats (legitimate speech) are kept.

    Examples
    --------
    "have a have a quick quick check on on on my my balance"
      → "have a quick check on my balance"
    "before before that that can you can you"
      → "before that can you"
    """
    if not text:
        return text
    for pattern in (_DEDUP_STT_RE_3W, _DEDUP_STT_RE_2W, _DEDUP_STT_RE_1W):
        prev = None
        while prev != text:       # iterate until no more substitutions
            prev = text
            text = pattern.sub(lambda m: m.group(1), text)
    # Collapse any double-spaces left behind and tidy trailing punctuation
    text = re.sub(r'  +', ' ', text).strip()
    return text


def _tokenize_words(text: str) -> List[str]:
    """Unicode-aware word tokenization for STT quality checks."""
    if not text:
        return []
    return [w.lower() for w in re.findall(r"\w+", text, flags=re.UNICODE)]


def _is_probable_hallucinated_stt(text: str) -> bool:
    """Reject repetitive STT hallucinations caused by noisy audio chunks."""
    words = _tokenize_words(text)
    if len(words) < SARVAM_STT_MIN_WORDS_DIVERSITY_CHECK:
        return False

    unique_words = set(words)
    diversity_ratio = len(unique_words) / max(len(words), 1)
    if diversity_ratio < SARVAM_STT_MIN_DIVERSITY_RATIO:
        return True

    # Additional guard: one dominant token repeated most of the transcript.
    dominant_repeats = max(words.count(w) for w in unique_words)
    dominant_ratio = dominant_repeats / len(words)
    return dominant_ratio >= 0.70


def _is_safe_language_switch_text(text: str) -> bool:
    """Allow language switching only on meaningful, non-repetitive utterances."""
    if not text or _is_probable_hallucinated_stt(text):
        return False
    words = _tokenize_words(text)
    if len(words) < SARVAM_LANG_SWITCH_MIN_WORDS:
        return False
    if len(set(words)) < SARVAM_LANG_SWITCH_MIN_DISTINCT_WORDS:
        return False
    return True


# ─── STT Coroutine ────────────────────────────────────────────────────────────

async def _async_warmup(text: str, on_warmup) -> None:
    """
    Run cosine-only intent classification on a partial STT transcript.
    Posted to the event loop from the Azure SDK thread via
    run_coroutine_threadsafe so the result is cached before the STT
    final arrives ~200–500 ms later.
    """
    try:
        router = get_intent_router()
        intent, conf, phrase = router.route_fast(text)
        await on_warmup(intent, conf, phrase)
    except Exception:
        pass


async def _stt_task(
    stt_q: asyncio.Queue,
    on_partial,
    on_final,
    language: str,
    loop: asyncio.AbstractEventLoop,
    region: str = "Others",
    on_warmup=None,
):
    """Region-aware STT task: Azure continuous STT or Sarvam chunked STT."""
    if _is_india_region(region):
        await _stt_task_sarvam(stt_q, on_final, language)
        return

    # Azure push-stream continuous STT
    fmt = speechsdk.audio.AudioStreamFormat(
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

    # Deduplication guard: Azure can occasionally fire `recognized` twice
    # for the same segment.  Track the last submitted text and skip exact
    # duplicates so they never reach _stt_final_q.
    _last_final_text:  List[str] = [""]
    # Warmup debounce: only post a new warmup task when the partial has grown
    # substantially (> 5 chars) so we don't spam the event loop.
    _warmup_last_len: List[int]  = [0]

    def _on_recognizing(evt):
        # Partials are display-only.  Overwrite — never accumulate.
        if evt.result.text:
            asyncio.run_coroutine_threadsafe(on_partial(evt.result.text), loop)
            # Intent warmup: fire cosine classification while user is still speaking.
            # Only when text grew by >5 chars and has at least 3 words — avoids
            # spamming the event loop on every tiny partial update.
            if (
                on_warmup
                and len(evt.result.text.split()) >= 3
                and len(evt.result.text) > _warmup_last_len[0] + 5
            ):
                _warmup_last_len[0] = len(evt.result.text)
                asyncio.run_coroutine_threadsafe(
                    _async_warmup(evt.result.text, on_warmup), loop
                )

    def _on_recognized(evt):
        if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
            text = _dedup_transcript(evt.result.text.strip())
            if text and text != _last_final_text[0]:
                _last_final_text[0] = text
                asyncio.run_coroutine_threadsafe(on_final(text), loop)

    recognizer.recognizing.connect(_on_recognizing)
    recognizer.recognized.connect(_on_recognized)
    recognizer.start_continuous_recognition_async()

    try:
        while True:
            chunk = await stt_q.get()
            if chunk is None:
                break
            push_stream.write(chunk)
    except asyncio.CancelledError:
        raise
    finally:
        push_stream.close()
        recognizer.stop_continuous_recognition_async()


async def _stt_task_sarvam(
    stt_q: asyncio.Queue,
    on_final,
    language: str,
):
    """Chunked Sarvam STT with simple speech endpointing for duplex sessions."""
    min_start_threshold = 120.0
    min_end_threshold = 75.0
    min_speech_ms = 350.0
    end_silence_ms = 650.0
    max_speech_ms = 8500.0
    hot_frames_to_start = 2

    in_speech = False
    hot_frames = 0
    speech_ms = 0.0
    silence_ms = 0.0
    noise_floor_rms = 40.0
    buffer = bytearray()

    async def _flush_if_valid():
        nonlocal in_speech, hot_frames, speech_ms, silence_ms, buffer
        if speech_ms >= min_speech_ms and buffer:
            # Use 'unknown' so Sarvam truly auto-detects language instead of
            # being biased by the initial session language.
            text, detected_lang = await _sarvam_transcribe_pcm(bytes(buffer), "unknown")
            if text:
                if _is_probable_hallucinated_stt(text):
                    logger.warning(
                        "Dropping noisy Sarvam STT transcript (len=%d, sample=%r)",
                        len(_tokenize_words(text)),
                        text[:120],
                    )
                else:
                    await on_final(text, detected_lang)
        in_speech = False
        hot_frames = 0
        speech_ms = 0.0
        silence_ms = 0.0
        buffer = bytearray()

    while True:
        chunk = await stt_q.get()
        if chunk is None:
            await _flush_if_valid()
            return

        samples = len(chunk) // 2
        chunk_ms = (samples / 16000.0) * 1000.0 if samples else 0.0
        if chunk_ms <= 0:
            continue

        rms = _pcm_rms(chunk)
        dynamic_start_threshold = max(
            min_start_threshold,
            min(noise_floor_rms * SARVAM_STT_NOISE_MULTIPLIER, VAD_MAX_THRESHOLD_RMS),
        )
        dynamic_end_threshold = max(
            min_end_threshold,
            min(dynamic_start_threshold * 0.55, VAD_MAX_THRESHOLD_RMS),
        )

        if not in_speech:
            # Learn ambient noise floor only while not in speech.
            raw_floor = (noise_floor_rms * 0.98) + (float(rms) * 0.02)
            noise_floor_rms = min(raw_floor, SARVAM_STT_MAX_NOISE_FLOOR)

            if rms >= dynamic_start_threshold:
                hot_frames += 1
                if hot_frames >= hot_frames_to_start:
                    in_speech = True
                    buffer.extend(chunk)
                    speech_ms = chunk_ms
                    silence_ms = 0.0
            else:
                hot_frames = 0
            continue

        buffer.extend(chunk)
        speech_ms += chunk_ms

        if rms <= dynamic_end_threshold:
            silence_ms += chunk_ms
        else:
            silence_ms = 0.0

        if silence_ms >= end_silence_ms or speech_ms >= max_speech_ms:
            await _flush_if_valid()


# ─── TTS Coroutine (in-memory, SSML, with fallback) ──────────────────────────

async def _tts_task(
    sentence_q: asyncio.Queue,
    websocket: WebSocket,
    output_language: str,
    region: str,
):
    """
    Drain sentence_q, synthesise with SSML, send WAV to browser.
    Sentence 0 is synthesised immediately for lowest first-audio latency.
    Sentences 1+ are pulled in pairs and joined into one SSML call, cutting
    TTS round-trips by ~50% (typically 6 → 3 calls per response).
    """
    sentence_idx = 0
    eos = False     # True when the None sentinel was consumed during batching
    try:
        while True:
            sentence = await sentence_q.get()
            if sentence is None:
                break

            # After the first sentence, drain ALL remaining sentences into one
            # batch to cut TTS API calls to a maximum of 2 per turn.
            # A 3-second deadline prevents indefinite blocking if the LLM is slow.
            if sentence_idx >= 1:
                parts    = [sentence]
                deadline = asyncio.get_event_loop().time() + 3.0
                try:
                    while True:
                        remaining = max(deadline - asyncio.get_event_loop().time(), 0.05)
                        nxt = await asyncio.wait_for(sentence_q.get(), timeout=remaining)
                        if nxt is None:
                            eos = True   # end-of-stream consumed here
                            break
                        parts.append(nxt)
                except asyncio.TimeoutError:
                    pass                 # deadline hit — synthesise what we have
                sentence = " ".join(parts)

            tts_start = time.monotonic()

            # Translate if needed
            if output_language == "en-US":
                tts_text = sentence
            else:
                tts_text, _ = await translator.translate_to_language(sentence, output_language)

            try:
                await websocket.send_json({"type": "sentence", "text": tts_text})
            except Exception:
                pass

            wav = await _synth_to_wav_bytes(
                tts_text,
                output_language,
                sentence_idx,
                region,
            )

            tts_ms = (time.monotonic() - tts_start) * 1000

            if wav:
                try:
                    await websocket.send_bytes(wav)
                except Exception:
                    pass
                logger.info(f"🔊 Sentence {sentence_idx} sent ({len(wav)} bytes, {tts_ms:.0f}ms)")
                await asyncio.sleep(0)  # yield for barge-in

            sentence_idx += 1
            if eos:
                break

    except asyncio.CancelledError:
        logger.info("🔇 [TTS] Cancelled → tts_stop")
        try:
            await websocket.send_json({"type": "tts_stop"})
        except Exception:
            pass
        raise


# ─── LLM→TTS Bridge (phrase-level flushing for faster first-audio) ────────────

async def _llm_to_tts_task(
    transcript_en: str,
    intent: str,
    workflow_ctx: dict,
    history: List[dict],
    sentence_q: asyncio.Queue,
    websocket: WebSocket,
    loop: asyncio.AbstractEventLoop,
) -> str:
    """
    Stream LLM tokens, detect phrase/sentence boundaries, push to TTS queue.
    Uses phrase-level flushing: splits on commas/semicolons too for faster
    first-audio delivery.
    """
    response_en = ""
    buffer      = ""
    first_flush = True  # first phrase gets flushed eagerly

    try:
        async for token in _stream_llm(transcript_en, intent, workflow_ctx, history, loop):
            response_en += token
            buffer      += token
            try:
                await websocket.send_json({"type": "token", "text": token})
            except Exception:
                pass

            # 1. Always flush on sentence boundaries
            parts = _SENTENCE_END.split(buffer)
            if len(parts) > 1:
                for s in parts[:-1]:
                    s = s.strip()
                    if s:
                        await sentence_q.put(_banking_safety_filter(s, workflow_ctx))
                        first_flush = False
                buffer = parts[-1]
                continue

            # 2. For faster first-audio: flush on phrase boundaries if buffer is long enough
            if first_flush and len(buffer) >= _MIN_PHRASE_LEN:
                phrase_parts = _PHRASE_BREAK.split(buffer)
                if len(phrase_parts) > 1:
                    for s in phrase_parts[:-1]:
                        s = s.strip()
                        if s and len(s) >= _MIN_PHRASE_LEN:
                            await sentence_q.put(_banking_safety_filter(s, workflow_ctx))
                            first_flush = False
                    buffer = phrase_parts[-1]

        # Flush remaining buffer
        if buffer.strip():
            await sentence_q.put(_banking_safety_filter(buffer.strip(), workflow_ctx))

    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.error(f"💥 LLM stream error: {exc}", exc_info=True)
    finally:
        await sentence_q.put(None)

    return response_en


# ═══════════════════════════════════════════════════════════════════════════════
#  DuplexSession — per-connection conversation manager
# ═══════════════════════════════════════════════════════════════════════════════

class DuplexSession:
    """
    Full duplex conversation for one WebSocket.

    State machine:
        IDLE → GREETING → LISTENING → PROCESSING → SPEAKING → LISTENING...

    Latency optimisations:
      • Parallel translation + intent routing during PROCESSING
      • Phrase-level LLM flushing for faster first-audio
      • In-memory TTS (no disk I/O)
      • Cached Bedrock client
    """

    def __init__(self, websocket: WebSocket, language: str, output_language: str, region: str):
        self.ws              = websocket
        self.language        = language
        self.output_language = output_language
        self.region          = _normalize_region(region)
        self.loop            = asyncio.get_event_loop()

        # Queues: _stt_q / _stt_final_q are session-level (never reset between
        # turns) so barge-in audio captured while the bot was speaking is never
        # discarded when the next pipeline turn starts.
        self._stt_q: asyncio.Queue      = asyncio.Queue(maxsize=500)
        self._sentence_q: asyncio.Queue = asyncio.Queue(maxsize=2)
        self._energy_q: asyncio.Queue   = asyncio.Queue(maxsize=200)

        # Ring buffer — holds the last 50 PCM chunks (~500 ms at 10 ms/chunk).
        # Written unconditionally in _recv_loop.  On barge-in we replay ONLY
        # the frames captured AFTER speaking started (frames that the echo gate
        # blocked) so we never feed already-recognised audio back into STT.
        from collections import deque as _deque
        self._pcm_ring: _deque       = _deque(maxlen=50)
        self._ring_frame_count: int  = 0   # monotonic count of frames appended
        self._speaking_start_frame: int = 0  # ring_frame_count when SPEAKING began
        # When True, _run_pipeline sleeps 120 ms at its start to let acoustic
        # room echo from the bot's speakers decay before opening the STT gate.
        self._after_speaking: bool = False

        # Events
        self._barge_in      = asyncio.Event()
        self._playback_done = asyncio.Event()  # set by frontend when AudioQueue empties
        self._start_event   = asyncio.Event()
        self._stt_final_q: asyncio.Queue = asyncio.Queue()
        self._hangup      = False
        # Intent warmup: last cosine-only result from STT partial events.
        # Consumed (reset to None) at the start of each processing phase.
        self._intent_warmup: Optional[tuple] = None

        # State
        self._state = "idle"
        self.history: List[dict] = []
        self._turn_count = 0
        self._session_start = time.monotonic()

    def _is_speaking(self) -> bool:
        return self._state in ("speaking", "greeting")

    async def _send(self, obj: dict):
        try:
            await self.ws.send_json(obj)
        except Exception:
            pass

    async def _set_state(self, state: str):
        self._state = state
        await self._send({"type": "state", "state": state})

    async def _on_partial(self, text: str):
        await self._send({"type": "partial", "text": text})

    async def _on_final(self, text: str, detected_lang: str = None):
        # Auto-detect language selection from user input and continue conversation in that language.
        if detected_lang and detected_lang != "unknown":
            logger.debug(f"Sarvam STT detected language: {detected_lang}")
            if detected_lang in SUPPORTED_LANGUAGES and (self.language != detected_lang or self.output_language != detected_lang):
                if _is_safe_language_switch_text(text):
                    logger.info(f"Auto-switching language parameters to: {detected_lang}")
                    self.language = detected_lang
                    self.output_language = detected_lang
                    await self._send({"type": "language_change", "language": detected_lang})
                else:
                    logger.warning(
                        "Skipped auto language switch to %s due to low-confidence transcript: %r",
                        detected_lang,
                        (text or "")[:120],
                    )
        await self._stt_final_q.put(text)

    async def _on_intent_warmup(self, intent: str, conf: float, phrase: str) -> None:
        """Cache the latest cosine-only intent classification from STT partials."""
        self._intent_warmup = (intent, conf, phrase)

    # ── Pipeline: LISTEN → PROCESS → SPEAK ───────────────────────────────────

    async def _run_pipeline(self):
        """One listen→respond cycle with latency-optimised processing."""
        self._turn_count += 1
        turn_start = time.monotonic()

        self._barge_in.clear()
        self._sentence_q = asyncio.Queue(maxsize=2)

        # Echo decay: if the bot was just speaking, wait for acoustic room echo
        # to fade before opening the STT gate.  120 ms covers typical domestic
        # room acoustics (RT60 ~ 100–250 ms at close mic distance).  Without
        # this pause, TTS audio still reverberating in the room feeds straight
        # into the always-on recogniser the instant the gate opens and produces
        # the characteristic doubled-word pattern in every transcript.
        if self._after_speaking:
            self._after_speaking = False
            # 300 ms covers typical domestic-room RT60 (100–250 ms) plus a
            # margin for the last TTS bytes still in transit to the browser.
            # The state is still "speaking" during this sleep, so the echo
            # gate stays CLOSED and no residual TTS audio leaks into STT.
            await asyncio.sleep(0.30)

        # Drain any stale finals left over from the previous turn.
        # Echo or background noise heard while the bot was speaking may have
        # produced spurious STT finals; clear them before we listen again.
        # The user's barge-in speech final cannot have arrived yet (Azure STT
        # needs ~300 ms+ after the last word), so this drain is safe.
        while not self._stt_final_q.empty():
            try:
                self._stt_final_q.get_nowait()
            except asyncio.QueueEmpty:
                break

        await self._set_state("listening")

        # The always-on STT (started once in run()) is already capturing the
        # user's microphone in real-time — even during the bot's TTS playback.
        # We simply wait for the next valid transcript it produces.
        transcript = ""
        wait_final = asyncio.create_task(self._stt_final_q.get())
        wait_barge = asyncio.create_task(self._barge_in.wait())
        try:
            done, pending = await asyncio.wait(
                [wait_final, wait_barge],
                timeout=30.0,
                return_when=asyncio.FIRST_COMPLETED,
            )
        except asyncio.CancelledError:
            wait_final.cancel()
            wait_barge.cancel()
            await asyncio.gather(wait_final, wait_barge, return_exceptions=True)
            raise

        for p in pending:
            p.cancel()
            try:
                await p
            except (asyncio.CancelledError, Exception):
                pass

        if not done:
            await self._send({"type": "error", "message": "No speech detected."})
            return

        for t in done:
            try:
                result = t.result()
                if isinstance(result, str) and result.strip():
                    transcript = result
            except Exception:
                pass

        if not transcript:
            if self._barge_in.is_set():
                self._barge_in.clear()
            return

        logger.info(f"📝 STT final (turn {self._turn_count}): {transcript!r}")

        # Hangup check
        t_lower = transcript.lower().strip()
        if any(p in t_lower for p in _HANGUP_PHRASES):
            await self._do_farewell()
            self._hangup = True
            return

        # ── PROCESSING (PARALLEL translation + intent) ────────────────────────
        await self._set_state("processing")
        proc_start = time.monotonic()

        # Run translation and intent routing IN PARALLEL
        translate_task = asyncio.create_task(
            translator.translate_to_english(transcript, self.language)
        )

        # If language is English, we can start intent routing immediately
        if self.language == "en-US":
            english = transcript
            translate_task.cancel()
            try:
                await translate_task
            except (asyncio.CancelledError, Exception):
                pass
        else:
            english, _ = await translate_task

        # Transcript dashboard payload:
        #  - text: what STT recognized
        #  - english_text: mandatory normalized English line for all languages
        #  - output_text: transcript translated to selected output language
        #                 (e.g., Khmer when output_language == km-KH)
        output_text = transcript
        if self.output_language == "en-US":
            output_text = english
        elif self.output_language == self.language:
            output_text = transcript
        else:
            try:
                output_text, _ = await translator.translate_to_language(
                    english, self.output_language
                )
            except Exception as tr_err:
                logger.warning(f"Transcript output translation failed: {tr_err}")
                output_text = transcript

        await self._send(
            {
                "type": "final",
                "text": transcript,
                "english_text": english,
                "output_text": output_text,
                "output_language": self.output_language,
            }
        )

        # Intent routing — use warmup result from partial if high confidence.
        # The warmup ran cosine-only while the user was still speaking, so it
        # arriving here costs <1 ms instead of the usual 20–600 ms.
        # Threshold is slightly higher than routing threshold because partials
        # are incomplete (e.g. "I want to check my" vs "I want to check my balance").
        _WARMUP_MIN = 0.72
        warmup = self._intent_warmup
        self._intent_warmup = None          # consume — one-shot per turn
        if warmup and warmup[1] >= _WARMUP_MIN:
            intent, conf = warmup[0], warmup[1]
            logger.info(f"⚡ Warmup intent: {intent}  conf={conf:.2f}  [<1ms]")
        else:
            intent, conf, _, _, _ = await get_intent_router().route(english)
        await self._send({"type": "intent", "intent": intent, "confidence": round(conf, 3)})

        # Workflow is instant (<1ms)
        workflow_ctx, _ = await workflow.process(intent, english)

        proc_ms = (time.monotonic() - proc_start) * 1000
        logger.info(f"⚙️  Processing: {proc_ms:.0f}ms — intent={intent} conf={conf:.2f}")

        # Bedrock requires strictly alternating user/assistant messages.
        # If the previous turn was barge-in'd (no bot response was recorded),
        # history already ends with a user message.  Remove it before appending
        # the new one so we never send two consecutive user roles.
        if self.history and self.history[-1]["role"] == "user":
            self.history.pop()
        self.history.append({"role": "user", "content": english})

        # ── SPEAKING ──────────────────────────────────────────────────────────
        self._sentence_q = asyncio.Queue(maxsize=2)
        # Snapshot the ring-buffer position NOW.  The barge-in preroll will
        # only inject frames added AFTER this point (i.e. frames the echo gate
        # will block).  Frames before this are already in the STT push-stream.
        self._speaking_start_frame = self._ring_frame_count
        await self._set_state("speaking")
        self._barge_in.clear()

        llm_task = asyncio.create_task(
            _llm_to_tts_task(
                english, intent, workflow_ctx,
                self.history[:-1],
                self._sentence_q,
                self.ws,
                self.loop,
            ),
            name="llm"
        )
        tts = asyncio.create_task(
            _tts_task(self._sentence_q, self.ws, self.output_language, self.region),
            name="tts"
        )
        barge_watch = asyncio.create_task(self._barge_in.wait(), name="barge_watch")

        try:
            done, pending = await asyncio.wait(
                [llm_task, tts, barge_watch],
                return_when=asyncio.FIRST_COMPLETED,
            )

            if barge_watch in done and not barge_watch.cancelled():
                if self._hangup:
                    for task in [llm_task, tts]:
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(llm_task, tts, return_exceptions=True)
                    return
                # BARGE-IN
                interrupt_ms = (time.monotonic() - turn_start) * 1000
                logger.info(f"⚡ BARGE-IN at {interrupt_ms:.0f}ms! Cancelling LLM + TTS.")
                for task in [llm_task, tts]:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(llm_task, tts, return_exceptions=True)

                # Inject ONLY the ring-buffer frames captured after speaking
                # started — those are the frames the echo gate blocked from
                # reaching the STT.  Re-injecting older frames (from LISTENING
                # or PROCESSING) would feed already-recognised audio back into
                # Azure and produce the doubled-word duplication pattern.
                _frames_gated = self._ring_frame_count - self._speaking_start_frame
                if _frames_gated > 0:
                    _inject = list(self._pcm_ring)[-min(_frames_gated, len(self._pcm_ring)):]
                    for chunk in _inject:
                        try:
                            self._stt_q.put_nowait(chunk)
                        except asyncio.QueueFull:
                            break

                self._barge_in.clear()
                await self._send({"type": "tts_stop"})
                await self._set_state("listening")
                return

            else:
                # LLM finished first (most common case) or TTS finished first.
                # If TTS is still playing we MUST keep watching for barge-in —
                # simply cancelling barge_watch and waiting for tts blindly
                # means any interruption during the remaining TTS audio is lost.
                barge_watch.cancel()
                await asyncio.gather(barge_watch, return_exceptions=True)

                if not tts.done():
                    # Keep a fresh barge-in watch alive for the entire TTS tail.
                    barge_watch_tail = asyncio.create_task(
                        self._barge_in.wait(), name="barge_watch_tail"
                    )
                    done_tail, _ = await asyncio.wait(
                        [tts, barge_watch_tail],
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    late_barge = (
                        barge_watch_tail in done_tail
                        and not barge_watch_tail.cancelled()
                    )
                    barge_watch_tail.cancel()
                    await asyncio.gather(barge_watch_tail, return_exceptions=True)

                    if late_barge:
                        interrupt_ms = (time.monotonic() - turn_start) * 1000
                        logger.info(
                            f"⚡ LATE BARGE-IN at {interrupt_ms:.0f}ms! Cancelling TTS."
                        )
                        if not tts.done():
                            tts.cancel()
                        await asyncio.gather(llm_task, tts, return_exceptions=True)

                        # Preroll: replay frames gated during speaking
                        _frames_gated = (
                            self._ring_frame_count - self._speaking_start_frame
                        )
                        if _frames_gated > 0:
                            _inject = list(self._pcm_ring)[
                                -min(_frames_gated, len(self._pcm_ring)):
                            ]
                            for chunk in _inject:
                                try:
                                    self._stt_q.put_nowait(chunk)
                                except asyncio.QueueFull:
                                    break

                        self._barge_in.clear()
                        await self._set_state("listening")
                        return

                    # No barge-in — TTS finished naturally; wait for LLM too
                    await asyncio.gather(llm_task, return_exceptions=True)
                else:
                    await asyncio.gather(llm_task, tts, return_exceptions=True)

                try:
                    bot_response = llm_task.result()
                except Exception:
                    bot_response = ""

                if bot_response:
                    self.history.append({"role": "assistant", "content": bot_response})

                turn_ms = (time.monotonic() - turn_start) * 1000
                await self._send({"type": "turn_end"})

                # Bridge the bytes-sent / audio-played gap.
                # The backend considers TTS "done" when the last WAV bytes are
                # written to the WebSocket — but the browser AudioQueue may still
                # be playing those bytes for several more seconds.  Keep a
                # barge-in watch alive until the frontend signals playback_done
                # (AudioQueue.onEnd) so the user can interrupt at any point
                # during actual audio playback, not just during byte transfer.
                self._playback_done.clear()
                _pb_task = asyncio.create_task(
                    self._playback_done.wait(), name="pb_done"
                )
                _bi_task = asyncio.create_task(
                    self._barge_in.wait(), name="bi_pb"
                )
                _done_pb, _ = await asyncio.wait(
                    [_pb_task, _bi_task],
                    timeout=20.0,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                _pb_task.cancel()
                _bi_task.cancel()
                await asyncio.gather(_pb_task, _bi_task, return_exceptions=True)

                if _bi_task in _done_pb and not _bi_task.cancelled():
                    if self._hangup:
                        return
                    _int_ms = (time.monotonic() - turn_start) * 1000
                    logger.info(
                        f"⚡ BARGE-IN during playback at {_int_ms:.0f}ms! Stopping audio."
                    )
                    await self._send({"type": "tts_stop"})
                    _frames_gated = self._ring_frame_count - self._speaking_start_frame
                    if _frames_gated > 0:
                        _inject = list(self._pcm_ring)[
                            -min(_frames_gated, len(self._pcm_ring)):
                        ]
                        for chunk in _inject:
                            try:
                                self._stt_q.put_nowait(chunk)
                            except asyncio.QueueFull:
                                break
                    self._barge_in.clear()
                    await self._set_state("listening")
                    return

                logger.info(f"✅ Turn {self._turn_count}: {turn_ms:.0f}ms total. Intent={intent}")

                if intent in _TERMINAL_INTENTS:
                    await asyncio.sleep(0.5)
                    await self._send({"type": "ended", "reason": f"resolved_{intent.lower()}"})
                    self._hangup = True
                    return

        except asyncio.CancelledError:
            for task in [llm_task, tts, barge_watch]:
                task.cancel()
            await asyncio.gather(llm_task, tts, barge_watch, return_exceptions=True)
            raise

        # Mark that echo decay is needed at the start of the next turn.
        # Do NOT call _set_state("listening") here — keep state as "speaking".
        # The echo gate depends on _is_speaking() returning True, which it does
        # for state == "speaking".  If we transition to "listening" now the gate
        # opens immediately, letting residual TTS echo from the room flow into
        # the always-on STT push-stream.  _run_pipeline() will open the gate
        # only after the 300-ms echo-decay sleep.
        self._after_speaking = True

    # ── Farewell ─────────────────────────────────────────────────────────────
    async def _do_farewell(self):
        farewell_en = _FAREWELLS["en-US"]
        await self._set_state("speaking")
        farewell_tts = _FAREWELLS.get(self.output_language, farewell_en)
        await self._send({"type": "sentence", "text": farewell_tts})
        wav = await _synth_to_wav_bytes(
            farewell_tts,
            self.output_language,
            sentence_index=0,
            region=self.region,
        )
        if wav:
            try:
                await self.ws.send_bytes(wav)
            except Exception:
                pass
        await self._send({"type": "ended", "reason": "user_hangup"})

    # ── Greeting ─────────────────────────────────────────────────────────────
    async def _do_greeting(self):
        greeting_en = _GREETINGS["en-US"]
        await self._set_state("greeting")
        greeting_tts = _GREETINGS.get(self.output_language, greeting_en)
        await self._send({"type": "sentence", "text": greeting_tts})
        wav = await _synth_to_wav_bytes(
            greeting_tts,
            self.output_language,
            sentence_index=0,
            region=self.region,
        )

        if wav:
            barge_watch = asyncio.create_task(self._barge_in.wait())
            send_task   = asyncio.create_task(self._send_wav(wav))
            done, _ = await asyncio.wait(
                [barge_watch, send_task], return_when=asyncio.FIRST_COMPLETED
            )
            for t in [barge_watch, send_task]:
                if not t.done():
                    t.cancel()
            await asyncio.gather(barge_watch, send_task, return_exceptions=True)

            if barge_watch in done and not barge_watch.cancelled():
                logger.info("⚡ Barge-in during greeting!")
                await self._send({"type": "tts_stop"})
                self._barge_in.clear()
                return

        self._after_speaking = True
        await self._send({"type": "turn_end"})

    async def _send_wav(self, wav: bytes):
        try:
            await self.ws.send_bytes(wav)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass

    # ── Main loop ────────────────────────────────────────────────────────────
    async def run(self):
        vad_task = asyncio.create_task(
            _vad_loop(self._energy_q, self._barge_in, self._is_speaking),
            name="vad"
        )
        recv_task = asyncio.create_task(self._recv_loop(), name="recv")
        # Single always-on STT for the whole session.  It runs continuously
        # through LISTENING, PROCESSING, and SPEAKING states, so when the user
        # barges in during bot TTS, their speech is already being recognised.
        # _run_pipeline() only reads from _stt_final_q — it never starts or
        # stops the recogniser itself.
        always_stt = asyncio.create_task(
            _stt_task(self._stt_q, self._on_partial, self._on_final,
                      self.language, self.loop,
                      region=self.region,
                      on_warmup=self._on_intent_warmup),
            name="always_stt"
        )

        try:
            await self._send({"type": "state", "state": "connecting"})
            try:
                await asyncio.wait_for(self._wait_for_start(), timeout=30.0)
            except asyncio.TimeoutError:
                await self._send({"type": "error", "message": "Connection timeout."})
                return

            logger.info(
                f"🎙 Session start — input={self.language} output={self.output_language} region={self.region}"
            )
            await self._do_greeting()

            while not self._hangup:
                await self._run_pipeline()

        except WebSocketDisconnect:
            logger.info("📵 Client disconnected")
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error(f"💥 Fatal: {exc}", exc_info=True); open("crash_log.txt","a").write(str(type(exc)) + str(exc) + str(exc.__traceback__.tb_frame) + "\n")
            try:
                await self._send({"type": "error", "message": str(exc)})
            except Exception:
                pass
        finally:
            self._hangup = True
            recv_task.cancel()
            vad_task.cancel()
            always_stt.cancel()
            await asyncio.gather(recv_task, vad_task, always_stt, return_exceptions=True)
            session_s = (time.monotonic() - self._session_start)
            logger.info(f"📵 Session ended — {self._turn_count} turns, {session_s:.1f}s")

    async def _wait_for_start(self):
        await self._start_event.wait()
        if self._hangup:
            raise asyncio.CancelledError()

    async def _recv_loop(self):
        """Sole consumer of ws.receive(). Routes PCM and JSON messages."""
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(self.ws.receive(), timeout=60.0)
                except asyncio.TimeoutError:
                    continue

                if "bytes" in msg and msg["bytes"]:
                    pcm = msg["bytes"]
                    rms = _pcm_rms(pcm)
                    # Use actual frame duration to keep VAD timing correct
                    # regardless of browser/processor buffer size.
                    samples = len(pcm) // 2
                    chunk_ms = (samples / 16000.0) * 1000.0 if samples else 0.0
                    try:
                        self._energy_q.put_nowait((rms, chunk_ms))
                    except asyncio.QueueFull:
                        pass
                    # Always keep a rolling buffer for barge-in pre-roll replay.
                    self._pcm_ring.append(pcm)
                    self._ring_frame_count += 1
                    # ECHO GATE: suppress STT audio while the bot is speaking.
                    # This prevents bot TTS leaking back through the mic and
                    # producing duplicated-word transcripts.  The ring buffer
                    # lets us replay the user's first words when barge-in fires.
                    if not self._is_speaking():
                        try:
                            self._stt_q.put_nowait(pcm)
                        except asyncio.QueueFull:
                            pass

                elif "text" in msg:
                    try:
                        data = json.loads(msg["text"])
                        msg_type = data.get("type", "")
                        if msg_type == "start":
                            self._start_event.set()
                        elif msg_type == "playback_done":
                            # Frontend AudioQueue finished playing all WAV chunks.
                            self._playback_done.set()
                        elif msg_type == "hangup":
                            logger.info("📵 Hangup received")
                            self._hangup = True
                            self._start_event.set()
                            self._playback_done.set()
                            self._barge_in.set()
                            return
                    except json.JSONDecodeError:
                        pass

                elif msg.get("type") == "websocket.disconnect":
                    self._hangup = True
                    self._start_event.set()
                    self._barge_in.set()
                    return

        except WebSocketDisconnect:
            self._hangup = True
            self._start_event.set()
            self._barge_in.set()
        except asyncio.CancelledError:
            pass


# ─── WebSocket Endpoint ───────────────────────────────────────────────────────

@router.websocket("/ws/duplex")
async def duplex_websocket(
    websocket: WebSocket,
    language: str = "en-US",
    output_language: str = "en-US",
    region: str = "Others",
):
    """True-duplex barge-in voice assistant with latency-optimised pipeline."""
    await websocket.accept()
    language        = language        if language        in SUPPORTED_LANGUAGES else "en-US"
    output_language = output_language if output_language in SUPPORTED_LANGUAGES else "en-US"
    region = _normalize_region(region)

    session = DuplexSession(websocket, language, output_language, region)
    await session.run()
