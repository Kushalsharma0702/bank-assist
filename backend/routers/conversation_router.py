"""
Bidirectional Conversation WebSocket  —  /ws/conversation
==========================================================

Wire protocol
─────────────
Client → Server
  binary frames : raw PCM Int16, 16 kHz, mono (streamed during user speech)
  text JSON     : {"type":"start"}  — call started / ready for first turn
                  {"type":"hangup"} — user clicked Hang Up

Server → Client
  text JSON     : {"type":"state",       "state": "greeting"|"listening"|"processing"|"speaking"|"ended"}
                  {"type":"partial_transcript", "text": "..."}
                  {"type":"final_transcript",   "text": "..."}
                  {"type":"bot_text_token",     "text": "..."}        — streaming Claude tokens
                  {"type":"bot_sentence",       "text": "..."}        — a translated/Khmer sentence
                  {"type":"intent",             "intent": "...", "confidence": 0.0}
                  {"type":"turn_complete"}                             — bot finished speaking
                  {"type":"ended",              "reason": "..."}      — call over
                  {"type":"error",              "message": "..."}
  binary frames : WAV audio for each sentence (sentence-streamed TTS)

Conversation loop
─────────────────
1. Bot sends greeting audio
2. Server streams PCM → Azure STT (push-stream with silence-based VAD)
3. Silence detected for >2 s → flush STT, close push-stream
4. Translate → Intent → Workflow → Claude → sentence TTS → send audio
5. After last WAV frame, server sends turn_complete and restarts step 2
6. Loop until: THANKS/REQUEST_AGENT resolved, user says "cut"/"bye"/"end call",
   or client sends {"type":"hangup"}
"""

import asyncio
import json
import logging
import os
import re
import tempfile
import threading
import time
from typing import AsyncIterator, List

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

logger     = logging.getLogger("ConversationRouter")
router     = APIRouter()
translator = TranslationService()
workflow   = WorkflowEngine()

# ── Terminal intents: end the call after the bot's response ──────────────────
_TERMINAL_INTENTS = {"THANKS", "REQUEST_AGENT"}
_HANGUP_PHRASES   = {
    "cut", "cut the call", "bye", "goodbye", "end call", "hang up",
    "hangup", "disconnect", "stop", "end conversation", "close",
}

_SENTENCE_END = re.compile(r'[.!?]["\')\\]]*\s')

# ─── System prompt ─────────────────────────────────────────────────────────────

