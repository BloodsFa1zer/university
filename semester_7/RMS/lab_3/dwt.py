"""Дискретне вейвлет-перетворення Хаара (2D, багаторівневе, ортонормоване).

Один крок 1D для пари сусідніх відліків (a, b):
    L = (a + b) / √2   — середнє (низькі частоти)
    H = (a − b) / √2   — різниця (високі частоти, деталі)
Обернений крок:  a = (L + H) / √2,  b = (L − H) / √2.

2D-рівень: крок по рядках, потім по стовпцях → чотири підсмуги
    [[LL, HL],
     [LH, HH]]
LL — зменшена копія зображення; на наступному рівні перетворюється лише LL.
"""
import numpy as np

from dct import pad_to_multiple

SQRT2 = np.sqrt(2.0)


def haar_rows(x: np.ndarray) -> np.ndarray:
    """Один крок Хаара вздовж рядків: [L | H] (ліва половина — L, права — H)."""
    a, b = x[:, 0::2], x[:, 1::2]  # парні та непарні стовпці
    return np.hstack([(a + b) / SQRT2, (a - b) / SQRT2])


def ihaar_rows(y: np.ndarray) -> np.ndarray:
    """Обернений крок Хаара вздовж рядків."""
    half = y.shape[1] // 2
    low, high = y[:, :half], y[:, half:]
    x = np.empty_like(y)
    x[:, 0::2] = (low + high) / SQRT2
    x[:, 1::2] = (low - high) / SQRT2
    return x


def haar2d(x: np.ndarray) -> np.ndarray:
    """Один рівень 2D Хаара: рядки, потім стовпці (через транспонування)."""
    return haar_rows(haar_rows(x).T).T


def ihaar2d(y: np.ndarray) -> np.ndarray:
    """Обернений рівень 2D: спочатку стовпці, потім рядки (зворотний порядок)."""
    return ihaar_rows(ihaar_rows(y.T).T)


def dwt2(img: np.ndarray, levels: int = 3) -> np.ndarray:
    """Пряме багаторівневе DWT Хаара.

    Зображення доповнюється до кратного 2^levels і центрується (−128),
    як і для DCT. Коефіцієнти зберігаються в одному масиві (схема Маллата):
    у лівому верхньому куті — LL останнього рівня.
    """
    out = pad_to_multiple(np.asarray(img, dtype=np.float64), 2 ** levels) - 128.0
    h, w = out.shape
    for _ in range(levels):
        out[:h, :w] = haar2d(out[:h, :w])
        h, w = h // 2, w // 2  # наступний рівень — лише підсмуга LL
    return out


def idwt2(coeffs: np.ndarray, shape: tuple, levels: int = 3) -> np.ndarray:
    """Обернене DWT: рівні відновлюються від найменшого LL до повного розміру.

    Повертає дійсні значення (без округлення й обмеження 0..255).
    """
    out = np.array(coeffs, dtype=np.float64, copy=True)
    full_h, full_w = out.shape
    for lev in reversed(range(levels)):
        h, w = full_h >> lev, full_w >> lev
        out[:h, :w] = ihaar2d(out[:h, :w])
    return out[: shape[0], : shape[1]] + 128.0
