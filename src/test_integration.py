"""Integration test — creates a test MIDI, renders it, and exports WAV.

This validates the full pipeline: MIDI → parse → render → export.
Run: python -m src.test_integration
"""

import logging
import sys
from pathlib import Path

import mido
import numpy as np

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.midi_parser import parse_midi
from src.engine import PerformanceEngine
from src.mixer import Mixer
from src.voice.synth_provider import SynthProvider, Waveform, ADSR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def create_test_midi(output_path: str) -> str:
    """Create a simple test MIDI file with a recognizable melody.

    Plays a C major scale + simple chord progression.
    """
    mid = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    mid.tracks.append(track)

    # Set tempo (120 BPM)
    track.append(mido.MetaMessage("set_tempo", tempo=500000, time=0))

    # Instrument: Acoustic Grand Piano
    track.append(mido.Message("program_change", program=0, time=0))

    # C major scale: C4 D4 E4 F4 G4 A4 B4 C5
    scale_notes = [60, 62, 64, 65, 67, 69, 71, 72]
    ticks_per_note = 480  # Quarter note at 480 TPQ

    for note in scale_notes:
        track.append(mido.Message("note_on", note=note, velocity=80, time=0))
        track.append(mido.Message("note_off", note=note, velocity=0, time=ticks_per_note))

    # Rest
    track.append(mido.Message("note_on", note=0, velocity=0, time=ticks_per_note))

    # Simple chord progression: C - Am - F - G
    chords = [
        ([60, 64, 67], ticks_per_note * 2),  # C major
        ([57, 60, 64], ticks_per_note * 2),  # A minor
        ([53, 57, 60], ticks_per_note * 2),  # F major (F3, A3, C4)
        ([55, 59, 62], ticks_per_note * 2),  # G major (G3, B3, D4) — actually [55,59,62] = G3,B3,D4 ✓ wait no
    ]
    # Correct G major: G3=55, B3=59, D4=62 ✓

    for chord_notes, chord_duration in chords:
        for note in chord_notes:
            track.append(mido.Message("note_on", note=note, velocity=70, time=0))
        first = True
        for note in chord_notes:
            track.append(mido.Message("note_off", note=note, velocity=0, time=chord_duration if first else 0))
            first = False

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    mid.save(str(output))
    logger.info("Created test MIDI: %s", output)
    return str(output)


def test_pipeline():
    """Run the full pipeline test."""
    output_dir = Path(__file__).parent.parent / "output"
    midi_path = output_dir / "test_scale_and_chords.mid"
    wav_path = output_dir / "test_output.wav"

    # 1. Create test MIDI
    logger.info("=" * 50)
    logger.info("Step 1: Creating test MIDI file...")
    create_test_midi(str(midi_path))

    # 2. Parse MIDI
    logger.info("Step 2: Parsing MIDI...")
    midi_info = parse_midi(str(midi_path))
    logger.info("  Tracks: %d, Notes: %d, Duration: %.1fs",
                midi_info.track_count, midi_info.note_count, midi_info.duration)
    assert midi_info.note_count > 0, "No notes parsed!"
    assert len(midi_info.notes) == 20, f"Expected 20 notes (8 scale + 12 chord), got {len(midi_info.notes)}"

    # 3. Set up engine with synth voice
    logger.info("Step 3: Setting up performance engine...")
    engine = PerformanceEngine(sample_rate=44100)

    # Piano-like voice
    piano = SynthProvider(
        waveform=Waveform.SINE,
        adsr=ADSR(attack=0.01, decay=0.3, sustain=0.5, release=0.5),
        harmonics=4,
        name="Test Piano",
    )
    engine.set_default_voice(piano)

    # 4. Render
    logger.info("Step 4: Rendering audio...")
    result = engine.render(midi_info)
    logger.info("  Rendered %d notes in %.1fs", result.note_count, result.render_time)
    logger.info("  Output duration: %.1fs, shape: %s", result.duration, result.audio.shape)

    assert result.note_count > 0, "No notes rendered!"
    assert result.audio.shape[0] > 0, "Empty audio buffer!"

    # 5. Check audio isn't silent
    peak = np.max(np.abs(result.audio))
    logger.info("  Peak amplitude: %.4f", peak)
    assert peak > 0.01, f"Audio is nearly silent (peak={peak:.6f})"

    # 6. Export
    logger.info("Step 5: Exporting WAV...")
    mixer = Mixer(sample_rate=44100)
    exported = mixer.export_wav(
        result.audio,
        str(wav_path),
        normalize=True,
        fade_in=0.02,
        fade_out=0.5,
    )

    logger.info("=" * 50)
    logger.info("ALL TESTS PASSED!")
    logger.info("Test MIDI:  %s", midi_path)
    logger.info("Output WAV: %s", wav_path)
    logger.info("=" * 50)


if __name__ == "__main__":
    test_pipeline()
