"""Метрики якості та оцінка обсягу даних."""
import numpy as np


def mse(original: np.ndarray, restored: np.ndarray) -> float:
    """Середньоквадратична помилка."""
    diff = original.astype(np.float64) - restored.astype(np.float64)
    return float(np.mean(diff ** 2))


def psnr(original: np.ndarray, restored: np.ndarray, max_value: float = 255.0) -> float:
    """PSNR = 10 · log10(MAX² / MSE), дБ. Для однакових зображень — нескінченність."""
    m = mse(original, restored)
    if m == 0:
        return float("inf")
    return float(10.0 * np.log10(max_value ** 2 / m))


def ssim(original: np.ndarray, restored: np.ndarray) -> float:
    """SSIM (додаткова метрика, готова реалізація зі scikit-image)."""
    from skimage.metrics import structural_similarity

    return float(structural_similarity(original, restored, data_range=255))


def entropy_bits(symbols: np.ndarray) -> float:
    """Оцінка кількості біт за ентропією Шеннона нульового порядку: N · H.

    H = −Σ p·log2(p), де p — частоти появи кожного значення.
    Це нижня межа для ідеального ентропійного кодера без урахування
    службової інформації, а не реальний розмір файлу.
    """
    _, counts = np.unique(symbols, return_counts=True)
    p = counts / counts.sum()
    return float(-(p * np.log2(p)).sum() * symbols.size)
