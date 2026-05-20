"""SF2/SFZ voice provider using FluidSynth.

Supports SoundFont (.sf2) and SFZ (.sfz) sample libraries.
Requires FluidSynth C library installed on the system.
"""

import logging
from pathlib import Path
from typing import Optional

import numpy as np

from .base import VoiceProvider

logger = logging.getLogger(__name__)

# Try to import pyfluidsynth — it may not be installed
try:
    import fluidsynth

    FLUIDSYNTH_AVAILABLE = True
except (ImportError, OSError):
    FLUIDSYNTH_AVAILABLE = False
    logger.warning("pyfluidsynth not available. SF2/SFZ support disabled.")


class SF2Provider(VoiceProvider):
    """SoundFont-based voice provider using FluidSynth.

    Loads .sf2 or .sfz files and renders notes through FluidSynth's
    high-quality sample-based synthesis engine.
    """

    def __init__(
        self,
        soundfont_path: str | Path,
        sample_rate: int = 44100,
        name: str = "",
        gain: float = 0.6,
        polyphony: int = 64,
    ):
        if not FLUIDSYNTH_AVAILABLE:
            raise RuntimeError(
                "pyfluidsynth is required for SF2/SFZ support. "
                "Install FluidSynth on your system and then: "
                "pip install pyfluidsynth"
            )

        soundfont_path = Path(soundfont_path)
        if not soundfont_path.exists():
            raise FileNotFoundError(f"SoundFont file not found: {soundfont_path}")

        super().__init__(sample_rate=sample_rate, name=name or soundfont_path.stem)
        self.soundfont_path = soundfont_path

        # Initialize FluidSynth
        self._settings = fluidsynth.Settings()
        self._settings["synth.sample-rate"] = sample_rate
        self._settings["synth.gain"] = gain
        self._settings["synth.polyphony"] = polyphony

        self._synth = fluidsynth.Synth(self._settings)
        self._synth.start()

        # Load the SoundFont
        ext = soundfont_path.suffix.lower()
        if ext == ".sf2":
            self._sfid = self._synth.sfload(str(soundfont_path))
            if self._sfid == -1:
                raise RuntimeError(f"Failed to load SoundFont: {soundfont_path}")
            logger.info("Loaded SF2: %s (id=%d)", soundfont_path.name, self._sfid)
        elif ext == ".sfz":
            # FluidSynth 2.x supports SFZ natively
            self._sfid = self._synth.sfload(str(soundfont_path))
            if self._sfid == -1:
                raise RuntimeError(f"Failed to load SFZ: {soundfont_path}")
            logger.info("Loaded SFZ: %s (id=%d)", soundfont_path.name, self._sfid)
        else:
            raise ValueError(f"Unsupported format: {ext}. Use .sf2 or .sfz")

        # Select the soundfont on channel 0
        self._synth.program_select(0, self._sfid, 0, 0)

    def render(
        self,
        note: int,
        velocity: int,
        duration: float,
    ) -> np.ndarray:
        """Render a note using FluidSynth.

        FluidSynth needs samples generated in real-time batches,
        so we run it for the duration of the note.
        """
        # Note on
        self._synth.noteon(0, note, velocity)

        # Calculate buffer size
        release_time = 0.3  # Extra time for release tail
        total_duration = duration + release_time
        num_samples = int(total_duration * self.sample_rate)

        # Render in chunks to avoid large memory allocation
        chunk_size = 1024
        buffer = np.zeros(num_samples, dtype=np.float32)

        for offset in range(0, num_samples, chunk_size):
            remaining = min(chunk_size, num_samples - offset)
            chunk = np.zeros(remaining * 2, dtype=np.float32)  # Stereo
            self._synth.write_samples(remaining, chunk)
            # Mix stereo to mono
            mono = (chunk[0::2] + chunk[1::2]) / 2.0
            buffer[offset : offset + remaining] = mono

        # Note off after duration
        # We need to send note off at the right time — this is approximate
        # A more accurate approach would interleave rendering and note-off
        self._synth.noteoff(0, note)
        # Render release tail
        release_samples = int(release_time * self.sample_rate)
        release_buffer = np.zeros(release_samples * 2, dtype=np.float32)
        self._synth.write_samples(release_samples, release_buffer)
        release_mono = (release_buffer[0::2] + release_buffer[1::2]) / 2.0

        # Append release tail
        tail_start = int(duration * self.sample_rate)
        buffer = np.concatenate([buffer[:tail_start], release_mono])

        # Normalize
        peak = np.max(np.abs(buffer))
        if peak > 1.0:
            buffer /= peak
        if peak < 1e-6:
            buffer = np.zeros_like(buffer)

        return buffer.astype(np.float32)

    def reset(self) -> None:
        """Reset FluidSynth — send all notes off."""
        if hasattr(self, "_synth"):
            self._synth.system_reset()
            self._synth.program_select(0, self._sfid, 0, 0)

    def __del__(self):
        """Clean up FluidSynth resources."""
        try:
            self._synth.delete()
        except Exception:
            pass
