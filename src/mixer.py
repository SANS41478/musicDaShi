"""Audio mixer — mixing, effects, and export utilities."""

import logging
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

logger = logging.getLogger(__name__)


class Mixer:
    """Audio mixing and export utilities.

    Handles normalization, basic effects, and WAV/MP3 export.
    """

    def __init__(self, sample_rate: int = 44100):
        self.sample_rate = sample_rate

    @staticmethod
    def normalize(audio: np.ndarray, target_peak: float = 0.95) -> np.ndarray:
        """Normalize audio to a target peak level.

        Args:
            audio: Input audio array.
            target_peak: Desired peak amplitude (0.0–1.0).

        Returns:
            Normalized audio array.
        """
        current_peak = np.max(np.abs(audio))
        if current_peak < 1e-8:
            return audio
        gain = target_peak / current_peak
        return (audio * gain).astype(np.float32)

    @staticmethod
    def apply_reverb(
        audio: np.ndarray,
        sample_rate: int,
        room_size: float = 0.5,
        damping: float = 0.5,
        wet_level: float = 0.3,
    ) -> np.ndarray:
        """Apply a simple Schroeder reverb effect.

        Args:
            audio: Input audio (mono or stereo).
            sample_rate: Sample rate in Hz.
            room_size: Room size (0.0–1.0).
            damping: High-frequency damping (0.0–1.0).
            wet_level: Wet/dry mix (0.0–1.0, higher = more reverb).

        Returns:
            Audio with reverb applied.
        """
        if wet_level <= 0.0:
            return audio

        was_mono = audio.ndim == 1
        if was_mono:
            audio = audio.reshape(-1, 1)
            audio = np.hstack([audio, audio])

        # Simple comb + allpass reverb
        # Convert room_size to delay lengths in samples
        comb_delays = [
            int(sample_rate * (0.03 + room_size * 0.02)),
            int(sample_rate * (0.037 + room_size * 0.02)),
            int(sample_rate * (0.041 + room_size * 0.02)),
            int(sample_rate * (0.045 + room_size * 0.02)),
        ]

        output = np.zeros_like(audio)
        comb_gain = 0.7 + room_size * 0.15

        for ch in range(audio.shape[1]):
            channel = audio[:, ch].copy()
            wet = np.zeros(len(channel), dtype=np.float64)

            # Comb filters
            for delay in comb_delays:
                comb_buf = np.zeros(delay, dtype=np.float64)
                for i in range(len(channel)):
                    idx = i % delay
                    out = comb_buf[idx]
                    comb_buf[idx] = channel[i] + comb_gain * out * (1.0 - damping)
                    wet[i] += out

            wet /= len(comb_delays)  # Normalize

            # Simple allpass
            ap_delay = int(sample_rate * 0.005)
            ap_buf = np.zeros(ap_delay, dtype=np.float64)
            ap_gain = 0.5
            for i in range(len(wet)):
                idx = i % ap_delay
                delayed = ap_buf[idx]
                ap_buf[idx] = wet[i] + ap_gain * delayed
                wet[i] = -ap_gain * wet[i] + delayed

            output[:, ch] = channel * (1.0 - wet_level) + wet * wet_level

        if was_mono:
            output = np.mean(output, axis=1)

        # Normalize
        peak = np.max(np.abs(output))
        if peak > 0.99:
            output /= peak * 1.01

        return output.astype(np.float32)

    @staticmethod
    def apply_fade_in(audio: np.ndarray, duration: float, sample_rate: int) -> np.ndarray:
        """Apply a linear fade-in."""
        fade_samples = int(duration * sample_rate)
        if fade_samples <= 0:
            return audio
        fade_samples = min(fade_samples, len(audio))
        fade = np.linspace(0, 1, fade_samples, dtype=np.float32)
        if audio.ndim == 2:
            audio[:fade_samples, 0] *= fade
            audio[:fade_samples, 1] *= fade
        else:
            audio[:fade_samples] *= fade
        return audio

    @staticmethod
    def apply_fade_out(audio: np.ndarray, duration: float, sample_rate: int) -> np.ndarray:
        """Apply a linear fade-out."""
        fade_samples = int(duration * sample_rate)
        if fade_samples <= 0:
            return audio
        fade_samples = min(fade_samples, len(audio))
        fade = np.linspace(1, 0, fade_samples, dtype=np.float32)
        if audio.ndim == 2:
            audio[-fade_samples:, 0] *= fade
            audio[-fade_samples:, 1] *= fade
        else:
            audio[-fade_samples:] *= fade
        return audio

    def export_wav(
        self,
        audio: np.ndarray,
        output_path: str | Path,
        normalize: bool = True,
        fade_in: float = 0.0,
        fade_out: float = 0.0,
    ) -> Path:
        """Export audio to a WAV file.

        Args:
            audio: Audio data (mono or stereo).
            output_path: Destination file path.
            normalize: Whether to normalize before export.
            fade_in: Fade-in duration in seconds.
            fade_out: Fade-out duration in seconds.

        Returns:
            Path to the exported file.
        """
        output = audio.copy()

        if fade_in > 0:
            output = self.apply_fade_in(output, fade_in, self.sample_rate)
        if fade_out > 0:
            output = self.apply_fade_out(output, fade_out, self.sample_rate)
        if normalize:
            output = self.normalize(output)

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        sf.write(str(output_path), output, self.sample_rate, subtype="PCM_16")
        logger.info("Exported WAV: %s (%.1fs)", output_path.name, len(output) / self.sample_rate)

        return output_path

    @staticmethod
    def get_duration(audio: np.ndarray, sample_rate: int) -> float:
        """Get audio duration in seconds."""
        return len(audio) / sample_rate
