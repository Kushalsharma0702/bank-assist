"""
Pipeline Orchestrator.

Coordinates all services and returns a PipelineResult with per-stage timing.

Full flow:
  Audio → STT → Translate → Intent Router → Workflow → Claude Response
        → Translate to Native Language → TTS → PipelineResult
"""

import logging
import os
import time
from typing import List

from exceptions import NoSpeechDetectedError
from models.intent_models import (
    LANGUAGE_CONFIG,
    SUPPORTED_LANGUAGES,
    PipelineResult,
    PipelineStage,
)
from services.stt_service       import SpeechToTextService
from services.translation_service import TranslationService
from services.intent_router     import get_intent_router
from services.workflow_engine   import WorkflowEngine
from services.response_service  import ResponseService
from services.tts_service       import TextToSpeechService
from services.sarvam_stt_service import SarvamSpeechToTextService
from services.sarvam_tts_service import SarvamTextToSpeechService

logger = logging.getLogger("PipelineOrchestrator")

# Friendly "no speech detected" messages  (en, native)
_NO_SPEECH: dict = {
    "km-KH": ("I didn't hear anything. Please try again.",
               "ខ្ញុំមិនបានឮអ្វីទេ។ សូមព្យាយាមម្តងទៀត។"),
    "en-US": ("I didn't hear anything. Please try again.",
               "I didn't hear anything. Please try again."),
    "vi-VN": ("I didn't hear anything. Please try again.",
               "Tôi không nghe thấy gì. Vui lòng thử lại."),
    "th-TH": ("I didn't hear anything. Please try again.",
               "ฉันไม่ได้ยินอะไร กรุณาลองอีกครั้ง"),
    "zh-CN": ("I didn't hear anything. Please try again.",
               "我没有听到任何内容。请再试一次。"),
    "hi-IN": ("I didn't hear anything. Please try again.",
               "मैंने कुछ नहीं सुना। कृपया पुनः प्रयास करें।"),
    "id-ID": ("I didn't hear anything. Please try again.",
               "Saya tidak mendengar apa pun. Silakan coba lagi."),
    "ms-MY": ("I didn't hear anything. Please try again.",
               "Saya tidak mendengar apa-apa. Sila cuba lagi."),
}

_STAGE_META = [
    ("STT",                 "🎤"),
    ("Translation",         "🌐"),
    ("Intent Detection",    "🎯"),
    ("Workflow Engine",     "⚙️"),
    ("Claude Response",     "🤖"),
    ("Native Translation",  "🌏"),
    ("TTS Audio",           "🔊"),
]


def _pending_stages() -> List[PipelineStage]:
    return [PipelineStage(name=n, icon=i, status="pending") for n, i in _STAGE_META]