def _build_system_prompt() -> str:
    return """\
You are Maya — a warm, intelligent real-time AI banking assistant on an active voice call.
Your job is to DIRECTLY HELP the customer through a multi-turn conversation.

CORE RULES:
- Never say "contact customer service", "visit the branch", or "call us".
- Instead TAKE ACTION and tell the customer what you are doing RIGHT NOW.
- Keep each response SHORT: 2-4 sentences MAX. This is a voice call — be concise.
- Never repeat the customer's full question back. Just answer it.
- Use "I'm doing X right now" language — sound immediate and capable.
- Give specific times: "30 seconds", "2-3 minutes", "5-7 days".
- Never say "I'm afraid", "unfortunately", "I cannot", "I don't have access".
- Output ONLY the response text — no JSON, no markdown, no labels.

CONVERSATION AWARENESS:
- You have access to the full conversation history.
- If the customer's query is resolved, end with "Is there anything else I can help you with?"
- If the customer says bye/goodbye/thank you at the end, give a warm farewell.

INTENT-SPECIFIC ACTIONS:

GREETING → Welcome warmly, state you are Maya from banking support, ask how you can help.

BALANCE → "I'm checking your account balance right now. Your current balance and recent transactions are available in your account summary. Would you like a mini-statement via SMS?"

STATEMENT → "I'm generating your 3-month statement now. It will be sent to your registered email within 2 minutes."

CARD_BLOCK → "I'm blocking your card immediately — it will be deactivated within 30 seconds. A replacement card will be dispatched in 5-7 days."

TX_DISPUTE → "I'm raising a dispute for this transaction right now. Your case ID will arrive by SMS. Disputes are resolved in 5-7 business days and your funds are protected."

KYC_STATUS → "Checking your KYC status now. If any documents are pending I'll tell you exactly what to upload — no branch visit needed."

EMI_DUE → "Your next EMI date and amount are based on your loan terms. I can send a full repayment schedule to your email right now."

FORECLOSURE → "I'm calculating your foreclosure amount now. Charges are typically 2-4% of outstanding principal. I can initiate the process today."

ADDRESS_CHANGE → "Updating your address now — an OTP will arrive on your registered mobile to confirm. Changes reflect in 24 hours."

COLLECTIONS_PTP → "Thank you for letting me know. I've recorded your commitment and paused follow-ups until then. I'm sending a payment link to your mobile now."

COLLECTIONS_PAYLINK → "Your secure payment link is being generated right now. You'll receive it on your registered mobile within 30 seconds."

PAYMENT_DIFFICULTY → "I understand completely. I can: (1) Restructure your EMI to lower the monthly amount, (2) Offer a 3-month payment holiday, or (3) Set up a custom repayment plan. Which works best?"

PARTIAL_PAYMENT → "I'm sending a secure payment link to your mobile right now. Pay any amount that works — I'll update your account instantly."

FULL_PAYMENT → "I'm processing your full payment now. Your secure payment link arrives on your mobile in 30 seconds."

CALLBACK → "Done — callback scheduled. Our specialist will call your registered number within 2 hours. SMS confirmation coming."

REQUEST_AGENT → "I'm connecting you to a live specialist now. I'm sharing your conversation so you won't need to repeat yourself. Wait time: 2-3 minutes."

THANKS → "You're very welcome! I'm glad I could help. Take care and have a great day!"

UNKNOWN → Ask one focused clarifying question to understand the customer's need.
"""


# ─── Claude streaming with conversation history ────────────────────────────────

async def _stream_claude_conv(
    transcript_en: str,
    intent: str,
    workflow_ctx: dict,
    history: List[dict],   # list of {"role": "user"|"assistant", "content": str}
) -> AsyncIterator[str]:
    """Yield Claude response tokens, maintaining multi-turn conversation history."""
    escalate = "  Note: escalate to human agent." if workflow_ctx.get("escalate") else ""
    paylink  = "  Note: send payment link."       if workflow_ctx.get("send_paylink") else ""

    # Build the user turn content
    user_content = (
        f"[Intent: {intent} | Action: {workflow_ctx.get('action','unknown')}]\n"
        f"{escalate}{paylink}\n"
        f"{transcript_en}"
    ).strip()

    # Build messages list from history + new turn.
    # IMPORTANT: Claude requires the first message to be 'user' role.
    # Drop any leading 'assistant' messages to satisfy this constraint.
    prior = [m for m in history]
    while prior and prior[0]["role"] != "user":
        prior.pop(0)

    messages = prior + [{"role": "user", "content": user_content}]

    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 350,
        "temperature": 0.35,
        "system": _build_system_prompt(),
        "messages": messages,
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


# ─── TTS helper ───────────────────────────────────────────────────────────────

def _tts_to_wav(text: str, language: str) -> bytes:
    """Synthesise text → WAV bytes. Blocking — run in thread pool."""
    if not text.strip():
        return b""
    speech_cfg = speechsdk.SpeechConfig(
        subscription=AZURE_SPEECH_KEY, region=AZURE_SPEECH_REGION
    )
    voice = VOICE_MAP.get(language, VOICE_MAP.get("en-US", "en-US-JennyNeural"))
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
    logger.warning(f"TTS failed for: {text[:60]!r}")
    return b""


# ─── Per-turn VAD-based STT ───────────────────────────────────────────────────

