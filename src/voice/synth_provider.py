"""Synthesizer voice provider — pure waveform synthesis with ADSR envelope.

No external samples required. Generates sound from basic waveforms:
sine, square, sawtooth, triangle, and noise.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import numpy as np

from .base import VoiceProvider


class Waveform(str, Enum):
    SINE = "sine"
    SQUARE = "square"
    SAWTOOTH = "sawtooth"
    TRIANGLE = "triangle"
    NOISE = "noise"


@dataclass
class ADSR:
    """ADSR envelope parameters, all in seconds."""

    attack: float = 0.02   # Time to reach peak
    decay: float = 0.1     # Time to reach sustain level
    sustain: float = 0.7   # Sustain level (0–1, fraction of peak)
    release: float = 0.3   # Time to fade to zero after note off


class SynthProvider(VoiceProvider):
    """Pure waveform synthesis voice provider.

    Generates tones from basic oscillator shapes with ADSR amplitude
    envelope. Useful as a fallback or for electronic/synth sounds.
    """

    def __init__(
        self,
        waveform: Waveform = Waveform.SINE,
        adsr: Optional[ADSR] = None,
        sample_rate: int = 44100,
        name: str = "",
        detune: float = 0.0,    # Cents of detuning
        harmonics: int = 0,      # Number of harmonic overtones (0 = none)
    ):
        super().__init__(sample_rate=sample_rate, name=name or f"Synth-{waveform.value}")
        self.waveform = waveform
        self.adsr = adsr or ADSR()
        self.detune = detune
        self.harmonics = harmonics

    def _generate_waveform(self, freq: float, num_samples: int) -> np.ndarray:
        """Generate one cycle of the selected waveform at the given frequency."""
        t = np.arange(num_samples) / self.sample_rate
        phase = (2.0 * np.pi * freq * t) % (2.0 * np.pi)

        # Apply detune (1 cent = 1/100 semitone)
        if self.detune != 0.0:
            detune_factor = 2.0 ** (self.detune / 1200.0)
            phase = (2.0 * np.pi * freq * detune_factor * t) % (2.0 * np.pi)

        base = np.zeros(num_samples, dtype=np.float32)

        # Generate base waveform + harmonics
        for h in range(self.harmonics + 1):
            multiplier = h + 1
            amplitude = 1.0 / multiplier  # Harmonics decay in amplitude
            h_phase = (phase * multiplier) % (2.0 * np.pi)

            if self.waveform == Waveform.SINE:
                wave = np.sin(h_phase, dtype=np.float32)
            elif self.waveform == Waveform.SQUARE:
                wave = np.where(np.sin(h_phase) >= 0, 1.0, -1.0).astype(np.float32)
            elif self.waveform == Waveform.SAWTOOTH:
                wave = (2.0 * (h_phase / (2.0 * np.pi) % 1.0) - 1.0).astype(np.float32)
            elif self.waveform == Waveform.TRIANGLE:
                wave = (2.0 * np.abs(2.0 * (h_phase / (2.0 * np.pi) % 1.0) - 1.0) - 1.0).astype(np.float32)
            elif self.waveform == Waveform.NOISE:
                wave = (np.random.rand(num_samples).astype(np.float32) * 2.0 - 1.0)
                break  # Noise doesn't benefit from harmonics
            else:
                wave = np.sin(h_phase, dtype=np.float32)

            base += wave * amplitude

        # Normalize
        peak = np.max(np.abs(base))
        if peak > 1.0:
            base /= peak

        return base

    def _apply_envelope(self, waveform: np.ndarray, velocity: float) -> np.ndarray:
        """Apply ADSR envelope to the waveform."""
        num_samples = len(waveform)
        sr = self.sample_rate

        envelope = np.ones(num_samples, dtype=np.float32)

        # Attack
        attack_samples = int(self.adsr.attack * sr)
        if attack_samples > 0 and attack_samples <= num_samples:
            envelope[:attack_samples] = np.linspace(0, 1, attack_samples, dtype=np.float32)

        # Decay
        decay_samples = int(self.adsr.decay * sr)
        decay_start = attack_samples
        decay_end = min(decay_start + decay_samples, num_samples)
        if decay_end > decay_start:
            envelope[decay_start:decay_end] = np.linspace(
                1, self.adsr.sustain, decay_end - decay_start, dtype=np.float32
            )

        # Sustain (already 1 in envelope, just scale it)
        if attack_samples + decay_samples < num_samples:
            sus_start = attack_samples + decay_samples
            envelope[sus_start:] = self.adsr.sustain

        # Release
        release_samples = int(self.adsr.release * sr)
        if release_samples > 0:
            release_start = max(0, num_samples - release_samples)
            envelope[release_start:] = np.linspace(
                envelope[release_start],
                0,
                num_samples - release_start,
                dtype=np.float32,
            )

        # Scale by velocity (0–127 → 0–1)
        vel_scale = velocity / 127.0
        return waveform * envelope * vel_scale

    def render(
        self,
        note: int,
        velocity: int,
        duration: float,
    ) -> np.ndarray:
        """Render a note using waveform synthesis with ADSR envelope."""
        freq = self.midi_to_freq(note)

        # Generate waveform for duration + release tail
        total_duration = duration + self.adsr.release
        num_samples = int(total_duration * self.sample_rate)

        if num_samples == 0:
            return np.zeros(0, dtype=np.float32)

        waveform = self._generate_waveform(freq, num_samples)
        result = self._apply_envelope(waveform, velocity)

        return result.astype(np.float32)

    def reset(self) -> None:
        """No state to reset for pure synth."""
        pass
