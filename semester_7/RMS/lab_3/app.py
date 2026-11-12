"""Інтерактивне порівняння стиснення: Original | DCT | DWT.

Запуск:
    python app.py                         # усі зображення з images/ та images/extra/ (кнопка «Наступне»)
    python app.py photo.jpg               # будь-яке своє зображення (стане сірим)
    python app.py --mode quant --level 25 # стартовий режим і рівень
    python app.py --save shot.png         # без вікна: зберегти знімок у PNG
"""
import argparse
import glob
import os

import numpy as np

from compressor import compress, load_gray
from metrics import psnr, ssim

HERE = os.path.dirname(os.path.abspath(__file__))

MODE_LABELS = {
    "keep": "Частка найбільших коеф.",
    "threshold": "Поріг |c| < T → 0",
    "quant": "Квантування з кроком Q",
}
# Для режиму keep повзунок працює в логарифмічній шкалі: значення = log10(%).
SLIDERS = {
    "keep": ("Збережено, %", -1.0, 2.0),
    "threshold": ("Поріг T", 0.0, 300.0),
    "quant": ("Крок Q", 1.0, 200.0),
}
DEFAULT_PARAMS = {"keep": 5.0, "threshold": 40.0, "quant": 30.0}
ERROR_MAX = 40  # шкала карти помилок, рівні яскравості


def slider_to_param(mode, value):
    return 10 ** value if mode == "keep" else value


def param_to_slider(mode, param):
    return np.log10(param) if mode == "keep" else param


def format_param(mode, param):
    return f"{param:.3g} %" if mode == "keep" else f"{param:.1f}"


class App:
    def __init__(self, plt, paths, mode, param, levels):
        from matplotlib.widgets import Button, RadioButtons

        self.plt = plt
        self.paths, self.index = paths, 0
        self.mode, self.levels = mode, levels
        self.params = dict(DEFAULT_PARAMS)
        if param is not None:
            self.params[mode] = param

        self.fig = plt.figure(figsize=(14, 10))
        if self.fig.canvas.manager is not None:
            self.fig.canvas.manager.set_window_title("ЛР3: стиснення DCT / DWT")
        grid = self.fig.add_gridspec(2, 3, left=0.02, right=0.98, top=0.95, bottom=0.17,
                                     hspace=0.28, wspace=0.06)
        self.axes = [[self.fig.add_subplot(grid[r, c]) for c in range(3)] for r in range(2)]
        for row in self.axes:
            for ax in row:
                ax.set_xticks([])
                ax.set_yticks([])
        self.info_ax = self.axes[1][0]
        self.info_ax.axis("off")

        modes = list(MODE_LABELS)
        self.radio = RadioButtons(self.fig.add_axes([0.02, 0.02, 0.2, 0.11]),
                                  [MODE_LABELS[m] for m in modes], active=modes.index(mode))
        self.radio.on_clicked(self.on_mode)

        self.slider_ax = self.fig.add_axes([0.32, 0.065, 0.42, 0.035])
        self.slider = None
        self.make_slider()

        self.button = Button(self.fig.add_axes([0.82, 0.045, 0.15, 0.07]), "Наступне зображення")
        self.button.on_clicked(self.on_next)

        self.load_image()

    # --- елементи керування -------------------------------------------------
    def make_slider(self):
        from matplotlib.widgets import Slider

        if self.slider is not None:
            self.slider.disconnect_events()
            self.slider_ax.clear()
        label, vmin, vmax = SLIDERS[self.mode]
        self.slider = Slider(self.slider_ax, label, vmin, vmax,
                             valinit=param_to_slider(self.mode, self.params[self.mode]))
        self.slider.valtext.set_text(format_param(self.mode, self.params[self.mode]))
        self.slider.on_changed(self.on_slider)

    def on_slider(self, value):
        self.params[self.mode] = slider_to_param(self.mode, value)
        self.slider.valtext.set_text(format_param(self.mode, self.params[self.mode]))
        self.update()

    def on_mode(self, label):
        self.mode = next(m for m, text in MODE_LABELS.items() if text == label)
        self.make_slider()
        self.update()

    def on_next(self, _event):
        self.index = (self.index + 1) % len(self.paths)
        self.load_image()

    # --- відображення -------------------------------------------------------
    def load_image(self):
        self.img = load_gray(self.paths[self.index])
        (ax_orig, ax_dct, ax_dwt), (_, ax_err_dct, ax_err_dwt) = self.axes
        for ax in (ax_orig, ax_dct, ax_dwt, ax_err_dct, ax_err_dwt):
            for artist in list(ax.images):
                artist.remove()
        gray = dict(cmap="gray", vmin=0, vmax=255, interpolation="nearest")
        err = dict(cmap="magma", vmin=0, vmax=ERROR_MAX, interpolation="nearest")
        ax_orig.imshow(self.img, **gray)
        self.im_dct = ax_dct.imshow(self.img, **gray)
        self.im_dwt = ax_dwt.imshow(self.img, **gray)
        self.im_err_dct = ax_err_dct.imshow(np.zeros_like(self.img), **err)
        self.im_err_dwt = ax_err_dwt.imshow(np.zeros_like(self.img), **err)
        h, w = self.img.shape
        ax_orig.set_title(f"Original — {os.path.basename(self.paths[self.index])} ({w}×{h})")
        ax_err_dct.set_title(f"|Original − DCT|  (0…{ERROR_MAX}+)")
        ax_err_dwt.set_title(f"|Original − DWT|  (0…{ERROR_MAX}+)")
        self.update()

    def update(self):
        param = self.params[self.mode]
        dct_res = compress(self.img, "dct", self.mode, param)
        dwt_res = compress(self.img, "dwt", self.mode, param, self.levels)

        rows = []
        for name, res, im, im_err, ax in (
            ("DCT 8×8", dct_res, self.im_dct, self.im_err_dct, self.axes[0][1]),
            (f"DWT Хаара, {levels_word(self.levels)}", dwt_res, self.im_dwt, self.im_err_dwt, self.axes[0][2]),
        ):
            p, s = psnr(self.img, res.image), ssim(self.img, res.image)
            im.set_data(res.image)
            im_err.set_data(np.abs(self.img.astype(int) - res.image.astype(int)))
            ax.set_title(f"{name} — PSNR {p:.2f} дБ\n"
                         f"збережено {res.kept} з {res.total} ({100 * res.kept_fraction:.2f} %)")
            rows.append((p, s, res))

        (p1, s1, r1), (p2, s2, r2) = rows
        self.info_ax.clear()
        self.info_ax.axis("off")
        text = (
            f"Режим: {MODE_LABELS[self.mode]}\n"
            f"Параметр: {format_param(self.mode, param)}\n\n"
            f"{'':<16}{'DCT':>10}{'DWT':>10}\n"
            f"{'PSNR, дБ':<16}{p1:>10.2f}{p2:>10.2f}\n"
            f"{'SSIM':<16}{s1:>10.3f}{s2:>10.3f}\n"
            f"{'Ненульових':<16}{r1.kept:>10}{r2.kept:>10}\n"
            f"{'Частка, %':<16}{100 * r1.kept_fraction:>10.2f}{100 * r2.kept_fraction:>10.2f}\n"
            f"{'CR = N/Nnz':<16}{r1.ratio_nonzero:>10.1f}{r2.ratio_nonzero:>10.1f}\n"
            f"{'біт/піксель*':<16}{r1.bpp:>10.3f}{r2.bpp:>10.3f}\n\n"
            "* оцінка за ентропією Шеннона\n"
            "  округлених коефіцієнтів"
        )
        self.info_ax.text(0.02, 0.98, text, va="top", ha="left", family="DejaVu Sans Mono", fontsize=11,
                          transform=self.info_ax.transAxes)
        self.fig.canvas.draw_idle()



