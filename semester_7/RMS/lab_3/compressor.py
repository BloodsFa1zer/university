"""Стиснення з втратами: зменшення кількості значущих коефіцієнтів DCT/DWT.

Режими (однакові для обох методів, щоб порівняння було чесним):
  keep      — зберегти задану частку (%) найбільших за модулем коефіцієнтів;
  threshold — обнулити коефіцієнти з |c| < T (жорсткий поріг);
  quant     — рівномірне квантування з кроком Q: c → round(c / Q) · Q.
DC-коефіцієнти DCT та підсмуга LL вейвлета не мають жодних привілеїв:
вони конкурують за місце на загальних підставах (зображення центроване,
тому малі за модулем DC-коефіцієнти теж можуть бути відкинуті).
"""
from dataclasses import dataclass

import numpy as np
from PIL import Image

from dct import dct2_blocks, idct2_blocks
from dwt import dwt2, idwt2
from metrics import entropy_bits

MODES = ("keep", "threshold", "quant")
METHODS = ("dct", "dwt")


def keep_largest(coeffs: np.ndarray, fraction: float) -> np.ndarray:
    """Залишає частку fraction (0..1) найбільших за модулем коефіцієнтів, решту обнуляє."""
    n = coeffs.size
    k = int(round(fraction * n))
    if k >= n:
        return coeffs.copy()
    out = np.zeros_like(coeffs)
    if k <= 0:
        return out
    flat = np.abs(coeffs).ravel()
    idx = np.argpartition(flat, n - k)[n - k:]  # індекси k найбільших |c|
    out.ravel()[idx] = coeffs.ravel()[idx]
    return out


def hard_threshold(coeffs: np.ndarray, t: float) -> np.ndarray:
    """Обнуляє всі коефіцієнти, менші за поріг t за модулем."""
    return np.where(np.abs(coeffs) >= t, coeffs, 0.0)


def quantize(coeffs: np.ndarray, step: float) -> np.ndarray:
    """Рівномірне квантування: індекс q = round(c / step), відновлення q · step."""
    return np.round(coeffs / step) * step


def reduce_coefficients(coeffs: np.ndarray, mode: str, param: float) -> np.ndarray:
    """Застосовує обраний режим стиснення до масиву коефіцієнтів."""
    if mode == "keep":
        return keep_largest(coeffs, param / 100.0)  # param — відсоток
    if mode == "threshold":
        return hard_threshold(coeffs, param)
    if mode == "quant":
        return quantize(coeffs, param)
    raise ValueError(f"Невідомий режим: {mode}")


@dataclass
class Result:
    image: np.ndarray   # відновлене зображення, uint8
    coeffs: np.ndarray  # коефіцієнти після стиснення
    kept: int           # кількість ненульових коефіцієнтів
    total: int          # загальна кількість коефіцієнтів
    bpp: float          # оцінка біт/піксель за ентропією

    @property
    def kept_fraction(self) -> float:
        return self.kept / self.total

    @property
    def ratio_nonzero(self) -> float:
        """Коефіцієнт стиснення як N_усіх / N_ненульових."""
        return self.total / max(self.kept, 1)

    @property
    def ratio_entropy(self) -> float:
        """Коефіцієнт стиснення відносно 8 біт/піксель вихідного зображення."""
        return 8.0 / self.bpp if self.bpp > 0 else float("inf")


def compress(img: np.ndarray, method: str, mode: str, param: float, levels: int = 3) -> Result:
    """Пряме перетворення → відкидання коефіцієнтів → обернене перетворення."""
    if method == "dct":
        coeffs = dct2_blocks(img)
    elif method == "dwt":
        coeffs = dwt2(img, levels)
    else:
        raise ValueError(f"Невідомий метод: {method}")

    reduced = reduce_coefficients(coeffs, mode, param)

    if method == "dct":
        restored = idct2_blocks(reduced, img.shape)
    else:
        restored = idwt2(reduced, img.shape, levels)
    restored = np.clip(np.round(restored), 0, 255).astype(np.uint8)

    # Для оцінки обсягу коефіцієнти округлюються до індексів квантувача
    # (для keep/threshold — крок 1, для quant — крок Q).
    step = param if mode == "quant" else 1.0
    symbols = np.round(reduced / step)
    bpp = entropy_bits(symbols) / (img.shape[0] * img.shape[1])

    return Result(restored, reduced, int(np.count_nonzero(reduced)), reduced.size, bpp)


def load_gray(path: str) -> np.ndarray:
    """Завантажує будь-яке зображення та перетворює його у відтінки сірого (uint8)."""
    return np.asarray(Image.open(path).convert("L"), dtype=np.uint8)
