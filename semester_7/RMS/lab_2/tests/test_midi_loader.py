"""Тести розбору MIDI: переведення тіків у секунди, зміни темпу, note_on з velocity 0."""
import sys
import unittest
from pathlib import Path

import mido

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from midi_loader import TempoMap, load_song, note_name, validate_song  # noqa: E402

TPB = 480


def make_file(tracks):
    mid = mido.MidiFile(type=1, ticks_per_beat=TPB)
    for msgs in tracks:
        mid.tracks.append(mido.MidiTrack(msgs))
    return mid


class TempoTests(unittest.TestCase):
    def test_default_tempo_is_120_bpm(self):
        tm = TempoMap(TPB, [])
        self.assertAlmostEqual(tm.to_seconds(TPB), 0.5)          # 1 доля при 120 BPM = 0.5 с

    def test_tempo_change_shifts_later_events(self):
        # 4 долі при 120 BPM (2.0 с), далі 60 BPM (1 доля = 1.0 с)
        tm = TempoMap(TPB, [(0, mido.bpm2tempo(120)), (4 * TPB, mido.bpm2tempo(60))])
        self.assertAlmostEqual(tm.to_seconds(4 * TPB), 2.0)
        self.assertAlmostEqual(tm.to_seconds(5 * TPB), 3.0)
        self.assertAlmostEqual(tm.to_seconds(6 * TPB), 4.0)
        self.assertAlmostEqual(tm.bpm_at(1.0), 120)
        self.assertAlmostEqual(tm.bpm_at(2.5), 60)

    def test_tempo_in_separate_track_applies_to_notes(self):
        conductor = [mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(120), time=0),
                     mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(60), time=4 * TPB)]
        notes = [mido.Message("note_on", note=60, velocity=100, time=0),
                 mido.Message("note_off", note=60, time=4 * TPB),          # кінець: 2.0 с
                 mido.Message("note_on", note=62, velocity=90, time=TPB),  # 5-та доля: 3.0 с
                 mido.Message("note_off", note=62, time=TPB)]              # 6-та доля: 4.0 с
        song = load_song(make_file([conductor, notes]))
        n1, n2 = song.voices[0].notes
        self.assertAlmostEqual(n1.start, 0.0)
        self.assertAlmostEqual(n1.end, 2.0)
        self.assertAlmostEqual(n2.start, 3.0)
        self.assertAlmostEqual(n2.end, 4.0)
        self.assertAlmostEqual(song.duration, 4.0)


class NoteTests(unittest.TestCase):
    def test_note_on_with_zero_velocity_is_note_off(self):
        track = [mido.Message("note_on", note=64, velocity=100, time=0),
                 mido.Message("note_on", note=64, velocity=0, time=TPB)]
        song = load_song(make_file([track]))
        (note,) = song.voices[0].notes
        self.assertEqual(note.velocity, 100)
        self.assertAlmostEqual(note.duration, 0.5)

    def test_drums_and_program_and_names(self):
        t1 = [mido.MetaMessage("track_name", name="Lead", time=0),
              mido.Message("program_change", program=80, channel=0, time=0),
              mido.Message("note_on", note=72, velocity=90, channel=0, time=0),
              mido.Message("note_off", note=72, channel=0, time=TPB)]
        t2 = [mido.MetaMessage("track_name", name="Drums", time=0),
              mido.Message("note_on", note=36, velocity=120, channel=9, time=0),
              mido.Message("note_off", note=36, channel=9, time=60)]
        song = load_song(make_file([t1, t2]))
        lead, drums = song.voices
        self.assertEqual((lead.name, lead.program, lead.is_drum), ("Lead", 80, False))
        self.assertEqual((drums.name, drums.is_drum), ("Drums", True))
        self.assertEqual(song.note_track_count, 2)
        self.assertEqual(validate_song(song), [])

    def test_unterminated_note_is_closed_at_track_end(self):
        track = [mido.Message("note_on", note=60, velocity=80, time=0),
                 mido.MetaMessage("end_of_track", time=2 * TPB)]
        song = load_song(make_file([track]))
        self.assertAlmostEqual(song.voices[0].notes[0].end, 1.0)

    def test_single_track_file_gets_warning(self):
        track = [mido.Message("note_on", note=60, velocity=80, time=0),
                 mido.Message("note_off", note=60, time=TPB)]
        self.assertTrue(validate_song(load_song(make_file([track]))))

    def test_note_name(self):
        self.assertEqual(note_name(60), "C4")
        self.assertEqual(note_name(69), "A4")
        self.assertEqual(note_name(61), "C#4")


class DemoFilesTests(unittest.TestCase):
    def test_demo_files_have_at_least_two_tracks(self):
        midi_dir = Path(__file__).resolve().parents[1] / "midi"
        for name in ("demo_song.mid", "mapping_test.mid"):
            song = load_song(midi_dir / name)
            self.assertGreaterEqual(song.note_track_count, 2, name)
            self.assertEqual(validate_song(song), [], name)
            self.assertGreaterEqual(len(song.tempo_map.segments()), 2, name)   # є зміна темпу


if __name__ == "__main__":
    unittest.main()
