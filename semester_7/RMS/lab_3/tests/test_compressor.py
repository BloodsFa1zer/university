"""Перевірки механізму стиснення та метрик."""
import os
import unittest

import numpy as np

from compressor import compress, hard_threshold, keep_largest, load_gray, quantize
from metrics import entropy_bits, psnr

IMAGES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "images")


class MetricsTest(unittest.TestCase):
    def test_psnr_identical_is_inf(self):
        img = np.full((8, 8), 100, dtype=np.uint8)
        self.assertEqual(psnr(img, img), float("inf"))

    def test_psnr_known_value(self):
        a = np.full((8, 8), 100, dtype=np.uint8)
        b = a + 1  # MSE = 1 → PSNR = 20·log10(255) ≈ 48.13 дБ
        self.assertAlmostEqual(psnr(a, b), 20 * np.log10(255), places=9)

    def test_entropy(self):
        self.assertAlmostEqual(entropy_bits(np.array([0, 0, 1, 1])), 4.0)  # 1 біт на символ
        self.assertEqual(entropy_bits(np.zeros(10)), 0.0)


class ReductionTest(unittest.TestCase):
    def test_keep_largest_keeps_exact_count_of_biggest(self):
        rng = np.random.default_rng(0)
        c = rng.normal(size=(16, 16))
        out = keep_largest(c, 0.1)
        k = round(0.1 * c.size)
        self.assertEqual(np.count_nonzero(out), k)
        self.assertGreaterEqual(np.min(np.abs(out[out != 0])), np.max(np.abs(c[out == 0])))

    def test_threshold_and_quantize(self):
        c = np.array([-3.0, -0.5, 0.2, 1.0, 4.4])
        self.assertTrue(np.array_equal(hard_threshold(c, 1.0), [-3.0, 0.0, 0.0, 1.0, 4.4]))
        self.assertTrue(np.allclose(quantize(c, 2.0), [-4.0, 0.0, 0.0, 0.0, 4.0]))


class CompressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.img = load_gray(os.path.join(IMAGES, "camera.png"))

    def test_keep_100_percent_is_lossless(self):
        for method in ("dct", "dwt"):
            res = compress(self.img, method, "keep", 100)
            self.assertTrue(np.array_equal(res.image, self.img), method)

    def test_psnr_decreases_with_fewer_coefficients(self):
        for method in ("dct", "dwt"):
            values = [psnr(self.img, compress(self.img, method, "keep", p).image) for p in (50, 25, 10, 5, 2, 1)]
            self.assertEqual(values, sorted(values, reverse=True), method)

    def test_kept_count_matches_fraction(self):
        res = compress(self.img, "dct", "keep", 5)
        self.assertEqual(res.kept, round(0.05 * self.img.size))


if __name__ == "__main__":
    unittest.main()