class PipelineOrchestrator:
    """Runs the full voice/text processing pipeline."""

    def __init__(self):
        self._azure_stt  = SpeechToTextService()
        self._sarvam_stt = SarvamSpeechToTextService()
        self._translator = TranslationService()
        self._workflow   = WorkflowEngine()
        self._responder  = ResponseService()
        self._azure_tts  = TextToSpeechService()
        self._sarvam_tts = SarvamTextToSpeechService()

    @property
    def _intent_router(self):
        return get_intent_router()

    @staticmethod
    def _normalize_region(region: str) -> str:
        return "India" if str(region or "Others").strip().lower() == "india" else "Others"

    def _get_stt_service(self, region: str):
        return self._sarvam_stt if self._normalize_region(region) == "India" else self._azure_stt

    def _get_tts_service(self, region: str):
        return self._sarvam_tts if self._normalize_region(region) == "India" else self._azure_tts

    # ------------------------------------------------------------------ #
    #  VOICE INPUT
    # ------------------------------------------------------------------ #

    async def process_audio(
        self, audio_file_path: str, language: str = "km-KH", region: str = "Others"
    ) -> PipelineResult:
        # selected_language = what the user chose on the frontend (drives TTS voice)
        # detected_lang     = what Azure STT actually detected in the audio (drives input translation)
        selected_language = language if language in SUPPORTED_LANGUAGES else "en-US"
        lang_cfg          = LANGUAGE_CONFIG[selected_language]
        lang_name         = lang_cfg["name"]
        total_start       = time.perf_counter()

        stages = _pending_stages()

        # ── Stage 0: STT ────────────────────────────────────────────────
        stages[0].status = "running"
        detected_lang    = selected_language   # default; overwritten on success
        try:
            stt_service = self._get_stt_service(region)
            transcript, detected_lang, stt_ms = await stt_service.transcribe(
                audio_file_path, selected_language
            )
            stages[0].status     = "done"
            stages[0].latency_ms = stt_ms
            stages[0].output     = transcript
            logger.info(
                f"STT detected={detected_lang!r}  selected={selected_language!r}  "
                f"transcript={transcript!r}"
            )
            # ⚠️  Do NOT overwrite selected_language with detected_lang.
            # detected_lang is used only to know the source language for Stage 1
            # translation. The response language (Stage 5) and TTS voice (Stage 6)
            # are always driven by selected_language.
        except NoSpeechDetectedError:
            stages[0].status  = "error"
            stages[0].output  = "No speech detected"
            return await self._no_speech_result(
                selected_language, lang_name, stages, total_start, region
            )
        except Exception as exc:
            stages[0].status = "error"
            stages[0].output = str(exc)
            raise

        # ── Stage 1: Translate input to English ─────────────────────────
        # Use detected_lang as the source so the translation is correct even
        # when Azure mis-detects language but the user's selected language is right.
        source_for_translation = (
            detected_lang if detected_lang in SUPPORTED_LANGUAGES else selected_language
        )
        stages[1].status = "running"
        english_text, trans_ms = await self._translator.translate_to_english(
            transcript, source_for_translation
        )
        stages[1].status     = "done"
        stages[1].latency_ms = trans_ms
        stages[1].output     = english_text

        return await self._run_stages_2_to_6(
            transcript, english_text, detected_lang, selected_language, lang_name,
            stages, total_start, region
        )

    # ------------------------------------------------------------------ #
    #  TEXT INPUT
    # ------------------------------------------------------------------ #

    async def process_text(
        self, text: str, language: str = "km-KH", region: str = "Others"
    ) -> PipelineResult:
        selected_language = language if language in SUPPORTED_LANGUAGES else "en-US"
        lang_cfg  = LANGUAGE_CONFIG[selected_language]
        lang_name = lang_cfg["name"]
        total_start = time.perf_counter()

        stages = _pending_stages()

        # Stage 0 is skipped for text input
        stages[0].status     = "done"
        stages[0].latency_ms = 0.0
        stages[0].output     = text

        # ── Stage 1: Translation ─────────────────────────────────────────
        stages[1].status = "running"
        english_text, trans_ms = await self._translator.translate_to_english(
            text, selected_language
        )
        stages[1].status     = "done"
        stages[1].latency_ms = trans_ms
        stages[1].output     = english_text

        return await self._run_stages_2_to_6(
            text, english_text, selected_language, selected_language, lang_name,
            stages, total_start, region
        )

    # ------------------------------------------------------------------ #
    #  SHARED STAGES 2–6
    # ------------------------------------------------------------------ #

    async def _run_stages_2_to_6(
        self,
        transcript: str,
        english_text: str,
        detected_language: str,
        selected_language: str,
        lang_name: str,
        stages: List[PipelineStage],
        total_start: float,
        region: str,
    ) -> PipelineResult:

        # ── Stage 2: Intent Detection ────────────────────────────────────
        stages[2].status = "running"
        intent, confidence, matched_phrase, method, intent_ms = (
            await self._intent_router.route(english_text)
        )
        stages[2].status         = "done"
        stages[2].latency_ms     = intent_ms
        stages[2].output         = intent
        stages[2].confidence     = confidence
        stages[2].matched_phrase = matched_phrase
        logger.info(f"IntentRouter | Intent: {intent}  confidence={confidence:.2f}  method={method}")

        # ── Stage 3: Workflow Engine ──────────────────────────────────────
        stages[3].status = "running"
        workflow_ctx, wf_ms = await self._workflow.process(intent, english_text)
        stages[3].status     = "done"
        stages[3].latency_ms = wf_ms
        stages[3].output     = workflow_ctx["summary"]

        # ── Stage 4: Claude Response (always in English) ──────────────────
        stages[4].status = "running"
        response_en, llm_ms = await self._responder.generate(
            english_text, intent, workflow_ctx
        )
        stages[4].status     = "done"
        stages[4].latency_ms = llm_ms
        stages[4].output     = response_en
        logger.info(f"ResponseService | Claude response (EN): {response_en[:100]!r}")

        # ── Stage 5: Translate response → selected language ───────────────
        # This uses selected_language (what the user picked on the frontend),
        # NOT detected_language (what Azure STT guessed). This is the fix that
        # ensures Khmer users always get a Khmer response regardless of whether
        # Azure STT classified their speech as "en-US".
        stages[5].status = "running"
        response_native, ntrans_ms = await self._translator.translate_to_language(
            response_en, selected_language
        )
        stages[5].status     = "done"
        stages[5].latency_ms = ntrans_ms
        stages[5].output     = response_native

        # Always populate response_khmer.  If selected_language is already km-KH
        # we reuse response_native to avoid a redundant API call.
        if selected_language == "km-KH":
            response_khmer   = response_native
            khmer_trans_ms   = ntrans_ms
        else:
            response_khmer, khmer_trans_ms = await self._translator.translate_to_khmer(
                response_en
            )
        logger.info(f"TranslationService | Translated → Khmer: {response_khmer[:80]!r}")

        # ── Stage 6: TTS using selected_language voice ────────────────────
        stages[6].status = "running"
        tts_text = response_native if selected_language != "en-US" else response_en
        tts_service = self._get_tts_service(region)
        audio_path, audio_b64, voice_used, tts_ms = await tts_service.synthesize(
            tts_text, selected_language
        )
        stages[6].status     = "done"
        stages[6].latency_ms = tts_ms
        stages[6].output     = f"Audio generated via {voice_used}"
        logger.info(f"TTSService | Synthesizing TTS ({voice_used})")

        processing_time = time.perf_counter() - total_start

        return PipelineResult(
            language             = selected_language,
            detected_language    = detected_language,
            native_language_name = lang_name,
            transcript           = transcript,
            english_translation  = english_text,
            intent               = intent,
            matched_phrase       = matched_phrase,
            confidence           = confidence,
            intent_method        = method,
            workflow_action      = workflow_ctx["action"],
            escalate             = workflow_ctx["escalate"],
            send_paylink         = workflow_ctx["send_paylink"],
            response_en          = response_en,
            response_native      = response_native,
            response_khmer       = response_khmer,
            tts_audio_url        = f"/audio/{os.path.basename(audio_path)}",
            tts_audio_base64     = audio_b64,
            tts_voice            = voice_used,
            processing_time      = processing_time,
            pipeline_stages      = stages,
            no_speech            = False,
        )

    # ------------------------------------------------------------------ #
    #  NO-SPEECH HELPER
    # ------------------------------------------------------------------ #

    async def _no_speech_result(
        self, selected_language: str, lang_name: str, stages, total_start, region: str = "Others"
    ) -> PipelineResult:
        resp_en, resp_native = _NO_SPEECH.get(selected_language, _NO_SPEECH["en-US"])

        # Khmer version of the no-speech message
        _, resp_khmer = _NO_SPEECH.get("km-KH", _NO_SPEECH["en-US"])
        if selected_language == "km-KH":
            resp_khmer = resp_native

        # Mark remaining stages as skipped
        for s in stages[1:]:
            s.status = "pending"

        # Synthesise the "please try again" audio in the selected language
        audio_path = audio_b64 = voice_used = ""
        try:
            tts_service = self._get_tts_service(region)
            audio_path, audio_b64, voice_used, _ = await tts_service.synthesize(
                resp_native, selected_language
            )
        except Exception as exc:
            logger.error(f"No-speech TTS failed: {exc}")

        processing_time = time.perf_counter() - total_start

        return PipelineResult(
            language             = selected_language,
            detected_language    = selected_language,
            native_language_name = lang_name,
            transcript           = "",
            english_translation  = "",
            intent               = "UNKNOWN",
            matched_phrase       = "",
            confidence           = 0.0,
            intent_method        = "none",
            workflow_action      = "none",
            escalate             = False,
            send_paylink         = False,
            response_en          = resp_en,
            response_native      = resp_native,
            response_khmer       = resp_khmer,
            tts_audio_url        = f"/audio/{os.path.basename(audio_path)}" if audio_path else "",
            tts_audio_base64     = audio_b64,
            tts_voice            = voice_used,
            processing_time      = processing_time,
            pipeline_stages      = stages,
            no_speech            = True,
        )
