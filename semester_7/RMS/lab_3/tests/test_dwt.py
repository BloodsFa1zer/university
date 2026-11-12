"""Перевірки власної реалізації вейвлета Хаара."""
import unittest

import numpy as np

from dwt import dwt2, haar2d, idwt2


class HaarTest(unittest.TestCase):
    def test_single_level_known_values(self):
        x = np.array([[1.0, 2.0], [3.0, 4.0]])
        y = haar2d(x)
        # LL = сума/2, HL = (1−2+3−4)/2, LH = (1+2−3−4)/2, HH = (1−2−3+4)/2
        self.assertTrue(np.allclose(y, [[5.0, -1.0], [-2.0, 0.0]]))

    def test_perfect_reconstruction_all_levels(self):
        rng = np.random.default_rng(0)
        img = rng.integers(0, 256, size=(64, 64)).astype(float)
        for levels in range(1, 6):
            restored = idwt2(dwt2(img, levels), img.shape, levels)
            self.assertLess(np.max(np.abs(restored - img)), 1e-9, f"levels={levels}")

    def test_energy_preserved(self):
        # Ортонормоване перетворення зберігає енергію (рівність Парсеваля).
        rng = np.random.default_rng(1)
        img = rng.integers(0, 256, size=(32, 32)).astype(float)
        coeffs = dwt2(img, 3)
        self.assertAlmostEqual(np.sum(coeffs ** 2), np.sum((img - 128.0) ** 2), places=6)

    def test_constant_image_only_ll(self):
        coeffs = dwt2(np.full((16, 16), 160.0), 2)
        # LL після 2 рівнів = 4 · (160 − 128), усі деталі нульові.
        self.assertTrue(np.allclose(coeffs[:4, :4], 4 * 32.0))
        coeffs[:4, :4] = 0
        self.assertLess(np.max(np.abs(coeffs)), 1e-9)

    def test_odd_size_padding_and_crop(self):
        rng = np.random.default_rng(2)
        img = rng.integers(0, 256, size=(37, 53)).astype(float)
        coeffs = dwt2(img, 3)
        self.assertEqual(coeffs.shape, (40, 56))
        restored = idwt2(coeffs, img.shape, 3)
        self.assertEqual(restored.shape, img.shape)
        self.assertLess(np.max(np.abs(restored - img)), 1e-9)


if __name__ == "__main__":
    unittest.main()
