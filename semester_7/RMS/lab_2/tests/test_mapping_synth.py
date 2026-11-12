"""Тести правил відображення і синтезатора."""
import os
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mapping as mp  # noqa: E402
import synth  # noqa: E402
from midi_loader import load_song  # noqa: E402


class MappingTests(unittest.TestCase):
    def test_higher_pitch_is_higher_on_screen(self):
        ys = [mp.pitch_to_y(p, 40, 90, top=50, bottom=500) for p in range(40, 91)]
        self.assertTrue(all(a > b for a, b in zip(ys, ys[1:])))      # Y спадає -> об'єкт вище
        self.assertEqual(ys[0], 500)
        self.assertEqual(ys[-1], 50)

    def test_louder_note_is_bigger_and_brighter(self):
        sizes = [mp.velocity_to_size(v) for v in range(1, 128)]
        bright = [mp.velocity_to_brightness(v) for v in range(1, 128)]
        self.assertTrue(all(a < b for a, b in zip(sizes, sizes[1:])))
        self.assertTrue(all(a < b for a, b in zip(bright, bright[1:])))
        self.assertLessEqual(max(bright), 1.0)

    def test_longer_note_fades_longer_and_tempo_speeds_up_scene(self):
        self.assertLess(mp.release_time(0.1), mp.release_time(1.0))
        self.assertLess(mp.tempo_to_scroll_speed(90), mp.tempo_to_scroll_speed(150))

    def test_program_and_drum_mapping(self):
        self.assertEqual(mp.program_to_shape(0), "circle")       # Piano
        self.assertEqual(mp.program_to_shape(38), "diamond")     # Synth Bass
        self.assertEqual(mp.program_to_shape(89), "hexagon")     # Synth Pad
        self.assertEqual(mp.DRUM_EFFECTS[mp.drum_kind(36)], "pulse")
        self.assertEqual(mp.DRUM_EFFECTS[mp.drum_kind(38)], "burst")
        self.assertEqual(mp.DRUM_EFFECTS[mp.drum_kind(42)], "sparkle")
        self.assertEqual(mp.DRUM_EFFECTS[mp.drum_kind(49)], "flash")

    def test_pop_animation(self):
        self.assertEqual(mp.pop_scale(0), 0)
        self.assertGreater(mp.pop_scale(0.08), 1.0)               # "перестрибує"
        self.assertEqual(mp.pop_scale(1.0), 1.0)                  # і осідає до 1


class SynthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.song = load_song(Path(__file__).resolve().parents[1] / "midi" / "mapping_test.mid")

    def test_stems_have_song_duration_plus_tail(self):
        stems = synth.render_stems(self.song)
        expected = int(round((self.song.duration + synth.TAIL) * synth.SR))
        self.assertEqual(len(stems), len(self.song.voices))
        for stem in stems:
            self.assertEqual(len(stem), expected)

    def test_mix_is_normalized_and_mute_works(self):
        stems = synth.render_stems(self.song)
        pans = synth.default_pans(self.song)
        master = synth.master_gain(stems, pans)
        full = synth.mix(stems, pans, master=master)
        self.assertEqual(full.shape[1], 2)
        self.assertAlmostEqual(float(np.max(np.abs(full))), 0.89, places=3)
        silent = synth.mix(stems, pans, muted=set(range(len(stems))), master=master)
        self.assertEqual(float(np.max(np.abs(silent))), 0.0)

    def test_note_frequency(self):
        self.assertAlmostEqual(synth.midi_to_freq(69), 440.0)
        self.assertAlmostEqual(synth.midi_to_freq(81), 880.0)
        tone = synth.render_note(69, 100, 0.5, program=80)
        self.assertEqual(len(tone), int(0.5 * synth.SR) + int(synth.TIMBRES["lead"]["r"] * synth.SR))


class SceneSmokeTest(unittest.TestCase):
    def test_frames_render_without_errors(self):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        import pygame
        pygame.init()
        from scene import Scene, ViewState
        song = load_song(Path(__file__).resolve().parents[1] / "midi" / "demo_song.mid")
        scene = Scene(song, (1280, 720))
        surf = pygame.Surface((1280, 720))
        for t in (0.0, 5.0, 19.3, 30.0, scene.end_time):
            scene.render(surf, t, ViewState())
            scene.render(surf, t, ViewState(hidden={0, 4}, focus=1, help=True))
        # у момент удару kick сцена світліша, ніж трохи раніше (ефект пульсації)
        kick = next(n.start for n in song.voices[4].notes if n.pitch == 36 and n.start > 5)
        before = pygame.Surface((1280, 720))
        scene.render(before, kick - 0.2, ViewState())
        scene.render(surf, kick + 0.02, ViewState())
        rect = scene.L.stage.inflate(-40, -40)
        mean = lambda s: pygame.surfarray.array3d(s.subsurface(rect)).mean()
        self.assertGreater(mean(surf), mean(before))


if __name__ == "__main__":
    unittest.main()
