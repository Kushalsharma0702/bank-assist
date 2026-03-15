"""
Advanced audio preprocessing — noise reduction, VAD, spectral filtering.
Ensures STT receives clean, zero-background-noise audio.
"""

import logging
import numpy as np
from scipy import signal
import librosa

logger = logging.getLogger("AudioPreprocessing")


class AudioPreprocessor:
    """High-quality audio preprocessing for STT."""

    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self.frame_length = int(0.025 * sample_rate)  # 25ms frames
        self.hop_length = int(0.010 * sample_rate)    # 10ms hop
        self.noise_profile = None

    def preprocess_audio(
        self,
        audio_data: np.ndarray,
        reduce_noise: bool = True,
        apply_vad: bool = True,
        normalize: bool = True,
    ) -> np.ndarray:
        """
        Full preprocessing pipeline:
        1. Normalize amplitude
        2. Spectral noise reduction (Wiener filter + spectral subtraction)
        3. Voice Activity Detection (VAD) to remove silence
        4. Auto-gain control

        Args:
            audio_data: Float32 or Int16 audio array (mono)
            reduce_noise: Apply spectral noise reduction
            apply_vad: Apply VAD to remove silence
            normalize: Normalize audio level

        Returns:
            Preprocessed audio (float32, range -1 to 1)
        """
        try:
            # Convert to float32 if needed
            if audio_data.dtype == np.int16:
                audio = audio_data.astype(np.float32) / 32768.0
            else:
                audio = audio_data.astype(np.float32)

            # 1. Normalize
            if normalize:
                audio = self._normalize_audio(audio)

            # 2. Pre-emphasis (boost high frequencies for voice clarity)
            audio = self._apply_preemphasis(audio)

            # 3. Spectral noise reduction
            if reduce_noise:
                audio = self._spectral_noise_reduction(audio)

            # 4. Voice Activity Detection (remove silence)
            if apply_vad:
                audio = self._apply_vad(audio)

            # 5. De-emphasis (inverse of pre-emphasis)
            audio = self._apply_deemphasis(audio)

            # 6. Auto-gain control
            audio = self._apply_agc(audio)

            logger.debug(
                f"✅ Preprocessed audio: {len(audio)} samples, "
                f"peak={np.max(np.abs(audio)):.3f}"
            )
            return np.clip(audio, -1.0, 1.0)

        except Exception as e:
            logger.warning(f"Preprocessing failed: {e}, returning original audio")
            return audio_data.astype(np.float32) / 32768.0 if audio_data.dtype == np.int16 else audio_data

    def _normalize_audio(self, audio: np.ndarray) -> np.ndarray:
        """Peak normalization to -3dB."""
        peak = np.max(np.abs(audio))
        if peak == 0:
            return audio
        target_peak = 0.7  # -3dB
        return audio * (target_peak / peak)

    def _apply_preemphasis(self, audio: np.ndarray, coeff: float = 0.97) -> np.ndarray:
        """Boost high frequencies to enhance consonants."""
        return np.append(audio[0], audio[1:] - coeff * audio[:-1])

    def _apply_deemphasis(self, audio: np.ndarray, coeff: float = 0.97) -> np.ndarray:
        """Inverse pre-emphasis filter."""
        restored = np.zeros_like(audio)
        restored[0] = audio[0]
        for i in range(1, len(audio)):
            restored[i] = audio[i] + coeff * restored[i - 1]
        return restored

    def _spectral_noise_reduction(self, audio: np.ndarray) -> np.ndarray:
        """
        Spectral subtraction + Wiener filtering.
        Reduces background noise while preserving speech.
        """
        try:
            # Compute STFT
            D = librosa.stft(audio, n_fft=512, hop_length=self.hop_length)
            S = np.abs(D)
            phase = np.angle(D)

            # Estimate noise from quiet frames (first 0.5s)
            n_noise_frames = int(0.5 * self.sample_rate / self.hop_length)
            noise_power = np.mean(S[:, :n_noise_frames] ** 2, axis=1, keepdims=True)

            # Spectral subtraction (reduce noise floor)
            alpha = 2.0  # oversubtraction factor
            S_reduced = np.maximum(S - alpha * np.sqrt(noise_power), 0.1 * S)

            # Wiener filter
            speech_power = np.maximum(S_reduced ** 2, noise_power)
            wiener_filter = speech_power / (speech_power + noise_power)
            S_filtered = S_reduced * wiener_filter

            # Reconstruct
            D_filtered = S_filtered * np.exp(1j * phase)
            audio_filtered = librosa.istft(D_filtered, hop_length=self.hop_length)

            return audio_filtered[:len(audio)]

        except Exception as e:
            logger.debug(f"Spectral noise reduction failed: {e}")
            return audio

    def _apply_vad(self, audio: np.ndarray, threshold: float = 0.02) -> np.ndarray:
        """
        Voice Activity Detection (simple energy-based + spectral centroid).
        Removes silence and low-energy segments.
        """
        try:
            # Frame-based energy
            frames = librosa.util.frame(audio, frame_length=self.frame_length, hop_length=self.hop_length)
            energy = np.sqrt(np.sum(frames ** 2, axis=0))
            energy_threshold = threshold * np.max(energy)

            # Spectral centroid (voice typically 100-5000 Hz)
            D = librosa.stft(audio, n_fft=512, hop_length=self.hop_length)
            S = np.abs(D)
            freq_bins = np.fft.fftfreq(512, 1 / self.sample_rate)[:257]
            centroid = np.sum(freq_bins[:, np.newaxis] * S, axis=0) / (np.sum(S, axis=0) + 1e-10)
            centroid_valid = (centroid > 80) & (centroid < 8000)

            # Combine conditions: high energy + valid spectral centroid
            vad_mask = (energy > energy_threshold) & centroid_valid

            # Smooth VAD decisions (median filter)
            vad_smooth = signal.medfilt(vad_mask.astype(float), kernel_size=5) > 0.5

            # Map back to samples and apply gate
            vad_gate = np.repeat(vad_smooth, self.hop_length)[:len(audio)]
            audio_vadded = audio * vad_gate

            # Remove leading/trailing silence
            vad_indices = np.where(vad_gate > 0)[0]
            if len(vad_indices) > 0:
                start, end = vad_indices[0], vad_indices[-1] + 1
                audio_vadded = audio[start:end]

            return audio_vadded

        except Exception as e:
            logger.debug(f"VAD failed: {e}")
            return audio

    def _apply_agc(self, audio: np.ndarray, target_db: float = -20.0) -> np.ndarray:
        """
        Automatic Gain Control.
        Maintains consistent loudness across frames.
        """
        try:
            frames = librosa.util.frame(audio, frame_length=self.frame_length, hop_length=self.hop_length)
            rms_values = np.sqrt(np.mean(frames ** 2, axis=0))
            rms_db = 20 * np.log10(np.maximum(rms_values, 1e-10))

            # Calculate gain to achieve target
            gain_db = target_db - rms_db
            gain_linear = 10 ** (np.clip(gain_db, -12, 12) / 20)

            # Smooth gain to avoid artifacts
            gain_smooth = signal.medfilt(gain_linear, kernel_size=3)
            gain_expanded = np.repeat(gain_smooth, self.hop_length)[:len(audio)]

            return audio * gain_expanded

        except Exception as e:
            logger.debug(f"AGC failed: {e}")
            return audio
