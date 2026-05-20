"""SF2/SFZ voice provider using FluidSynth.

Supports SoundFont (.sf2) and SFZ (.sfz) sample libraries.
Requires FluidSynth C library installed on the system.
"""

import logging
import os
import sys
from pathlib import Path
from typing import Optional

import numpy as np

from .base import VoiceProvider

logger = logging.getLogger(__name__)

# Try to find FluidSynth DLL in project directory
_PROJECT_ROOT = Path(__file__).parent.parent.parent
_FLUIDSYNTH_BIN = _PROJECT_ROOT / "fluidsynth_lib" / "bin"
if _FLUIDSYNTH_BIN.exists() and sys.platform == "win32":
    try:
        os.add_dll_directory(str(_FLUIDSYNTH_BIN))
    except Exception:
        pass

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

        # Initialize FluidSynth (API v1.3.x: keyword args directly)
        self._synth = fluidsynth.Synth(
            gain=gain,
            samplerate=sample_rate,
            channels=polyphony,
        )

        # Load the SoundFont
        ext = soundfont_path.suffix.lower()
        if ext in (".sf2", ".sfz"):
            self._sfid = self._synth.sfload(str(soundfont_path))
            if self._sfid == -1:
                raise RuntimeError(f"Failed to load SoundFont: {soundfont_path}")
            logger.info("Loaded %s: %s (id=%d)", ext.upper(), soundfont_path.name, self._sfid)
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
        """Render a note using FluidSynth."""
        release_time = 0.3
        total_duration = duration + release_time
        num_samples = int(total_duration * self.sample_rate)

        # Note on
        self._synth.noteon(0, note, velocity)

        # Render in chunks
        chunk_size = 1024
        buffer_l = []
        remaining = num_samples

        while remaining > 0:
            n = min(chunk_size, remaining)
            stereo = self._synth.get_samples(n)  # Returns stereo interleaved
            mono = (stereo[0::2] + stereo[1::2]) / 2.0  # Mix to mono
            buffer_l.append(mono)
            remaining -= n

        buffer = np.concatenate(buffer_l).astype(np.float32)

        # Note off
        self._synth.noteoff(0, note)

        # Render release tail
        release_samples = int(release_time * self.sample_rate)
        release_stereo = self._synth.get_samples(release_samples)
        release_mono = (release_stereo[0::2] + release_stereo[1::2]) / 2.0

        # Combine
        body_samples = int(duration * self.sample_rate)
        result = np.concatenate([buffer[:body_samples], release_mono])

        # Normalize
        peak = np.max(np.abs(result))
        if peak > 1.0:
            result /= peak
        if peak < 1e-6:
            result = np.zeros(1, dtype=np.float32)

        return result.astype(np.float32)

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
