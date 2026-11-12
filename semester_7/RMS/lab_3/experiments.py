"""Серія експериментів для звіту: таблиці (CSV + Markdown) і графіки.

Запуск:  python experiments.py
Результати: results/*.csv, results/*.md, report_assets/*.png
"""
import csv
import glob
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from compressor import compress, load_gray
from dct import dct2_blocks
from dwt import dwt2
from metrics import psnr, ssim

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "results")
ASSETS = os.path.join(HERE, "report_assets")

KEEP_LEVELS = [50, 25, 10, 5, 2, 1, 0.5]   # % збережених коефіцієнтів
THRESHOLDS = [10, 20, 40, 80]              # поріг T
QUANT_STEPS = [4, 8, 16, 32, 64]           # крок квантування Q
DWT_LEVELS = 3
GRID_LEVELS = [10, 5, 2, 1]
CROPS = {"camera": (40, 170, 160), "astronaut": (40, 150, 200)}  # (y, x, розмір)
METHOD_NAMES = {"dct": "DCT 8×8", "dwt": f"DWT Хаара ({DWT_LEVELS} р.)"}


def measure(img, method, mode, param, levels=DWT_LEVELS):
    res = compress(img, method, mode, param, levels)
    return res, {
        "method": METHOD_NAMES[method] if levels == DWT_LEVELS or method == "dct" else f"DWT Хаара ({levels} р.)",
        "param": param,
        "kept": res.kept,
        "kept_pct": 100 * res.kept_fraction,
        "cr_nz": res.ratio_nonzero,
        "bpp": res.bpp,
        "cr_ent": res.ratio_entropy,
        "psnr": psnr(img, res.image),
        "ssim": ssim(img, res.image),
    }


