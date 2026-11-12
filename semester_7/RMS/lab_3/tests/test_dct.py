"""Перевірки власної реалізації DCT."""
import unittest

import numpy as np

from dct import BLOCK, C, dct2_blocks, dct_matrix, idct2_blocks


def naive_dct2(block):
    """Пряма сума за означенням 2D DCT-II (без матриць) — еталон для порівняння."""
    n = block.shape[0]
    out = np.zeros((n, n))
    for u in range(n):
        for v in range(n):
            au = np.sqrt(1 / n) if u == 0 else np.sqrt(2 / n)
            av = np.sqrt(1 / n) if v == 0 else np.sqrt(2 / n)
            s = 0.0
            for x in range(n):
                for y in range(n):
                    s += (block[x, y]
                          * np.cos(np.pi * (2 * x + 1) * u / (2 * n))
                          * np.cos(np.pi * (2 * y + 1) * v / (2 * n)))
            out[u, v] = au * av * s
    return out


class DctTest(unittest.TestCase):
    def test_matrix_is_orthonormal(self):
        self.assertTrue(np.allclose(C @ C.T, np.eye(BLOCK), atol=1e-12))

    def test_matrix_matches_cosine_formula(self):
        n = 8
        expected = np.zeros((n, n))
        for k in range(n):
            a = np.sqrt(1 / n) if k == 0 else np.sqrt(2 / n)
            for i in range(n):
                expected[k, i] = a * np.cos(np.pi * (2 * i + 1) * k / (2 * n))
        self.assertTrue(np.allclose(dct_matrix(n), expected, atol=1e-12))

    def test_blockwise_dct_equals_direct_sum(self):
        rng = np.random.default_rng(0)
        img = rng.integers(0, 256, size=(16, 24)).astype(float)
        coeffs = dct2_blocks(img)
        for by in range(0, 16, 8):
            for bx in range(0, 24, 8):
                block = img[by:by + 8, bx:bx + 8] - 128.0
                self.assertTrue(np.allclose(coeffs[by:by + 8, bx:bx + 8], naive_dct2(block), atol=1e-9))

    def test_matches_scipy_reference(self):
        # Лише для перевірки: у самій програмі scipy не використовується.
        from scipy.fft import dctn

        rng = np.random.default_rng(1)
        block = rng.normal(size=(8, 8))
        self.assertTrue(np.allclose(C @ block @ C.T, dctn(block, norm="ortho"), atol=1e-12))

    def test_perfect_reconstruction(self):
        rng = np.random.default_rng(2)
        img = rng.integers(0, 256, size=(64, 64)).astype(float)
        restored = idct2_blocks(dct2_blocks(img), img.shape)
        self.assertLess(np.max(np.abs(restored - img)), 1e-9)

    def test_odd_size_padding_and_crop(self):
        rng = np.random.default_rng(3)
        img = rng.integers(0, 256, size=(37, 53)).astype(float)
        coeffs = dct2_blocks(img)
        self.assertEqual(coeffs.shape, (40, 56))
        restored = idct2_blocks(coeffs, img.shape)
        self.assertEqual(restored.shape, img.shape)
        self.assertLess(np.max(np.abs(restored - img)), 1e-9)

    def test_constant_block_has_only_dc(self):
        coeffs = dct2_blocks(np.full((8, 8), 200.0))
        self.assertAlmostEqual(coeffs[0, 0], 8 * (200 - 128))
        coeffs[0, 0] = 0
        self.assertLess(np.max(np.abs(coeffs)), 1e-9)


if __name__ == "__main__":
    unittest.main()
