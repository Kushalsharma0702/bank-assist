"""
Sarvam Text-to-Speech service for India region routing.
"""

import base64
import logging
import tempfile
import time
from typing import Tuple

from config import SARVAM_API_KEY, SARVAM_TTS_MODEL, SARVAM_TTS_SPEAKER

logger = logging.getLogger("SarvamTTSService")


def _to_sarvam_language_code(language: str) -> str:
    """Map frontend language to Sarvam-compatible language code."""
    mapping = {
        "en-US": "en-IN",
        "en-IN": "en-IN",
        "hi-IN": "hi-IN",
        "ta-IN": "ta-IN",
        "te-IN": "te-IN",
        "bn-BD": "bn-IN",
        "bn-IN": "bn-IN",
        "gu-IN": "gu-IN",
        "mr-IN": "mr-IN",
        "kn-IN": "kn-IN",
        "ml-IN": "ml-IN",
        "pa-IN": "pa-IN",
        "or-IN": "od-IN",  # Sarvam uses od-IN for Odia (not or-IN)
    }
    return mapping.get(language, "hi-IN")


class SarvamTextToSpeechService:
    """Sarvam batch TTS adapter with the same return shape as Azure TTS service."""

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

    async def synthesize(
        self,
        text: str,
        language: str = "hi-IN",
        output_file: str = "",
        use_ssml: bool = True,
        humanize: bool = True,
    ) -> Tuple[str, str, str, float]:
        """
        Synthesize text through Sarvam TTS.

        Returns:
            (audio_file_path, audio_base64, voice_name, latency_ms)
        """
        _ = use_ssml
        _ = humanize
        t0 = time.perf_counter()
        client = self._get_client()
        target_language = _to_sarvam_language_code(language)

        def _do_tts():
            return client.text_to_speech.convert(
                text=text,
                target_language_code=target_language,
                model=SARVAM_TTS_MODEL,
                speaker=SARVAM_TTS_SPEAKER,
            )

        response = await __import__("asyncio").to_thread(_do_tts)
        if not hasattr(response, "audios") or not response.audios:
            raise RuntimeError("Sarvam TTS did not return audio")

        audio_b64 = response.audios[0]
        audio_bytes = base64.b64decode(audio_b64)

        if not output_file:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
            output_file = tmp.name
            tmp.close()

        with open(output_file, "wb") as f:
            f.write(audio_bytes)

        latency_ms = (time.perf_counter() - t0) * 1000
        voice_name = f"sarvam:{SARVAM_TTS_SPEAKER}"
        logger.info(
            "Sarvam TTS complete (%s): %d chars [%dms]",
            target_language,
            len(audio_b64),
            int(latency_ms),
        )
        return output_file, audio_b64, voice_name, latency_ms
