"""Abstract base class for all voice (sound source) providers."""

from abc import ABC, abstractmethod
from typing import Optional

import numpy as np


class VoiceProvider(ABC):
    """A sound source that can render a single note into an audio buffer.

    Subclasses implement different sound generation methods:
    - SF2Provider: SoundFont files via FluidSynth
    - SynthProvider: Pure waveform synthesis
    - UserSampleProvider: User-provided WAV samples with manual note mapping
    """

    def __init__(self, sample_rate: int = 44100, name: str = ""):
        self.sample_rate = sample_rate
        self.name = name or self.__class__.__name__

    @abstractmethod
    def render(
        self,
        note: int,
        velocity: int,
        duration: float,
    ) -> np.ndarray:
        """Render a single note into a mono audio buffer.

        Args:
            note: MIDI note number (0–127, middle C = 60).
            velocity: How hard the note is struck (0–127).
            duration: Note duration in seconds.

        Returns:
            1D numpy array of float32 samples in range [-1, 1].
            May be longer than duration to allow for release tail.
        """
        ...

    @abstractmethod
    def reset(self) -> None:
        """Reset any internal state (e.g., FluidSynth instance)."""
        ...

    def render_poly(
        self,
        notes: list[tuple[int, int]],  # [(note, velocity), ...]
        duration: float,
    ) -> np.ndarray:
        """Render multiple notes simultaneously (chord).

        Default implementation renders each note and mixes them.
        Providers can override for better polyphonic rendering.
        """
        if not notes:
            return np.zeros(int(duration * self.sample_rate), dtype=np.float32)

        buffers = []
        for note, velocity in notes:
            buf = self.render(note, velocity, duration)
            buffers.append(buf)

        # Pad all to same length and mix
        max_len = max(len(b) for b in buffers)
        mixed = np.zeros(max_len, dtype=np.float32)
        for buf in buffers:
            padded = np.zeros(max_len, dtype=np.float32)
            padded[: len(buf)] = buf
            mixed += padded

        # Normalize to avoid clipping
        peak = np.max(np.abs(mixed))
        if peak > 1.0:
            mixed /= peak

        return mixed

    @staticmethod
    def midi_to_freq(note: int) -> float:
        """Convert MIDI note number to frequency (Hz).

        A4 = 440 Hz = MIDI note 69.
        """
        return 440.0 * (2.0 ** ((note - 69) / 12.0))