class SilenceVAD:
    """
    Simple energy-based Voice Activity Detector.
    Feeds PCM Int16 chunks into Azure STT push-stream.
    Signals end-of-utterance when:
      - Azure STT fires 'recognized' for a non-empty result, AND
      - there has been SILENCE_SEC seconds of silence since the last speech energy.
    """
    SILENCE_SEC   = 1.8    # seconds of silence to trigger end-of-utterance
    MIN_SPEECH_SEC = 0.3   # minimum speech before we consider ending
    RMS_THRESHOLD = 300    # Int16 RMS threshold to count as "speech"

    def __init__(self, push_stream, loop):
        self.push_stream       = push_stream
        self.loop              = loop
        self._last_speech_t    = time.monotonic()
        self._speech_started_t = None
        self._lock             = threading.Lock()

    def feed(self, pcm_bytes: bytes):
        """Feed raw PCM Int16 bytes. Compute RMS and update silence timer."""
        if len(pcm_bytes) < 2:
            return
        # PCM16 LE → sample values
        samples = [
            int.from_bytes(pcm_bytes[i:i+2], "little", signed=True)
            for i in range(0, len(pcm_bytes) - 1, 2)
        ]
        rms = (sum(s*s for s in samples) / len(samples)) ** 0.5
        now = time.monotonic()
        with self._lock:
            if rms > self.RMS_THRESHOLD:
                if self._speech_started_t is None:
                    self._speech_started_t = now
                self._last_speech_t = now

        self.push_stream.write(pcm_bytes)

    def should_stop(self) -> bool:
        """Return True when silence has lasted long enough after real speech."""
        now = time.monotonic()
        with self._lock:
            if self._speech_started_t is None:
                return False
            speech_duration = now - self._speech_started_t
            silence_duration = now - self._last_speech_t
            return (speech_duration >= self.MIN_SPEECH_SEC and
                    silence_duration >= self.SILENCE_SEC)