def levels_word(n):
    """«1 рівень», «3 рівні», «5 рівнів» — українська форма множини."""
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} рівень"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return f"{n} рівні"
    return f"{n} рівнів"

def main():
    parser = argparse.ArgumentParser(description="Порівняння стиснення DCT і DWT")
    parser.add_argument("images", nargs="*", help="шляхи до зображень (за замовч. images/*.png і images/extra/*.png)")
    parser.add_argument("--mode", choices=list(MODE_LABELS), default="keep", help="режим стиснення")
    parser.add_argument("--level", type=float, help="рівень: %% для keep, T для threshold, Q для quant")
    parser.add_argument("--levels", type=int, default=3, help="кількість рівнів DWT (за замовч. 3)")
    parser.add_argument("--save", help="зберегти знімок вікна у файл і вийти")
    args = parser.parse_args()

    main_imgs = sorted(glob.glob(os.path.join(HERE, "images", "*.png")),
                       key=lambda p: os.path.basename(p) != "camera.png")   # camera першим, як у звіті
    paths = args.images or (main_imgs + sorted(glob.glob(os.path.join(HERE, "images", "extra", "*.png"))))
    readable = []
    for path in paths:                      # некоректний файл пропускаємо з поясненням, а не падаємо
        try:
            load_gray(path)
            readable.append(path)
        except (OSError, ValueError) as exc:
            print(f"Пропущено {path}: не вдалося відкрити як зображення ({exc.__class__.__name__})")
    if not readable:
        parser.error("немає зображень: вкажіть шлях або запустіть prepare_images.py")
    paths = readable

    import matplotlib
    if args.save:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    app = App(plt, paths, args.mode, args.level, args.levels)
    if args.save:
        app.fig.savefig(args.save, dpi=100)
        print("Збережено", args.save)
    else:
        plt.show()


if __name__ == "__main__":
    main()