def write_tables(name, rows, param_title):
    os.makedirs(RESULTS, exist_ok=True)
    keys = ["image", "method", "param", "kept", "kept_pct", "cr_nz", "bpp", "cr_ent", "psnr", "ssim"]
    with open(os.path.join(RESULTS, f"{name}.csv"), "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)
    header = (f"| Зображення | Метод | {param_title} | Ненульових коеф. | Частка, % | CR = N/Nnz "
              "| біт/піксель (оцінка) | CR = 8/bpp | PSNR, дБ | SSIM |")
    lines = [header, "|" + "---|" * 10]
    for r in rows:
        lines.append(f"| {r['image']} | {r['method']} | {r['param']:g} | {r['kept']} | {r['kept_pct']:.2f} "
                     f"| {r['cr_nz']:.1f} | {r['bpp']:.3f} | {r['cr_ent']:.1f} | {r['psnr']:.2f} | {r['ssim']:.3f} |")
    with open(os.path.join(RESULTS, f"{name}.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def write_compact_table(rows):
    """Компактна таблиця для звіту: DCT і DWT в одному рядку для кожного рівня."""
    lines = []
    for name in dict.fromkeys(r["image"] for r in rows):
        lines += [f"**{name}**", "",
                  "| Збережено, % | Коефіцієнтів | CR = N/Nnz | біт/піксель (DCT / DWT) "
                  "| PSNR DCT, дБ | PSNR DWT, дБ | SSIM DCT | SSIM DWT |",
                  "|" + "---|" * 8]
        for p in KEEP_LEVELS:
            d, w = (next(r for r in rows if r["image"] == name and r["param"] == p and r["method"] == METHOD_NAMES[m])
                    for m in ("dct", "dwt"))
            lines.append(f"| {p:g} | {d['kept']} | {d['cr_nz']:.0f} | {d['bpp']:.2f} / {w['bpp']:.2f} "
                         f"| {d['psnr']:.2f} | {w['psnr']:.2f} | {d['ssim']:.3f} | {w['ssim']:.3f} |")
        lines.append("")
    with open(os.path.join(RESULTS, "keep_compact.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def run_mode(images, mode, params, param_title):
    rows = []
    for name, img in images.items():
        for p in params:
            for method in ("dct", "dwt"):
                _, row = measure(img, method, mode, p)
                rows.append({"image": name, **row})
    write_tables(mode, rows, param_title)
    return rows


def plot_psnr_vs_kept(rows):
    fig, ax = plt.subplots(figsize=(8, 5))
    styles = {"camera": "-", "astronaut": "--"}
    for name in styles:
        for method, color in ((METHOD_NAMES["dct"], "tab:blue"), (METHOD_NAMES["dwt"], "tab:orange")):
            sel = [r for r in rows if r["image"] == name and r["method"] == method]
            ax.plot([r["kept_pct"] for r in sel], [r["psnr"] for r in sel], styles[name], color=color,
                    marker="o", label=f"{method}, {name}")
    ax.set_xscale("log")
    ax.set_xticks(KEEP_LEVELS, [f"{p:g}" for p in KEEP_LEVELS])
    ax.set_xlabel("Частка збережених коефіцієнтів, % (лог. шкала)")
    ax.set_ylabel("PSNR, дБ")
    ax.set_title("PSNR залежно від частки збережених коефіцієнтів")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(ASSETS, "psnr_vs_kept.png"), dpi=120)
    plt.close(fig)


def plot_rate_distortion(rows):
    fig, ax = plt.subplots(figsize=(8, 5))
    styles = {"camera": "-", "astronaut": "--"}
    for name in styles:
        for method, color in ((METHOD_NAMES["dct"], "tab:blue"), (METHOD_NAMES["dwt"], "tab:orange")):
            sel = [r for r in rows if r["image"] == name and r["method"] == method]
            ax.plot([r["bpp"] for r in sel], [r["psnr"] for r in sel], styles[name], color=color,
                    marker="o", label=f"{method}, {name}")
    ax.set_xlabel("Оцінка обсягу, біт/піксель (ентропія квантованих коефіцієнтів)")
    ax.set_ylabel("PSNR, дБ")
    ax.set_title("Квантування з кроком Q = 4…64: якість проти обсягу")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(ASSETS, "rate_distortion.png"), dpi=120)
    plt.close(fig)


def plot_grid(name, img):
    fig, axes = plt.subplots(len(GRID_LEVELS), 3, figsize=(10.5, 3.6 * len(GRID_LEVELS)))
    for row, p in zip(axes, GRID_LEVELS):
        panels = [("Original", img)]
        for method in ("dct", "dwt"):
            res, info = measure(img, method, "keep", p)
            panels.append((f"{METHOD_NAMES[method]}, {p:g} %\nPSNR {info['psnr']:.2f} дБ", res.image))
        for ax, (title, im) in zip(row, panels):
            ax.imshow(im, cmap="gray", vmin=0, vmax=255)
            ax.set_title(title, fontsize=10)
            ax.axis("off")
    fig.tight_layout()
    fig.savefig(os.path.join(ASSETS, f"grid_{name}.png"), dpi=90)
    plt.close(fig)


def plot_crops(name, img):
    y, x, s = CROPS[name]
    levels = [5, 2, 1]
    fig, axes = plt.subplots(len(levels), 3, figsize=(10, 3.5 * len(levels)))
    for row, p in zip(axes, levels):
        panels = [("Original (фрагмент)", img)]
        for method in ("dct", "dwt"):
            res, info = measure(img, method, "keep", p)
            panels.append((f"{METHOD_NAMES[method]}, {p:g} %, PSNR {info['psnr']:.2f} дБ", res.image))
        for ax, (title, im) in zip(row, panels):
            ax.imshow(im[y:y + s, x:x + s], cmap="gray", vmin=0, vmax=255, interpolation="nearest")
            ax.set_title(title, fontsize=9)
            ax.axis("off")
    fig.tight_layout()
    fig.savefig(os.path.join(ASSETS, f"crops_{name}.png"), dpi=100)
    plt.close(fig)


def plot_coefficient_maps(img):
    dct_c, dwt_c = dct2_blocks(img), dwt2(img, DWT_LEVELS)
    # Ті самі DCT-коефіцієнти, перегруповані за частотою (u, v): 64 «підсмуги» 64×64.
    h, w = dct_c.shape
    dct_by_freq = dct_c.reshape(h // 8, 8, w // 8, 8).transpose(1, 0, 3, 2).reshape(h, w)
    fig, axes = plt.subplots(1, 3, figsize=(16, 5.8))
    panels = ((dct_c, "DCT 8×8 (блоки на своїх місцях)"),
              (dct_by_freq, "DCT, згруповані за частотою (u, v)"),
              (dwt_c, f"DWT Хаара, {DWT_LEVELS} рівні (схема Маллата)"))
    for ax, (coeffs, title) in zip(axes, panels):
        ax.imshow(np.log1p(np.abs(coeffs)), cmap="viridis")
        ax.set_title("log(1 + |c|): " + title, fontsize=10)
        ax.axis("off")
    for lev in range(DWT_LEVELS):  # межі підсмуг вейвлета
        hh, ww = h >> (lev + 1), w >> (lev + 1)
        axes[2].plot([ww, ww], [0, 2 * hh], color="white", lw=0.8)
        axes[2].plot([0, 2 * ww], [hh, hh], color="white", lw=0.8)
    axes[2].set_xlim(-0.5, w - 0.5)
    axes[2].set_ylim(h - 0.5, -0.5)
    fig.tight_layout()
    fig.savefig(os.path.join(ASSETS, "coefficient_maps.png"), dpi=90)
    plt.close(fig)


def dwt_levels_table(images):
    fractions = [10, 5, 2, 1, 0.5]
    lines = ["| Зображення | Метод | " + " | ".join(f"{p:g} %" for p in fractions) + " |",
             "|" + "---|" * (len(fractions) + 2)]
    for name, img in images.items():
        values = [f"{psnr(img, compress(img, 'dct', 'keep', p).image):.2f}" for p in fractions]
        lines.append(f"| {name} | DCT 8×8 | " + " | ".join(values) + " |")
        for levels in (1, 2, 3, 4, 5):
            values = [f"{psnr(img, compress(img, 'dwt', 'keep', p, levels).image):.2f}" for p in fractions]
            lines.append(f"| {name} | DWT, {levels} р. | " + " | ".join(values) + " |")
    with open(os.path.join(RESULTS, "dwt_levels.md"), "w", encoding="utf-8") as f:
        f.write("PSNR, дБ, режим «частка найбільших коефіцієнтів»\n\n" + "\n".join(lines) + "\n")


def main():
    os.makedirs(ASSETS, exist_ok=True)
    images = {os.path.splitext(os.path.basename(p))[0]: load_gray(p)
              for p in sorted(glob.glob(os.path.join(HERE, "images", "*.png")))}
    images = dict(sorted(images.items(), key=lambda kv: kv[0] != "camera"))  # camera першим

    keep_rows = run_mode(images, "keep", KEEP_LEVELS, "Збережено, %")
    write_compact_table(keep_rows)
    run_mode(images, "threshold", THRESHOLDS, "Поріг T")
    quant_rows = run_mode(images, "quant", QUANT_STEPS, "Крок Q")
    dwt_levels_table(images)

    plot_psnr_vs_kept(keep_rows)
    plot_rate_distortion(quant_rows)
    for name, img in images.items():
        plot_grid(name, img)
        if name in CROPS:
            plot_crops(name, img)
    plot_coefficient_maps(images["camera"])
    print("Готово:", sorted(os.listdir(RESULTS)), sorted(os.listdir(ASSETS)))


if __name__ == "__main__":
    main()
