"""Performance engine — renders MIDI events through voice providers into audio.

This is the core orchestrator: it takes parsed MIDI notes, sends them
through the configured voice providers, and assembles the full audio timeline.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np

from .midi_parser import MidiFileInfo, NoteEvent, parse_midi
from .voice.base import VoiceProvider

logger = logging.getLogger(__name__)


@dataclass
class TrackConfig:
    """Configuration for a single MIDI track's voice settings."""

    track_index: int
    voice: VoiceProvider
    volume: float = 1.0         # 0.0–1.0 track volume
    pan: float = 0.0            # -1.0 (left) to 1.0 (right)
    transpose: int = 0          # Semitones to transpose
    solo: bool = False
    mute: bool = False


@dataclass
class RenderResult:
    """Result of rendering a performance."""

    audio: np.ndarray          # Float32 array, shape (samples,) or (samples, channels)
    sample_rate: int
    duration: float
    render_time: float         # How long rendering took (seconds)
    note_count: int


class PerformanceEngine:
    """Renders MIDI files through voice providers into audio.

    Usage:
        engine = PerformanceEngine(sample_rate=44100)
        engine.set_voice_for_track(0, my_piano_provider)
        result = engine.render("song.mid")
        # result.audio is a numpy array ready for playback/export
    """

    def __init__(self, sample_rate: int = 44100):
        self.sample_rate = sample_rate
        self._track_configs: dict[int, TrackConfig] = {}
        self._default_voice: Optional[VoiceProvider] = None
        self._progress_callback: Optional[Callable[[float], None]] = None

    def set_default_voice(self, voice: VoiceProvider) -> None:
        """Set the fallback voice for tracks without explicit configuration."""
        self._default_voice = voice

    def set_voice_for_track(
        self,
        track_index: int,
        voice: VoiceProvider,
        volume: float = 1.0,
        pan: float = 0.0,
        transpose: int = 0,
    ) -> None:
        """Configure which voice to use for a specific MIDI track."""
        self._track_configs[track_index] = TrackConfig(
            track_index=track_index,
            voice=voice,
            volume=volume,
            pan=pan,
            transpose=transpose,
        )

    def set_progress_callback(self, callback: Callable[[float], None]) -> None:
        """Set a callback for render progress (0.0 to 1.0)."""
        self._progress_callback = callback

    def _get_voice_for_track(self, track_index: int) -> Optional[VoiceProvider]:
        """Get the voice provider for a track, or the default."""
        config = self._track_configs.get(track_index)
        if config and not config.mute:
            return config.voice
        return self._default_voice

    def _get_config_for_track(self, track_index: int) -> Optional[TrackConfig]:
        """Get the full track config, or a default config using the default voice."""
        if track_index in self._track_configs:
            return self._track_configs[track_index]
        if self._default_voice:
            return TrackConfig(track_index=track_index, voice=self._default_voice)
        return None

    def render_file(self, midi_path: str) -> RenderResult:
        """Parse and render a MIDI file.

        Args:
            midi_path: Path to a .mid file.

        Returns:
            RenderResult with the full audio buffer.
        """
        midi_info = parse_midi(midi_path)
        return self.render(midi_info)

    def render(self, midi_info: MidiFileInfo) -> RenderResult:
        """Render a pre-parsed MidiFileInfo into audio.

        Args:
            midi_info: Parsed MIDI data from midi_parser.parse_midi().

        Returns:
            RenderResult with the complete mixed audio.
        """
        t_start = time.time()

        # Reset all voices
        for config in self._track_configs.values():
            config.voice.reset()
        if self._default_voice:
            self._default_voice.reset()

        notes = midi_info.notes
        if not notes:
            logger.warning("No notes to render — producing silence")
            silence = np.zeros(self.sample_rate, dtype=np.float32)
            return RenderResult(
                audio=silence,
                sample_rate=self.sample_rate,
                duration=1.0,
                render_time=0.0,
                note_count=0,
            )

        # Calculate total buffer size
        total_duration = midi_info.duration + 1.0  # 1 second tail
        total_samples = int(total_duration * self.sample_rate)

        # Allocate stereo output buffer
        output = np.zeros((total_samples, 2), dtype=np.float64)

        rendered_count = 0
        skipped_count = 0

        for i, note in enumerate(notes):
            config = self._get_config_for_track(note.track)
            if config is None:
                skipped_count += 1
                continue

            if config.mute or config.solo is False:
                # Check if any track is soloed — if so, skip non-solo tracks
                any_solo = any(c.solo for c in self._track_configs.values())
                if any_solo and not config.solo:
                    skipped_count += 1
                    continue

            # Apply transpose
            play_note = note.note + config.transpose
            play_note = max(0, min(127, play_note))

            # Render the note
            try:
                audio = config.voice.render(play_note, note.velocity, note.duration)
            except Exception as e:
                logger.error("Error rendering note %d on track %d: %s", note.note, note.track, e)
                skipped_count += 1
                continue

            if len(audio) == 0:
                skipped_count += 1
                continue

            # Place audio at correct time position
            start_sample = int(note.start_time * self.sample_rate)
            end_sample = min(start_sample + len(audio), total_samples)

            if start_sample >= total_samples:
                continue

            actual_len = end_sample - start_sample
            if actual_len <= 0:
                continue

            # Apply volume
            audio_chunk = audio[:actual_len] * config.volume * (note.velocity / 127.0)

            # Apply pan (simple linear pan)
            left_gain = max(0.0, 1.0 - max(0.0, config.pan))
            right_gain = max(0.0, 1.0 + min(0.0, config.pan))

            output[start_sample:end_sample, 0] += audio_chunk * left_gain
            output[start_sample:end_sample, 1] += audio_chunk * right_gain

            rendered_count += 1

            # Progress callback
            if self._progress_callback and i % 50 == 0:
                self._progress_callback(i / len(notes))

        if self._progress_callback:
            self._progress_callback(1.0)

        # Normalize to prevent clipping
        peak = np.max(np.abs(output))
        if peak > 1.0:
            output /= peak
        if peak < 1e-8:
            output = np.zeros_like(output)

        # Trim trailing silence
        output = self._trim_silence(output)

        # Convert to float32 for output
        output = output.astype(np.float32)

        render_time = time.time() - t_start

        logger.info(
            "Rendered %d notes (%d skipped) in %.2fs — duration: %.1fs",
            rendered_count, skipped_count, render_time, total_duration,
        )

        return RenderResult(
            audio=output,
            sample_rate=self.sample_rate,
            duration=len(output) / self.sample_rate,
            render_time=render_time,
            note_count=rendered_count,
        )

    @staticmethod
    def _trim_silence(audio: np.ndarray, threshold: float = 0.001) -> np.ndarray:
        """Trim leading and trailing silence."""
        if audio.ndim == 2:
            envelope = np.max(np.abs(audio), axis=1)
        else:
            envelope = np.abs(audio)

        above = np.where(envelope > threshold)[0]
        if len(above) == 0:
            return audio[:1]  # Return minimal silence

        start = max(0, above[0] - 100)
        end = min(len(envelope), above[-1] + int(44100 * 0.5))  # 0.5s tail

        if audio.ndim == 2:
            return audio[start:end, :]
        return audio[start:end]
