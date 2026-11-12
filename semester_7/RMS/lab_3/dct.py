"""Дискретне косинусне перетворення (DCT-II) блоками 8×8 у матричній формі.

Пряме перетворення блоку X:   Y = C · X · Cᵀ
Обернене перетворення:        X = Cᵀ · Y · C
де C — ортонормована матриця DCT-II 8×8 (C · Cᵀ = I, тому C⁻¹ = Cᵀ).
"""
import numpy as np

BLOCK = 8


def dct_matrix(n: int = BLOCK) -> np.ndarray:
    """Ортонормована матриця DCT-II розміру n×n.

    C[k, i] = a(k) · cos(π · (2i + 1) · k / (2n)),
    a(0) = √(1/n),  a(k) = √(2/n) для k > 0.
    Рядок k — k-та косинусоїда (k = 0 — постійна складова, DC).
    """
    k = np.arange(n).reshape(-1, 1)  # номер частоти (рядок матриці)
    i = np.arange(n).reshape(1, -1)  # номер пікселя (стовпець матриці)
    c = np.sqrt(2.0 / n) * np.cos(np.pi * (2 * i + 1) * k / (2 * n))
    c[0, :] = np.sqrt(1.0 / n)
    return c


C = dct_matrix()


def pad_to_multiple(img: np.ndarray, m: int) -> np.ndarray:
    """Доповнює зображення повторенням крайніх пікселів до розміру, кратного m."""
    h, w = img.shape
    ph, pw = (-h) % m, (-w) % m
    if ph or pw:
        img = np.pad(img, ((0, ph), (0, pw)), mode="edge")
    return img


def to_blocks(img: np.ndarray, n: int = BLOCK) -> np.ndarray:
    """(H, W) -> (H/n, W/n, n, n): зображення як сітка блоків n×n."""
    h, w = img.shape
    return img.reshape(h // n, n, w // n, n).swapaxes(1, 2)


def from_blocks(blocks: np.ndarray) -> np.ndarray:
    """(H/n, W/n, n, n) -> (H, W): зворотне склеювання блоків."""
    bh, bw, n, _ = blocks.shape
    return blocks.swapaxes(1, 2).reshape(bh * n, bw * n)


def dct2_blocks(img: np.ndarray) -> np.ndarray:
    """Пряме DCT зображення блоками 8×8.

    1) доповнення до кратного 8, 2) центрування (−128),
    3) для кожного блоку Y = C · X · Cᵀ (numpy множить усі блоки одразу).
    Результат має розмір доповненого зображення: блок коефіцієнтів 8×8
    лежить на місці відповідного блоку пікселів, у його лівому верхньому
    куті — DC-коефіцієнт.
    """
    x = pad_to_multiple(np.asarray(img, dtype=np.float64), BLOCK) - 128.0
    y = C @ to_blocks(x) @ C.T
    return from_blocks(y)


def idct2_blocks(coeffs: np.ndarray, shape: tuple) -> np.ndarray:
    """Обернене DCT: X = Cᵀ · Y · C для кожного блоку, +128, обрізання до shape.

    Повертає дійсні значення (без округлення й обмеження 0..255).
    """
    x = C.T @ to_blocks(coeffs) @ C
    return from_blocks(x)[: shape[0], : shape[1]] + 128.0
