"""
Advanced Azure Text-to-Speech service.
Features:
- Humanized voice with SSML (prosody, emotion, pauses)
- Natural speaking rate and pitch control
- Khmer and English support with proper phonetics
- Base64 encoding for frontend playback
"""

import base64
import logging
import os
import time
import re
from typing import Tuple
from xml.sax.saxutils import escape

import azure.cognitiveservices.speech as speechsdk

from config import AZURE_SPEECH_KEY, AZURE_SPEECH_REGION
from models.intent_models import LANGUAGE_CONFIG

logger = logging.getLogger("TTSService")

# Voice map with humanization profiles
VOICE_MAP: dict = {
    "ar-SA": {"voice": "ar-SA-ZariyahNeural", "rate": 0.95, "pitch": 1.0, "emotion": None},
    "bn-BD": {"voice": "bn-BD-NabanitaNeural", "rate": 0.95, "pitch": 1.0, "emotion": None},
    "de-DE": {"voice": "de-DE-KatjaNeural", "rate": 0.95, "pitch": 1.0, "emotion": None},
    "en-US": {"voice": "en-US-JennyNeural", "rate": 0.95, "pitch": 1.0, "emotion": "friendly"},
    "es-ES": {"voice": "es-ES-ElviraNeural", "rate": 0.95, "pitch": 1.0, "emotion": None},
    "fil-PH": {"voice": "fil-PH-BlessicaNeural", "rate": 0.95, "pitch": 1.0, "emotion": None},
    "fr-FR": {"voice": "fr-FR-DeniseNeural", "rate": 0.95, "pitch": 1.0, "emotion": None},
    "hi-IN": {"voice": "hi-IN-SwaraNeural", "rate": 0.95, "pitch": 1.0, "emotion": None},
    "id-ID": {"voice": "id-ID-GadisNeural", "rate": 0.95, "pitch": 1.0, "emotion": None},
    "it-IT": {"voice": "it-IT-ElsaNeural", "rate": 0.95, "pitch": 1.0, "emotion": None},
    "ja-JP": {"voice": "ja-JP-NanamiNeural", "rate": 0.95, "pitch": 1.0, "emotion": None},
    "km-KH": {"voice": "km-KH-PisethNeural", "rate": 0.95, "pitch": 1.0, "emotion": None},
    "ko-KR": {"voice": "ko-KR-SunHiNeural", "rate": 0.95, "pitch": 1.0, "emotion": None},
    "ms-MY": {"voice": "ms-MY-YasminNeural", "rate": 0.95, "pitch": 1.0, "emotion": None},
    "nl-NL": {"voice": "nl-NL-ColetteNeural", "rate": 0.95, "pitch": 1.0, "emotion": None},
    "pl-PL": {"voice": "pl-PL-ZofiaNeural", "rate": 0.95, "pitch": 1.0, "emotion": None},
    "pt-BR": {"voice": "pt-BR-FranciscaNeural", "rate": 0.95, "pitch": 1.0, "emotion": None},
    "ru-RU": {"voice": "ru-RU-SvetlanaNeural", "rate": 0.95, "pitch": 1.0, "emotion": None},
    "si-LK": {"voice": "si-LK-ThiliniNeural", "rate": 0.95, "pitch": 1.0, "emotion": None},
    "sv-SE": {"voice": "sv-SE-SofieNeural", "rate": 0.95, "pitch": 1.0, "emotion": None},
    "ta-IN": {"voice": "ta-IN-PallaviNeural", "rate": 0.95, "pitch": 1.0, "emotion": None},
    "ta-LK": {"voice": "ta-LK-SaranyaNeural", "rate": 0.95, "pitch": 1.0, "emotion": None},
    "te-IN": {"voice": "te-IN-ShrutiNeural", "rate": 0.95, "pitch": 1.0, "emotion": None},
    "th-TH": {"voice": "th-TH-PremwadeeNeural", "rate": 0.95, "pitch": 1.0, "emotion": None},
    "tr-TR": {"voice": "tr-TR-EmelNeural", "rate": 0.95, "pitch": 1.0, "emotion": None},
    "uk-UA": {"voice": "uk-UA-PolinaNeural", "rate": 0.95, "pitch": 1.0, "emotion": None},
    "ur-PK": {"voice": "ur-PK-UzmaNeural", "rate": 0.95, "pitch": 1.0, "emotion": None},
    "vi-VN": {"voice": "vi-VN-HoaiMyNeural", "rate": 0.95, "pitch": 1.0, "emotion": None},
    "zh-CN": {"voice": "zh-CN-XiaoxiaoNeural", "rate": 0.90, "pitch": 1.0, "emotion": None},
    "zh-HK": {"voice": "zh-HK-HiuMaanNeural", "rate": 0.90, "pitch": 1.0, "emotion": None},
    "zh-TW": {"voice": "zh-TW-HsiaoChenNeural", "rate": 0.90, "pitch": 1.0, "emotion": None},
}


