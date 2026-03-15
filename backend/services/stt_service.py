"""
Azure Speech-to-Text service with advanced preprocessing.
Includes noise reduction, VAD, and audio enhancement for accuracy.
"""

import logging
import time
from typing import Tuple
import numpy as np
import librosa

import azure.cognitiveservices.speech as speechsdk

from models.intent_models import LANGUAGE_CONFIG, SUPPORTED_LANGUAGES
from config import AZURE_SPEECH_KEY, AZURE_SPEECH_REGION
from exceptions import NoSpeechDetectedError
from services.audio_preprocessing import AudioPreprocessor

logger = logging.getLogger("STTService")
preprocessor = AudioPreprocessor(sample_rate=16000)


class SpeechToTextService:
    """Azure Speech SDK — STT with automatic language detection."""

    async def transcribe(
        self,
        audio_file_path: str,
        language: str = "km-KH",
        preprocess: bool = True,
    ) -> Tuple[str, str, float]:
        """
        Transcribe audio file with optional preprocessing.

        Args:
            audio_file_path: Path to audio WAV file (16 kHz mono expected)
            language: BCP-47 language code (e.g., "km-KH")
            preprocess: Apply noise reduction, VAD, AGC

        Returns:
            (transcript, detected_language_code, latency_ms)
        """
        t0 = time.perf_counter()
        try:
            # Load and preprocess audio
            preprocessed_path = audio_file_path
            if preprocess:
                logger.info("Preprocessing audio (noise reduction, VAD, AGC)…")
                try:
                    audio, sr = librosa.load(audio_file_path, sr=16000, mono=True)
                    audio_processed = preprocessor.preprocess_audio(
                        audio,
                        reduce_noise=True,
                        apply_vad=True,
                        normalize=True,
                    )
                    # Save preprocessed audio temporarily
                    preprocessed_path = audio_file_path.replace(".wav", "_processed.wav")
                    librosa.output.write_wav(preprocessed_path, audio_processed, sr=16000)
                    logger.debug(f"✅ Audio preprocessed, saved to {preprocessed_path}")
                except Exception as prep_err:
                    logger.warning(f"Preprocessing failed: {prep_err}, using original")
                    preprocessed_path = audio_file_path

            speech_config = speechsdk.SpeechConfig(
                subscription=AZURE_SPEECH_KEY,
                region=AZURE_SPEECH_REGION,
            )
            
            # Enable confidence scores for better quality metrics
            speech_config.enable_audio_logging()

            lang_cfg = LANGUAGE_CONFIG.get(language, LANGUAGE_CONFIG["en-US"])
            candidates = lang_cfg["auto_detect_candidates"]

            auto_detect = speechsdk.languageconfig.AutoDetectSourceLanguageConfig(
                languages=candidates
            )
            audio_config = speechsdk.audio.AudioConfig(filename=preprocessed_path)
            recognizer = speechsdk.SpeechRecognizer(
                speech_config=speech_config,
                auto_detect_source_language_config=auto_detect,
                audio_config=audio_config,
            )

            logger.info(f"Transcribing (candidates: {candidates})…")
            result = recognizer.recognize_once()

            if result.reason == speechsdk.ResultReason.RecognizedSpeech:
                text = result.text
                detected = language
                try:
                    detected = (
                        speechsdk.AutoDetectSourceLanguageResult(result).language
                        or language
                    )
                except Exception:
                    pass
                if detected not in SUPPORTED_LANGUAGES:
                    detected = language
                latency_ms = (time.perf_counter() - t0) * 1000
                logger.info(f"✅ Transcribed ({detected}): {text!r}  [{latency_ms:.0f}ms]")
                return text, detected, latency_ms

            elif result.reason == speechsdk.ResultReason.NoMatch:
                raise NoSpeechDetectedError("No speech detected in audio")
            else:
                raise RuntimeError(f"Recognition failed: {result.reason}")

        except NoSpeechDetectedError:
            raise
        except Exception as exc:
            logger.error(f"STT error: {exc}")
            raise
        finally:
            # Clean up preprocessed file
            if preprocess and preprocessed_path != audio_file_path:
                try:
                    import os
                    os.unlink(preprocessed_path)
                except OSError:
                    pass