async def _listen_one_turn(
    websocket: WebSocket,
    language: str,
    send_json_fn,
    loop,
) -> dict | None:
    """
    Open one STT push-stream and collect one user utterance.
    Returns {"ok": True, "text": "..."} or {"ok": False, "text": reason}.
    Returns None if a hangup was received.
    """
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

    transcript_q: asyncio.Queue = asyncio.Queue()
    vad = SilenceVAD(push_stream, loop)

    def on_recognizing(evt):
        if evt.result.text:
            asyncio.run_coroutine_threadsafe(
                send_json_fn({"type": "partial_transcript", "text": evt.result.text}),
                loop,
            )

    def on_recognized(evt):
        if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
            asyncio.run_coroutine_threadsafe(
                transcript_q.put({"ok": True, "text": evt.result.text}), loop
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
    recognizer.start_continuous_recognition_async()

    hangup = False
    got_result = False

    try:
        while True:
            # Check VAD silence condition (non-blocking polling)
            if vad.should_stop() and not transcript_q.empty():
                break

            try:
                msg = await asyncio.wait_for(websocket.receive(), timeout=0.05)
            except asyncio.TimeoutError:
                # Check if transcript already available (VAD triggered)
                if vad.should_stop() and not transcript_q.empty():
                    break
                continue

            if "bytes" in msg and msg["bytes"]:
                vad.feed(msg["bytes"])
            elif "text" in msg:
                try:
                    data = json.loads(msg["text"])
                    if data.get("type") == "hangup":
                        hangup = True
                        break
                    elif data.get("type") == "audio_end":
                        # Client signals end of user speech manually
                        break
                except json.JSONDecodeError:
                    pass

    finally:
        push_stream.close()
        recognizer.stop_continuous_recognition_async()

    if hangup:
        return None

    # Give recognizer up to 5 s to deliver the final result
    try:
        result = await asyncio.wait_for(transcript_q.get(), timeout=5.0)
    except asyncio.TimeoutError:
        return {"ok": False, "text": "Timeout waiting for transcript"}

    return result


# ─── Bot response turn: Claude + sentence TTS ─────────────────────────────────

async def _bot_respond(
    websocket: WebSocket,
    transcript_en: str,
    intent: str,
    workflow_ctx: dict,
    history: List[dict],
    output_language: str,
    send_json_fn,
) -> str:
    """
    Stream Claude response, translate to output_language, synthesise TTS, send WAV.
    Returns the full English response text.
    """
    response_en     = ""
    sentence_buffer = ""

    tts_queue: asyncio.Queue = asyncio.Queue()

    async def tts_worker():
        while True:
            sentence_en = await tts_queue.get()
            if sentence_en is None:
                break
            # Translate to the output language, then TTS with that language's voice
            if output_language == "en-US":
                tts_text = sentence_en
            else:
                tts_text, _ = await translator.translate_to_language(sentence_en, output_language)
            await send_json_fn({"type": "bot_sentence", "text": tts_text, "language": output_language})
            wav = await asyncio.get_event_loop().run_in_executor(
                None, _tts_to_wav, tts_text, output_language
            )
            if wav:
                try:
                    await websocket.send_bytes(wav)
                except Exception:
                    pass

    worker_task = asyncio.create_task(tts_worker())

    async for token in _stream_claude_conv(transcript_en, intent, workflow_ctx, history):
        response_en     += token
        sentence_buffer += token
        await send_json_fn({"type": "bot_text_token", "text": token})

        if _SENTENCE_END.search(sentence_buffer):
            parts = _SENTENCE_END.split(sentence_buffer)
            for s in parts[:-1]:
                s = s.strip()
                if s:
                    await tts_queue.put(s)
            sentence_buffer = parts[-1] if parts[-1] else ""

    if sentence_buffer.strip():
        await tts_queue.put(sentence_buffer.strip())

    await tts_queue.put(None)
    await worker_task

    return response_en


# ─── Check if user wants to end the call ──────────────────────────────────────

def _is_hangup_phrase(text: str) -> bool:
    t = text.lower().strip()
    return any(phrase in t for phrase in _HANGUP_PHRASES)


# ─── Main WebSocket endpoint ──────────────────────────────────────────────────

@router.websocket("/ws/conversation")
async def conversation_websocket(
    websocket: WebSocket,
    language: str = "km-KH",
    output_language: str = "km-KH",
):
    """
    Bidirectional conversation loop.
    language        : STT / input language (what the customer speaks)
    output_language : TTS / output language (what Maya speaks back)
    Sends a greeting, then listens → processes → speaks, in a loop
    until the call is naturally resolved or the user hangs up.
    """
    await websocket.accept()
    language        = language        if language        in SUPPORTED_LANGUAGES else "en-US"
    output_language = output_language if output_language in SUPPORTED_LANGUAGES else "km-KH"
    loop     = asyncio.get_event_loop()

    async def send_json(obj: dict):
        try:
            await websocket.send_json(obj)
        except Exception:
            pass

    # Conversation history for Claude multi-turn context
    history: List[dict] = []
    turn_number = 0

    try:
        # ── Wait for client "start" signal ────────────────────────────────────
        await send_json({"type": "state", "state": "connecting"})
        try:
            msg = await asyncio.wait_for(websocket.receive(), timeout=30.0)
            if "text" in msg:
                data = json.loads(msg.get("text", "{}"))
                if data.get("type") == "hangup":
                    await send_json({"type": "ended", "reason": "hangup"})
                    return
        except asyncio.TimeoutError:
            await send_json({"type": "error", "message": "Connection timeout"})
            return

        # ── Greeting turn (bot speaks first) ─────────────────────────────────
        turn_number += 1
        logger.info(f"[Conv] Starting — input={language}  output={output_language}")
        await send_json({"type": "state", "state": "greeting"})

        GREETING_EN = (
            "Hello! I'm Maya, your AI banking assistant. "
            "I'm here to help you right away. "
            "How can I assist you today?"
        )
        # Translate greeting to output language for TTS
        if output_language == "en-US":
            greeting_tts = GREETING_EN
        else:
            greeting_tts, _ = await translator.translate_to_language(GREETING_EN, output_language)
        await send_json({"type": "bot_sentence", "text": greeting_tts, "language": output_language})
        greeting_wav = await asyncio.get_event_loop().run_in_executor(
            None, _tts_to_wav, greeting_tts, output_language
        )
        if greeting_wav:
            await websocket.send_bytes(greeting_wav)

        # NOTE: Do NOT add the greeting to Claude history.
        # Claude requires the FIRST message to be 'user' role.
        # The greeting is hardcoded — Claude will see it via the system prompt context.
        await send_json({"type": "turn_complete", "turn": 0})

        # ── Main conversation loop ─────────────────────────────────────────────
        while True:
            turn_number += 1
            logger.info(f"[Conv] Turn {turn_number} — listening…")
            await send_json({"type": "state", "state": "listening", "turn": turn_number})

            # Listen for user input
            result = await _listen_one_turn(websocket, language, send_json, loop)

            if result is None:
                # Hangup received
                logger.info("[Conv] Hangup received during listening")
                await send_json({"type": "ended", "reason": "hangup"})
                return

            if not result["ok"]:
                # No speech or error — prompt again
                transcript = result["text"]
                logger.info(f"[Conv] No speech: {transcript}")
                await send_json({"type": "state", "state": "speaking"})
                no_speech_en = "I didn't catch that — could you please speak again?"
                if output_language == "en-US":
                    ns_tts = no_speech_en
                else:
                    ns_tts, _ = await translator.translate_to_language(no_speech_en, output_language)
                await send_json({"type": "bot_sentence", "text": ns_tts, "language": output_language})
                ns_wav = await asyncio.get_event_loop().run_in_executor(
                    None, _tts_to_wav, ns_tts, output_language
                )
                if ns_wav:
                    await websocket.send_bytes(ns_wav)
                await send_json({"type": "turn_complete", "turn": turn_number})
                continue

            transcript = result["text"]
            await send_json({"type": "final_transcript", "text": transcript})
            logger.info(f"[Conv] Turn {turn_number} transcript: {transcript!r}")

            # Check for explicit hangup phrases
            if _is_hangup_phrase(transcript):
                await send_json({"type": "state", "state": "speaking"})
                farewell_en = "Thank you for calling. Have a wonderful day! Goodbye!"
                if output_language == "en-US":
                    farewell_tts = farewell_en
                else:
                    farewell_tts, _ = await translator.translate_to_language(farewell_en, output_language)
                await send_json({"type": "bot_sentence", "text": farewell_tts, "language": output_language})
                farewell_wav = await asyncio.get_event_loop().run_in_executor(
                    None, _tts_to_wav, farewell_tts, output_language
                )
                if farewell_wav:
                    await websocket.send_bytes(farewell_wav)
                await send_json({"type": "ended", "reason": "user_hangup"})
                return

            # Translate user message to English for processing
            await send_json({"type": "state", "state": "processing"})
            english, _ = await translator.translate_to_english(transcript, language)
            logger.info(f"[Conv] EN: {english!r}")
            # Send English translation back to UI so it can be shown
            await send_json({
                "type": "translation",
                "language": "en-US",
                "text": english,
            })

            # Detect intent
            intent, conf, phrase, method, _ = await get_intent_router().route(english)
            await send_json({
                "type": "intent",
                "intent": intent,
                "confidence": round(conf, 3),
                "matched_phrase": phrase,
            })
            logger.info(f"[Conv] Intent={intent} ({conf:.2%})")

            # Workflow context
            workflow_ctx, _ = await workflow.process(intent, english)

            # Add user turn to history
            history.append({"role": "user", "content": english})

            # Generate and stream bot response
            await send_json({"type": "state", "state": "speaking"})
            response_en = await _bot_respond(
                websocket, english, intent, workflow_ctx, history[:-1],
                output_language, send_json,
            )

            # Add bot response to history
            history.append({"role": "assistant", "content": response_en})
            logger.info(f"[Conv] Bot: {response_en!r}")

            await send_json({"type": "turn_complete", "turn": turn_number})

            # Check if call should end naturally
            if intent in _TERMINAL_INTENTS:
                logger.info(f"[Conv] Terminal intent '{intent}' — ending call.")
                await asyncio.sleep(0.5)
                await send_json({"type": "ended", "reason": f"resolved_{intent.lower()}"})
                return

            # Continue loop → go back to listening

    except WebSocketDisconnect:
        logger.info("[Conv] Client disconnected")
    except asyncio.TimeoutError:
        await send_json({"type": "error", "message": "Timeout — please try again."})
    except Exception as exc:
        logger.error(f"[Conv] Error: {exc}", exc_info=True)
        try:
            await send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass
