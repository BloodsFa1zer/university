"""Готує тестові зображення.

images/        — два зображення 512×512 у відтінках сірого, на них рахуються експерименти:
  camera    — skimage.data.camera() (вільна ліцензія, CC0);
  astronaut — skimage.data.astronaut() (фото NASA, суспільне надбання), переведене в сірий.

images/extra/  — додаткові зображення різного типу для демонстрації в app.py:
  1_hike_frame    — кадр із власного відео (960×540: висота не кратна 8, перевіряє доповнення країв);
  2_cat_color     — skimage.data.chelsea(), кольорове 451×300: програма сама переводить у сірий;
  3_sharp_edges   — синтетичне: шахівниця, тонкі лінії, текст — різкі перепади яскравості;
  4_smooth        — синтетичне: плавні градієнти без дрібних деталей.

Запуск:  python prepare_images.py [шлях_до_власного_відео]
Готові PNG уже лежать у папках, скрипт потрібен лише для їх відтворення.
"""
import os
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from skimage import data

HERE = os.path.dirname(os.path.abspath(__file__))
FONT = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"


def sharp_edges(size=512):
    img = Image.new("L", (size, size), 235)
    d = ImageDraw.Draw(img)
    for y in range(0, 256, 32):                              # шахівниця з клітинкою 32 px
        for x in range(0, 256, 32):
            if (x // 32 + y // 32) % 2:
                d.rectangle([x, y, x + 31, y + 31], fill=20)
    for i, width in enumerate((1, 2, 3, 5)):                 # похилі лінії різної товщини
        d.line([(280, 24 + i * 60), (500, 70 + i * 60)], fill=10, width=width)
    try:
        font = ImageFont.truetype(FONT, 56)
    except OSError:
        font = ImageFont.load_default()
    d.text((24, 290), "DCT vs DWT", font=font, fill=0)
    d.text((24, 380), "Хаар 8×8", font=font, fill=70)
    d.ellipse([310, 300, 490, 480], outline=0, width=6)
    return img


def smooth(size=512):
    y, x = np.mgrid[0:size, 0:size] / size
    v = (128 + 80 * np.sin(2.2 * x + 1.3 * y) * np.cos(1.7 * y)
         + 40 * np.exp(-((x - 0.65) ** 2 + (y - 0.4) ** 2) / 0.02))
    return Image.fromarray(np.clip(v, 0, 255).astype(np.uint8))


def video_frame(video, t=8.0):
    import imageio_ffmpeg
    res = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-loglevel", "error", "-ss", str(t), "-i", video,
                          "-frames:v", "1", "-vf", "scale=960:540", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True)
    return Image.frombytes("RGB", (960, 540), res.stdout)


def main():
    out_dir = os.path.join(HERE, "images")
    extra = os.path.join(out_dir, "extra")
    os.makedirs(extra, exist_ok=True)
    Image.fromarray(data.camera()).save(os.path.join(out_dir, "camera.png"))
    Image.fromarray(data.astronaut()).convert("L").save(os.path.join(out_dir, "astronaut.png"))
    if len(sys.argv) > 1:
        video_frame(sys.argv[1]).save(os.path.join(extra, "1_hike_frame.png"))
    Image.fromarray(data.chelsea()).save(os.path.join(extra, "2_cat_color.png"))
    sharp_edges().save(os.path.join(extra, "3_sharp_edges.png"))
    smooth().save(os.path.join(extra, "4_smooth.png"))
    print("Збережено:", sorted(os.listdir(out_dir)), sorted(os.listdir(extra)))


if __name__ == "__main__":
    main()
