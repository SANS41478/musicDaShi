"""MIDI file parser — converts .mid files into structured note event lists."""

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import mido


@dataclass
class NoteEvent:
    """A single note to be played, with absolute timing in seconds."""

    note: int          # MIDI note number (0–127, middle C = 60)
    velocity: int      # How hard the note is struck (0–127)
    start_time: float  # Absolute start time in seconds
    duration: float    # Note duration in seconds
    track: int         # Which MIDI track this note belongs to
    channel: int       # MIDI channel (0–15)

    @property
    def end_time(self) -> float:
        return self.start_time + self.duration


@dataclass
class TempoChange:
    """Records a tempo change at a specific time."""

    time: float        # Absolute time in seconds when this tempo takes effect
    tempo: int         # Microseconds per quarter note (standard = 500000 = 120 BPM)
    tick: int          # Absolute tick at which this change occurs


@dataclass
class TrackInfo:
    """Metadata about a MIDI track."""

    index: int
    name: str
    note_count: int
    channel: int
    instrument_name: str = ""


@dataclass
class MidiFileInfo:
    """Parsed MIDI file with all note events and metadata."""

    file_path: Path
    ticks_per_beat: int
    duration: float          # Total duration in seconds
    tracks: List[TrackInfo]
    notes: List[NoteEvent]
    tempo_changes: List[TempoChange]

    @property
    def note_count(self) -> int:
        return len(self.notes)

    @property
    def track_count(self) -> int:
        return len(self.tracks)


def _ticks_to_seconds(
    ticks: int,
    tempo_changes: List[TempoChange],
    ticks_per_beat: int,
) -> float:
    """Convert absolute ticks to seconds, accounting for tempo changes.

    Walks through tempo change points to accumulate time correctly.
    """
    if not tempo_changes:
        return 0.0

    seconds = 0.0
    prev_tick = 0
    prev_tempo = tempo_changes[0].tempo

    for tc in tempo_changes:
        if tc.tick >= ticks:
            break
        # Time from prev_tick to tc.tick at prev_tempo
        tick_delta = tc.tick - prev_tick
        seconds += (tick_delta / ticks_per_beat) * (prev_tempo / 1_000_000)
        prev_tick = tc.tick
        prev_tempo = tc.tempo

    # Remaining ticks at current tempo
    tick_delta = ticks - prev_tick
    seconds += (tick_delta / ticks_per_beat) * (prev_tempo / 1_000_000)

    return seconds


def _extract_tempo_changes(track: mido.MidiTrack, ticks_per_beat: int) -> List[TempoChange]:
    """Extract tempo change events from a track (usually track 0)."""
    changes: List[TempoChange] = []
    abs_tick = 0

    for msg in track:
        abs_tick += msg.time
        if msg.type == "set_tempo":
            t = _ticks_to_seconds(
                abs_tick,
                [TempoChange(time=0, tempo=500000, tick=0)],  # default 120 BPM
                ticks_per_beat,
            )
            changes.append(TempoChange(time=t, tempo=msg.tempo, tick=abs_tick))

    # Ensure there's always at least one tempo
    if not changes:
        changes.append(TempoChange(time=0, tempo=500000, tick=0))

    return changes


def parse_midi(file_path: str | Path) -> MidiFileInfo:
    """Parse a MIDI file and extract all note events with absolute timing.

    Args:
        file_path: Path to a .mid or .midi file.

    Returns:
        MidiFileInfo containing all parsed notes and metadata.
    """
    file_path = Path(file_path)
    mid = mido.MidiFile(str(file_path))

    ticks_per_beat = mid.ticks_per_beat

    # Step 1: Scan track 0 (conductor track) for tempo changes
    tempo_changes = _extract_tempo_changes(mid.tracks[0], ticks_per_beat)

    # Step 2: Parse all tracks for note events
    all_notes: List[NoteEvent] = []
    track_infos: List[TrackInfo] = []

    for track_idx, track in enumerate(mid.tracks):
        # Track state
        abs_tick = 0
        # Active notes: key = (channel, note), value = (start_tick, velocity)
        active_notes: dict[tuple[int, int], tuple[int, int]] = {}
        note_count = 0
        track_name = f"Track {track_idx}"
        channel = 0

        for msg in track:
            abs_tick += msg.time

            if msg.type == "track_name":
                track_name = msg.name
            elif msg.type == "program_change":
                channel = msg.channel

            elif msg.type == "note_on":
                if msg.velocity > 0:
                    # Note on
                    active_notes[(msg.channel, msg.note)] = (abs_tick, msg.velocity)
                else:
                    # Note on with velocity 0 = note off
                    key = (msg.channel, msg.note)
                    if key in active_notes:
                        start_tick, velocity = active_notes.pop(key)
                        start_time = _ticks_to_seconds(
                            start_tick, tempo_changes, ticks_per_beat
                        )
                        end_time = _ticks_to_seconds(
                            abs_tick, tempo_changes, ticks_per_beat
                        )
                        all_notes.append(
                            NoteEvent(
                                note=msg.note,
                                velocity=velocity,
                                start_time=start_time,
                                duration=end_time - start_time,
                                track=track_idx,
                                channel=msg.channel,
                            )
                        )
                        note_count += 1

            elif msg.type == "note_off":
                key = (msg.channel, msg.note)
                if key in active_notes:
                    start_tick, velocity = active_notes.pop(key)
                    start_time = _ticks_to_seconds(
                        start_tick, tempo_changes, ticks_per_beat
                    )
                    end_time = _ticks_to_seconds(
                        abs_tick, tempo_changes, ticks_per_beat
                    )
                    all_notes.append(
                        NoteEvent(
                            note=msg.note,
                            velocity=velocity,
                            start_time=start_time,
                            duration=end_time - start_time,
                            track=track_idx,
                            channel=msg.channel,
                        )
                    )
                    note_count += 1

        # Close any notes still held at track end
        final_tick = abs_tick
        for (ch, note_num), (start_tick, velocity) in active_notes.items():
            start_time = _ticks_to_seconds(start_tick, tempo_changes, ticks_per_beat)
            end_time = _ticks_to_seconds(final_tick, tempo_changes, ticks_per_beat)
            duration = max(end_time - start_time, 0.1)  # minimum 100ms
            all_notes.append(
                NoteEvent(
                    note=note_num,
                    velocity=velocity,
                    start_time=start_time,
                    duration=duration,
                    track=track_idx,
                    channel=ch,
                )
            )
            note_count += 1

        if note_count > 0 or track_idx == 0:
            track_infos.append(
                TrackInfo(
                    index=track_idx,
                    name=track_name,
                    note_count=note_count,
                    channel=channel,
                )
            )

    # Sort notes by start time
    all_notes.sort(key=lambda n: (n.start_time, n.note))

    # Calculate total duration
    total_duration = 0.0
    if all_notes:
        total_duration = max(n.end_time for n in all_notes)

    return MidiFileInfo(
        file_path=file_path,
        ticks_per_beat=ticks_per_beat,
        duration=total_duration,
        tracks=track_infos,
        notes=all_notes,
        tempo_changes=tempo_changes,
    )
