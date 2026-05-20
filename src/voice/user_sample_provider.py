"""User sample voice provider — user-provided WAV files with manual mapping.

Users can record or provide audio samples of individual notes,
then map them to MIDI note ranges and velocity layers.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

from .base import VoiceProvider

logger = logging.getLogger(__name__)


@dataclass
class SampleMap:
    """Maps a single audio sample to a note and velocity range."""

    file_path: Path
    root_note: int          # The actual MIDI note of this sample (for pitch shifting)
    note_lo: int            # Lowest MIDI note this sample covers
    note_hi: int            # Highest MIDI note this sample covers
    vel_lo: int = 0         # Lowest velocity this sample covers
    vel_hi: int = 127       # Highest velocity this sample covers
    loop_start: int = 0     # Sample index for loop start (0 = no loop)
    loop_end: int = 0       # Sample index for loop end

    # Cached audio data (populated at load time)
    _data: Optional[np.ndarray] = field(default=None, repr=False)


class UserSampleProvider(VoiceProvider):
    """Voice provider using user-supplied WAV samples with manual note mapping.

    Users configure which WAV file plays for which note range and velocity
    layer. Multiple samples can be layered (e.g., pp, mf, ff for the same note).
    """

    def __init__(
        self,
        sample_rate: int = 44100,
        name: str = "User Samples",
    ):
        super().__init__(sample_rate=sample_rate, name=name)
        self._sample_maps: list[SampleMap] = []
        self._loaded = False

    def add_sample(
        self,
        file_path: str | Path,
        root_note: int,
        note_lo: int,
        note_hi: int,
        vel_lo: int = 0,
        vel_hi: int = 127,
        loop_start: int = 0,
        loop_end: int = 0,
    ) -> None:
        """Add a sample mapping.

        Args:
            file_path: Path to WAV file.
            root_note: The actual MIDI note this sample was recorded at.
            note_lo: Lowest note this sample should play for.
            note_hi: Highest note this sample should play for.
            vel_lo: Lowest velocity trigger.
            vel_hi: Highest velocity trigger.
            loop_start: Sample index where sustain loop begins (0 = no loop).
            loop_end: Sample index where sustain loop ends.
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Sample file not found: {file_path}")

        sm = SampleMap(
            file_path=file_path,
            root_note=root_note,
            note_lo=note_lo,
            note_hi=note_hi,
            vel_lo=vel_lo,
            vel_hi=vel_hi,
            loop_start=loop_start,
            loop_end=loop_end,
        )
        self._sample_maps.append(sm)
        self._loaded = False
        logger.info("Added sample: %s (notes %d-%d)", file_path.name, note_lo, note_hi)

    def load_samples(self) -> None:
        """Load all sample WAV files into memory."""
        for sm in self._sample_maps:
            if sm._data is None:
                data, sr = sf.read(str(sm.file_path), dtype="float32")
                if sr != self.sample_rate:
                    # Resample
                    from scipy import signal as scipy_signal

                    ratio = self.sample_rate / sr
                    data = scipy_signal.resample(data, int(len(data) * ratio))
                # Convert to mono if stereo
                if data.ndim > 1:
                    data = np.mean(data, axis=1)
                sm._data = data.astype(np.float32)
        self._loaded = True
        logger.info("Loaded %d samples", len(self._sample_maps))

    def _find_sample(self, note: int, velocity: int) -> Optional[SampleMap]:
        """Find the best matching sample for a given note and velocity."""
        best: Optional[SampleMap] = None
        best_score = -1

        for sm in self._sample_maps:
            if sm.note_lo <= note <= sm.note_hi and sm.vel_lo <= velocity <= sm.vel_hi:
                # Prefer samples with root_note closest to the requested note
                note_dist = abs(sm.root_note - note)
                score = 1000 - note_dist  # Higher is better
                if score > best_score:
                    best_score = score
                    best = sm

        return best

    @staticmethod
    def _pitch_shift(data: np.ndarray, semitones: float, sr: int) -> np.ndarray:
        """Pitch shift by resampling (changes duration proportionally).

        Uses FFT-based resampling for high quality.
        Positive semitones = pitch up (shorter), negative = pitch down (longer).
        """
        if semitones == 0:
            return data.copy()

        from scipy.signal import resample

        ratio = 2.0 ** (-semitones / 12.0)
        new_len = max(1, int(len(data) * ratio))

        # Edge-preserving window to reduce FFT boundary artifacts
        window_len = min(len(data) // 8, 1024)
        if window_len > 1:
            fade = np.hanning(window_len * 2)
            data = data.copy()
            data[:window_len] *= fade[:window_len]
            data[-window_len:] *= fade[window_len:]

        result = resample(data, new_len)
        return result.astype(np.float32)

    def render(
        self,
        note: int,
        velocity: int,
        duration: float,
    ) -> np.ndarray:
        """Render a note from user samples with pitch shifting."""
        if not self._loaded:
            self.load_samples()

        sm = self._find_sample(note, velocity)
        if sm is None or sm._data is None:
            # No matching sample — return silence with a tiny click for debugging
            logger.debug("No sample for note=%d vel=%d", note, velocity)
            return np.zeros(int(0.01 * self.sample_rate), dtype=np.float32)

        # Pitch shift from root note to requested note
        semitones = note - sm.root_note
        audio = self._pitch_shift(sm._data, semitones, self.sample_rate)

        # Handle duration
        needed_samples = int(duration * self.sample_rate)
        needs_loop = sm.loop_end > sm.loop_start > 0

        if needs_loop and needed_samples > len(audio):
            # Loop-based sustain
            result = np.zeros(needed_samples, dtype=np.float32)
            attack_part = audio[: sm.loop_end]
            loop_part = audio[sm.loop_start : sm.loop_end]

            # Attack
            copy_len = min(len(attack_part), needed_samples)
            result[:copy_len] = attack_part[:copy_len]

            # Loop
            pos = len(attack_part)
            while pos < needed_samples:
                remaining = needed_samples - pos
                chunk = min(len(loop_part), remaining)
                result[pos : pos + chunk] = loop_part[:chunk]
                pos += chunk

            # Apply release envelope at end
            release_samples = int(0.05 * self.sample_rate)
            if release_samples > 0 and release_samples < needed_samples:
                release_env = np.linspace(1, 0, release_samples, dtype=np.float32)
                result[-release_samples:] *= release_env

            return result.astype(np.float32)
        else:
            # One-shot playback
            if needed_samples >= len(audio):
                result = np.zeros(needed_samples, dtype=np.float32)
                result[: len(audio)] = audio

                # Apply release envelope if note ends before sample ends
                release_samples = int(0.05 * self.sample_rate)
                if release_samples > 0 and release_samples < needed_samples:
                    release_env = np.linspace(1, 0, release_samples, dtype=np.float32)
                    result[-release_samples:] *= release_env
            else:
                # Sample is longer than needed — truncate with fade out
                result = audio[:needed_samples].copy()
                fade_len = int(0.02 * self.sample_rate)
                if fade_len > 0 and fade_len < needed_samples:
                    fade_env = np.linspace(1, 0, fade_len, dtype=np.float32)
                    result[-fade_len:] *= fade_env

        # Scale by velocity
        vel_scale = velocity / 127.0
        result *= vel_scale

        return result.astype(np.float32)

    def reset(self) -> None:
        """Clear loaded samples."""
        for sm in self._sample_maps:
            sm._data = None
        self._loaded = False

    def clear_mappings(self) -> None:
        """Remove all sample mappings."""
        self.reset()
        self._sample_maps.clear()

    @property
    def sample_count(self) -> int:
        return len(self._sample_maps)
