"""Генерує ілюстрації для звіту в report_assets/ (без вікна, через ту саму Scene)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pygame  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

import mapping as mp  # noqa: E402
from midi_loader import load_song  # noqa: E402
from scene import Scene, ViewState, draw_shape  # noqa: E402

OUT = ROOT / "report_assets"
SIZE = (1280, 720)
FONT = "/System/Library/Fonts/Supplemental/Arial.ttf"


def font(size: int):
    try:
        return ImageFont.truetype(FONT, size)
    except OSError:
        return ImageFont.load_default()


def frame(scene: Scene, t: float, state: ViewState | None = None) -> Image.Image:
    surf = pygame.Surface(SIZE)
    scene.render(surf, t, state or ViewState())
    return Image.frombytes("RGB", SIZE, pygame.image.tobytes(surf, "RGB"))


def captioned(img: Image.Image, text: str, h: int = 26) -> Image.Image:
    out = Image.new("RGB", (img.width, img.height + h), (20, 22, 40))
    out.paste(img, (0, h))
    ImageDraw.Draw(out).text((8, 5), text, fill=(230, 232, 245), font=font(15))
    return out


def stack(images: list[Image.Image], vertical: bool = True, gap: int = 4) -> Image.Image:
    if vertical:
        w, h = max(i.width for i in images), sum(i.height for i in images) + gap * (len(images) - 1)
    else:
        w, h = sum(i.width for i in images) + gap * (len(images) - 1), max(i.height for i in images)
    out = Image.new("RGB", (w, h), (8, 8, 16))
    pos = 0
    for i in images:
        out.paste(i, (0, pos) if vertical else (pos, 0))
        pos += (i.height if vertical else i.width) + gap
    return out


def main() -> None:
    pygame.init()
    OUT.mkdir(exist_ok=True)
    demo = Scene(load_song(ROOT / "midi" / "demo_song.mid"), SIZE)
    test = Scene(load_song(ROOT / "midi" / "mapping_test.mid"), SIZE)
    stage = demo.L.stage

    # 1. Повний інтерфейс, фокус на доріжці, довідка
    frame(demo, 22.4).save(OUT / "ui_main.png")
    frame(demo, 29.9, ViewState(focus=0)).save(OUT / "ui_focus_lead.png")
    frame(demo, 12.3, ViewState(help=True)).save(OUT / "ui_help.png")
    frame(demo, 26.0, ViewState(hidden={1, 2})).save(OUT / "ui_hidden_tracks.png")

    # 2. Життєвий цикл однієї ноти (E4, 4 долі, 11.37–12.97 с у mapping_test.mid)
    note = next(n for n in test.song.voices[0].notes if n.pitch == 64 and n.duration > 1.5)
    y = int(test.note_y(note.pitch))
    box = (stage.left, y - 60, stage.right, y + 60)
    steps = [
        (note.start - 0.05, "до note_on: нового об'єкта ще немає (ліворуч — попередня, коротша нота E4)"),
        (note.start + 0.06, "note_on: поява — об'єкт «вистрибує» (pop) і розходиться кільце"),
        (note.start + 0.6, "нота звучить: об'єкт рухається ліворуч, «хвіст» росте від лінії note_on"),
        (note.end - 0.02, "перед note_off: довжина хвоста = тривалість ноти × швидкість сцени"),
        (note.end + 0.5, f"після note_off: згасання й зменшення ({mp.release_time(note.duration):.1f} с для цієї ноти)"),
        (note.end + 1.6, "майже зникла"),
    ]
    tiles = [captioned(frame(test, t, ViewState(hidden={1, 2})).crop(box), f"t = {t:5.2f} с — {txt}")
             for t, txt in steps]
    stack(tiles).save(OUT / "note_lifecycle.png")

    # 3. Висота -> Y, velocity -> розмір (висхідна гама з crescendo)
    scale_frames = [captioned(frame(test, t, ViewState(hidden={1, 2})).crop(
        (stage.left, stage.top, stage.right, stage.bottom)).resize((466, 246)), f"t = {t:.2f} с")
        for t in (2.4, 4.8, 7.2)]
    stack(scale_frames, vertical=False).save(OUT / "pitch_velocity_scale.png")

    # 4. Ефекти ударних
    effects = [(0.667 + 0.08, "kick → пульсація фону + хвиля"), (3.333 + 0.2, "snare → вибух частинок"),
               (5.333 + 0.06, "hi-hat → іскри вгорі"), (8.0 + 0.12, "crash → спалах"),
               (9.333 + 0.15, "tom → кільця")]
    tiles = [captioned(frame(test, t, ViewState(hidden={0, 1})).crop(
        (stage.left, stage.top, stage.right, stage.bottom)).resize((466, 246)), txt) for t, txt in effects]
    row1, row2 = stack(tiles[:3], vertical=False), stack(tiles[3:], vertical=False)
    stack([row1, row2]).save(OUT / "drum_effects.png")

    # 5. Таблиця форм: інструмент (родина GM) -> форма; velocity -> розмір і яскравість
    families = [("Piano 0", 0), ("Chrom. Perc 10", 10), ("Organ 16", 16), ("Guitar 24", 24),
                ("Bass 38", 38), ("Strings 48", 48), ("Synth Pad 89", 89)]
    vels = [20, 60, 100, 127]
    surf = pygame.Surface((180 + 110 * len(vels), 60 + 76 * len(families)))
    surf.fill((14, 16, 32))
    for j, (name, prog) in enumerate(families):
        for i, v in enumerate(vels):
            color = mp.note_color(mp.track_color(j), 70, 40, 100, mp.velocity_to_brightness(v))
            draw_shape(surf, mp.program_to_shape(prog), 230 + 110 * i, 90 + 76 * j,
                       mp.velocity_to_size(v), color)
    img = Image.frombytes("RGB", surf.get_size(), pygame.image.tobytes(surf, "RGB"))
    d = ImageDraw.Draw(img)
    for i, v in enumerate(vels):
        d.text((205 + 110 * i, 18), f"vel {v}", fill=(230, 232, 245), font=font(16))
    for j, (name, prog) in enumerate(families):
        d.text((14, 80 + 76 * j), f"{name}\n{mp.program_to_shape(prog)}", fill=(230, 232, 245), font=font(14))
    img.save(OUT / "shapes_velocity.png")

    # 6. Журнал подій поруч зі сценою (крупно)
    full = frame(demo, 22.4)
    full.crop((demo.L.panel.left, demo.L.panel.top + 160, demo.L.panel.right, demo.L.panel.bottom)).save(
        OUT / "event_log.png")
    print("Готово:", sorted(p.name for p in OUT.iterdir()))


if __name__ == "__main__":
    main()
