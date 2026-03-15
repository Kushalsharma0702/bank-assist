"""
WebSocket router for real-time interruption detection and streaming.

Allows frontend to:
1. Send raw audio from microphone while TTS is playing
2. Detect speech activity (VAD) in real-time
3. Interrupt TTS and start new conversation immediately
"""

import logging
import json
import asyncio
from typing import Optional, Set
import numpy as np
import librosa

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from services.audio_preprocessing import AudioPreprocessor

logger = logging.getLogger("WSRouter")

router = APIRouter()
preprocessor = AudioPreprocessor(sample_rate=16000)


class InterruptionManager:
    """Manages real-time interruption detection and TTS pause/stop commands."""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self.is_tts_playing = False
        self.vad_threshold = 0.05  # Voice activity threshold
        self.silence_frames = 0
        self.max_silence_frames = 8  # ~160ms of silence at 16kHz

    async def connect(self, websocket: WebSocket):
        """Register new WebSocket connection."""
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"✅ Client connected ({len(self.active_connections)} active)")
        await websocket.send_json({"type": "connection_ok", "status": "ready"})

    async def disconnect(self, websocket: WebSocket):
        """Unregister WebSocket connection."""
        self.active_connections.discard(websocket)
        logger.info(f"Client disconnected ({len(self.active_connections)} active)")

    async def process_audio_chunk(self, audio_bytes: bytes) -> dict:
        """
        Process incoming audio chunk for voice activity detection.

        Returns:
            {
                "type": "vad_result",
                "has_speech": bool,
                "confidence": float (0-1),
                "should_interrupt": bool,
                "action": "continue" | "pause" | "stop"
            }
        """
        try:
            # Convert bytes to float32 PCM @ 16kHz
            audio_int16 = np.frombuffer(audio_bytes, dtype=np.int16)
            audio_float = audio_int16.astype(np.float32) / 32768.0

            # Quick VAD using energy and spectral features
            has_speech, confidence = self._detect_vad(audio_float)

            # Determine action based on VAD and TTS state
            action = "continue"
            should_interrupt = False

            if has_speech:
                self.silence_frames = 0
                should_interrupt = self.is_tts_playing

                if self.is_tts_playing:
                    action = "interrupt"
                    logger.debug(f"🛑 Speech detected during TTS playback — interrupting")

            else:
                self.silence_frames += 1
                if self.is_tts_playing and self.silence_frames > self.max_silence_frames:
                    action = "resume"
                    logger.debug(f"🔊 Resuming TTS after user silence")

            return {
                "type": "vad_result",
                "has_speech": has_speech,
                "confidence": float(confidence),
                "should_interrupt": should_interrupt,
                "action": action,
            }

        except Exception as e:
            logger.error(f"VAD processing error: {e}")
            return {
                "type": "vad_error",
                "error": str(e),
                "action": "continue",
            }

    def _detect_vad(self, audio: np.ndarray) -> tuple:
        """
        Quick voice activity detection using energy and spectral features.

        Returns:
            (has_speech: bool, confidence: float)
        """
        try:
            # Energy-based detection
            energy = np.sqrt(np.mean(audio ** 2))
            energy_threshold = self.vad_threshold

            if energy < energy_threshold:
                return False, 0.0

            # Spectral centroid (voice typically 100-5000 Hz)
            try:
                D = librosa.stft(audio, n_fft=256, hop_length=64)
                S = np.abs(D)
                freqs = np.fft.fftfreq(256, 1 / 16000)[:129]
                centroid = np.sum(freqs[:, np.newaxis] * S) / (np.sum(S) + 1e-10)
                spectral_valid = (centroid > 80) and (centroid < 8000)
            except Exception:
                spectral_valid = True  # Fallback

            # ZCR (Zero Crossing Rate) - voice has low ZCR
            zcr = np.sum(np.abs(np.diff(np.sign(audio)))) / (2 * len(audio))
            zcr_valid = zcr < 0.1  # Voice typically < 10% ZCR

            # Combine features
            has_speech = energy > energy_threshold and spectral_valid and zcr_valid
            confidence = min(energy / (self.vad_threshold * 3), 1.0)

            return has_speech, confidence

        except Exception as e:
            logger.debug(f"VAD feature extraction failed: {e}")
            return energy > energy_threshold, min(energy / (self.vad_threshold * 3), 1.0)

    async def broadcast_interruption(self):
        """Notify all clients that TTS should be interrupted."""
        message = {"type": "interrupt_command", "action": "stop_tts"}
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.warning(f"Failed to broadcast interruption: {e}")


# Global interruption manager
interrupt_manager = InterruptionManager()


@router.websocket("/ws/interruption")
async def websocket_interruption(websocket: WebSocket):
    """
    WebSocket endpoint for real-time speech interruption detection.

    Expected message format from client:
    {
        "type": "audio_chunk",
        "data": "<base64-encoded PCM audio>",
        "sample_rate": 16000
    }

    Or control messages:
    {
        "type": "tts_started",
        "duration_ms": 5000
    }
    {
        "type": "tts_ended"
    }
    """
    await interrupt_manager.connect(websocket)

    try:
        while True:
            msg = await websocket.receive_json()
            msg_type = msg.get("type", "")

            if msg_type == "audio_chunk":
                await _handle_audio_chunk(websocket, msg)

            elif msg_type == "tts_started":
                interrupt_manager.is_tts_playing = True
                logger.info(f"▶️ TTS started (duration: {msg.get('duration_ms')}ms)")

            elif msg_type == "tts_ended":
                interrupt_manager.is_tts_playing = False
                interrupt_manager.silence_frames = 0
                logger.info("⏹️ TTS ended")

            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        await interrupt_manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await interrupt_manager.disconnect(websocket)


async def _handle_audio_chunk(websocket: WebSocket, msg: dict):
    """Process incoming audio chunk."""
    try:
        import base64

        audio_chunk = msg.get("data", "")
        if not audio_chunk:
            return

        # Decode base64 audio
        audio_bytes = base64.b64decode(audio_chunk)

        # Process for VAD
        vad_result = await interrupt_manager.process_audio_chunk(audio_bytes)

        # Send VAD result back to client
        await websocket.send_json(vad_result)

        # Broadcast interruption if needed
        if vad_result.get("should_interrupt"):
            await interrupt_manager.broadcast_interruption()

    except Exception as e:
        logger.error(f"Audio chunk handling error: {e}")
        await websocket.send_json({"type": "error", "error": str(e)})
