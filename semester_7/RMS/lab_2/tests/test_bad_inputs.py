"""Тести на некоректні вхідні дані: програма має пояснити помилку, а не впасти."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import pygame  # noqa: E402

import make_test_inputs  # noqa: E402
from midi_loader import MidiLoadError, load_song, validate_song  # noqa: E402
from scene import Scene, ViewState  # noqa: E402


class SampleFilesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.files = {p.name.split("_", 1)[1]: p for p in make_test_inputs.build(Path(cls.tmp.name))}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_ok_files_load_without_warnings(self):
        for name in ("ok_type0_multichannel.mid", "ok_tempo_changes.mid", "ok_extreme_values.mid"):
            with self.subTest(name):
                song = load_song(self.files[name])
                self.assertGreaterEqual(len(song.voices), 2)
                self.assertEqual(validate_song(song), [])

    def test_type0_channels_become_separate_voices(self):
        song = load_song(self.files["ok_type0_multichannel.mid"])
        self.assertEqual(song.midi_type, 0)
        self.assertEqual(sorted(v.channel for v in song.voices), [0, 1, 9])

    def test_warnings(self):
        expected = {"warn_one_track.mid": "менше двох доріжок",
                    "warn_no_notes.mid": "немає нот",
                    "warn_unpaired_notes.mid": "без note_off"}
        for name, text in expected.items():
            with self.subTest(name):
                warnings = validate_song(load_song(self.files[name]))
                self.assertTrue(any(text in w for w in warnings), warnings)

    def test_unpaired_notes_are_counted(self):
        song = load_song(self.files["warn_unpaired_notes.mid"])
        self.assertIn("нот без note_off: 2 (закрито в кінці треку)", song.issues)
        self.assertIn("note_off без note_on: 1 (пропущено)", song.issues)

    def test_bad_files_raise_readable_error(self):
        expected = {"bad_empty.mid": "порожній",
                    "bad_not_midi.mid": "не MIDI-файл",
                    "bad_truncated.mid": "обрізаний",
                    "bad_zero_ticks.mid": "ticks_per_beat = 0",
                    "bad_data_byte.mid": "пошкоджені дані"}
        for name, text in expected.items():
            with self.subTest(name):
                with self.assertRaises(MidiLoadError) as ctx:
                    load_song(self.files[name])
                self.assertIn(text, str(ctx.exception))

    def test_missing_file(self):
        with self.assertRaises(MidiLoadError):
            load_song(Path(self.tmp.name) / "немає_такого.mid")

    def test_scene_renders_song_without_notes(self):
        pygame.init()
        song = load_song(self.files["warn_no_notes.mid"])
        surf = pygame.Surface((1280, 720))
        state = ViewState(warnings=validate_song(song), message="тест", message_error=True)
        Scene(song, (1280, 720)).render(surf, 1.0, state)



def _write(path: Path, tracks, tpb=480):
    """Невеликий MIDI-файл для тесту: tracks — список списків повідомлень mido."""
    import mido
    mid = mido.MidiFile(type=1, ticks_per_beat=tpb)
    for msgs in tracks:
        mid.tracks.append(mido.MidiTrack(msgs))
    mid.save(path)
    return path


class EdgeCaseTests(unittest.TestCase):
    """Випадки, знайдені під час перевірки: раніше вони валили програму або вводили в оману."""

    @classmethod
    def setUpClass(cls):
        import mido
        cls.mido = mido
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def notes(self, ch=0, program=0, n=2):
        M = self.mido.Message
        out = [M("program_change", channel=ch, program=program, time=0)]
        for _ in range(n):
            out += [M("note_on", channel=ch, note=60, velocity=90, time=0),
                    M("note_off", channel=ch, note=60, velocity=0, time=480)]
        return out

    def test_zero_tempo_is_rejected(self):
        meta = [self.mido.MetaMessage("set_tempo", tempo=0, time=0)]
        f = _write(self.dir / "tempo0.mid", [meta, self.notes(0), self.notes(1)])
        with self.assertRaises(MidiLoadError) as ctx:
            load_song(f)
        self.assertIn("set_tempo", str(ctx.exception))

    def test_too_long_file_is_rejected(self):
        M = self.mido.Message
        held = [M("note_on", note=60, velocity=90, time=0), M("note_off", note=60, velocity=0, time=0x0FFFFFFF)]
        f = _write(self.dir / "huge.mid", [held, self.notes(1)])
        with self.assertRaises(MidiLoadError) as ctx:
            load_song(f)
        self.assertIn("задовгий", str(ctx.exception))

    def test_directory_is_reported_as_folder(self):
        with self.assertRaises(MidiLoadError) as ctx:
            load_song(self.dir)
        self.assertIn("папка", str(ctx.exception))

    def test_program_change_after_first_note_is_logged_as_no_effect(self):
        M = self.mido.Message
        t1 = self.notes(0, program=0) + [M("program_change", channel=0, program=33, time=0)] + self.notes(0, 0, 1)[1:]
        f = _write(self.dir / "prog.mid", [t1, self.notes(1, program=80)])
        pygame.init()
        scene = Scene(load_song(f), (1280, 720))
        prog_lines = [text for _, _, text in scene.log if " prog " in text]
        self.assertTrue(any("prog 33" in t and "без змін" in t for t in prog_lines), prog_lines)
        self.assertTrue(any("prog 0" in t and "circle" in t for t in prog_lines), prog_lines)

    def test_log_lines_are_never_cut_mid_number(self):
        pygame.init()
        song = load_song(ROOT / "midi" / "demo_song.mid")
        for size in ((640, 360), (1280, 720)):
            scene = Scene(song, size)
            width = scene.L.panel.right - (scene.L.panel.x + 8) - 6
            for _, _, text in scene.log[:200]:
                surf = scene._fit(text, width, (255, 255, 255))
                self.assertLessEqual(surf.get_width(), width + 1, text)


class CliValidationTests(unittest.TestCase):
    def test_bad_values_give_argparse_error_not_traceback(self):
        import contextlib
        import io
        import app
        for argv in (["--screenshot", "abc"], ["--hide", "x"], ["--fps", "0"],
                     ["--start", "5", "--end", "2"], ["--focus", "0"]):
            with self.subTest(argv), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as ctx:
                    app.parse_args(argv)
                self.assertEqual(ctx.exception.code, 2)

    def test_good_values_are_parsed(self):
        import app
        args = app.parse_args(["--screenshot", "5,12.5", "--hide", "2,3", "--fps", "25"])
        self.assertEqual(args.screenshot, [5.0, 12.5])
        self.assertEqual(args.hide, {2, 3})
        self.assertEqual(args.fps, 25)


if __name__ == "__main__":
    unittest.main()
