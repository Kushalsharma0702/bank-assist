"""
Sarvam Speech-to-Text service for India region routing.
"""

import logging
import time
from typing import Tuple

from config import SARVAM_API_KEY, SARVAM_STT_MODEL
from exceptions import NoSpeechDetectedError

logger = logging.getLogger("SarvamSTTService")


def _to_sarvam_language_code(language: str) -> str:
    """Map frontend BCP-47 language to the code Sarvam saaras:v3 accepts.
    Providing the hint improves accuracy; 'unknown' forces full auto-detect."""
    mapping = {
        "hi-IN": "hi-IN",
        "bn-IN": "bn-IN",
        "bn-BD": "bn-IN",
        "ta-IN": "ta-IN",
        "ta-LK": "ta-IN",
        "te-IN": "te-IN",
        "kn-IN": "kn-IN",
        "ml-IN": "ml-IN",
        "mr-IN": "mr-IN",
        "gu-IN": "gu-IN",
        "pa-IN": "pa-IN",
        "or-IN": "od-IN",  # Sarvam uses od-IN for Odia
        "en-IN": "en-IN",
        "en-US": "en-IN",
    }
    return mapping.get(language, "unknown")


class SarvamSpeechToTextService:
    """Sarvam batch STT adapter with the same return contract as Azure STT service."""

    def __init__(self):
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client

        if not SARVAM_API_KEY:
            raise RuntimeError("SARVAM_API_KEY is missing")

        try:
            from sarvamai import SarvamAI
        except Exception as exc:
            raise RuntimeError(
                "sarvamai package is required for India/Sarvam region mode"
            ) from exc

        self._client = SarvamAI(api_subscription_key=SARVAM_API_KEY)
        return self._client

    async def transcribe(
        self,
        audio_file_path: str,
        language: str = "hi-IN",
        preprocess: bool = True,
    ) -> Tuple[str, str, float]:
        """
        Transcribe audio through Sarvam STT.

        Returns:
            (transcript, detected_language_code, latency_ms)
        """
        _ = preprocess  # kept for interface compatibility
        t0 = time.perf_counter()
        client = self._get_client()
        language_code = _to_sarvam_language_code(language)

        def _do_transcribe():
            with open(audio_file_path, "rb") as f:
                return client.speech_to_text.transcribe(
                    file=("input.wav", f, "audio/wav"),
                    model=SARVAM_STT_MODEL,
                    language_code=language_code,
                )

        response = await __import__("asyncio").to_thread(_do_transcribe)
        transcript = (getattr(response, "transcript", "") or "").strip()
        detected = getattr(response, "language_code", "") or language or "en-IN"
        if not transcript:
            raise NoSpeechDetectedError("No speech detected in audio")
        latency_ms = (time.perf_counter() - t0) * 1000

        logger.info(
            "Sarvam STT complete (%s): %r [%dms]",
            detected,
            transcript,
            int(latency_ms),
        )
        return transcript, detected, latency_ms