class TextToSpeechService:
    """Azure Neural TTS with humanization and SSML support."""

    def _build_ssml(
        self,
        text: str,
        language: str = "km-KH",
        add_pauses: bool = True,
        emotion_enabled: bool = True,
    ) -> str:
        """
        Build Speech Synthesis Markup Language (SSML) for natural sounding speech.

        Args:
            text: Text to synthesize
            language: Language code (e.g., "km-KH")
            add_pauses: Insert natural pauses at sentence boundaries
            emotion_enabled: Use emotion expression (if supported by voice)

        Returns:
            SSML-formatted string
        """
        profile = VOICE_MAP.get(language, VOICE_MAP["en-US"])
        voice = profile["voice"]
        rate = profile["rate"]
        pitch = profile["pitch"]

        # Build phoneme-friendly text (handle special cases)
        clean_text = escape(text.strip())

        # Add natural pauses after punctuation
        if add_pauses:
            clean_text = re.sub(r'([.!?])\s+', r'\1<break time="500ms"/> ', clean_text)
            clean_text = re.sub(r',\s+', ',<break time="200ms"/> ', clean_text)

        # Build SSML with prosody control
        ssml = f'<speak version="1.0" xml:lang="{language}">'
        ssml += f'<voice name="{voice}">'
        
        # Add rate and pitch control
        ssml += f'<prosody rate="{rate:.2f}" pitch="{pitch:.2f}">'
        
        # Add emotion if supported
        if emotion_enabled and profile["emotion"]:
            ssml += f'<amazon:emotion name="{profile["emotion"]}" intensity="medium">'
            ssml += clean_text
            ssml += '</amazon:emotion>'
        else:
            ssml += clean_text

        ssml += '</prosody>'
        ssml += '</voice>'
        ssml += '</speak>'

        logger.debug(f"SSML: {ssml[:200]}…")
        return ssml

    async def synthesize(
        self,
        text: str,
        language: str = "km-KH",
        output_file: str = "",
        use_ssml: bool = True,
        humanize: bool = True,
    ) -> Tuple[str, str, str, float]:
        """
        Synthesize text to speech with humanization.

        Args:
            text: Text to synthesize (target language)
            language: BCP-47 code (e.g., "km-KH")
            output_file: Optional WAV output path
            use_ssml: Use SSML for better prosody control
            humanize: Add natural pauses and emotion

        Returns:
            (audio_file_path, audio_base64, voice_name, latency_ms)
        """
        t0 = time.perf_counter()
        try:
            speech_config = speechsdk.SpeechConfig(
                subscription=AZURE_SPEECH_KEY,
                region=AZURE_SPEECH_REGION,
            )

            # Get voice profile
            profile = VOICE_MAP.get(language)
            if not profile:
                logger.warning(
                    f"No voice mapping for language '{language}', "
                    "defaulting to km-KH-PisethNeural"
                )
                profile = VOICE_MAP["km-KH"]

            voice = profile["voice"]
            speech_config.speech_synthesis_voice_name = voice

            # Set audio output
            if not output_file:
                tmp_dir = os.environ.get("TEMP", "/tmp")
                if not os.path.exists(tmp_dir):
                    os.makedirs(tmp_dir, exist_ok=True)
                output_file = os.path.join(tmp_dir, f"tts_{int(time.time() * 1000)}.wav")

            audio_config = speechsdk.audio.AudioOutputConfig(filename=output_file)
            synthesizer = speechsdk.SpeechSynthesizer(
                speech_config=speech_config,
                audio_config=audio_config,
            )

            # Build SSML if enabled
            if use_ssml:
                tts_input = self._build_ssml(text, language, add_pauses=humanize)
                logger.info(f"Synthesizing TTS ({voice}) with SSML: {text[:60]!r}…")
                result = synthesizer.speak_ssml_async(tts_input).get()
            else:
                logger.info(f"Synthesizing TTS ({voice}): {text[:60]!r}…")
                result = synthesizer.speak_text_async(text).get()

            if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
                with open(output_file, "rb") as f:
                    audio_b64 = base64.b64encode(f.read()).decode("utf-8")

                latency_ms = (time.perf_counter() - t0) * 1000
                logger.info(
                    f"✅ TTS complete ({voice}): {len(audio_b64)} chars  [{latency_ms:.0f}ms]"
                )
                return output_file, audio_b64, voice, latency_ms
            elif result.reason == speechsdk.ResultReason.Canceled:
                cancellation_details = speechsdk.CancellationDetails(result)
                logger.error(f"TTS canceled: {cancellation_details.reason} - {cancellation_details.error_details}")
                raise RuntimeError(f"TTS synthesis failed: {result.reason} - {cancellation_details.error_details}")
            else:
                raise RuntimeError(f"TTS synthesis failed: {result.reason}")

        except Exception as exc:
            logger.error(f"TTS error: {exc}")
            raise
