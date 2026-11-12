"""Правила відображення MIDI -> параметри анімації.

Усі правила зібрано тут як прості функції, щоб їх було легко пояснити й протестувати:
  доріжка          -> колір (палітра)
  програма (GM)    -> форма об'єкта
  висота ноти      -> координата Y і відтінок кольору
  velocity         -> розмір і яскравість
  тривалість ноти  -> довжина "хвоста" і час згасання
  note_on/note_off -> поява / зникнення об'єкта
  ударні (канал 10)-> ефекти: пульсація, вибух частинок, іскри, спалах
  темп (BPM)       -> швидкість руху сцени
"""
from __future__ import annotations

import colorsys

PALETTE = [
    (255, 94, 120),   # рожево-червоний
    (64, 170, 255),   # блакитний
    (255, 200, 70),   # жовтий
    (80, 220, 170),   # бірюзовий
    (180, 120, 255),  # фіолетовий
    (255, 150, 60),   # помаранчевий
    (120, 230, 90),   # зелений
    (240, 240, 240),  # білий
    (255, 120, 220),  # малиновий
]

# 16 родин інструментів General MIDI (program // 8) і форма для кожної
FAMILY_NAMES = [
    "Piano", "Chromatic Perc", "Organ", "Guitar", "Bass", "Strings", "Ensemble", "Brass",
    "Reed", "Pipe", "Synth Lead", "Synth Pad", "Synth FX", "Ethnic", "Percussive", "Sound FX",
]
FAMILY_SHAPES = [
    "circle", "star", "square", "triangle", "diamond", "hexagon", "hexagon", "triangle",
    "triangle", "circle", "circle", "hexagon", "star", "triangle", "star", "star",
]

# Ударні General MIDI: номер ноти -> вид інструмента
DRUM_KINDS = {
    35: "kick", 36: "kick",
    37: "snare", 38: "snare", 39: "snare", 40: "snare",
    42: "hihat", 44: "hihat", 46: "open_hat",
    41: "tom", 43: "tom", 45: "tom", 47: "tom", 48: "tom", 50: "tom",
    49: "crash", 52: "crash", 55: "crash", 57: "crash", 51: "hihat", 59: "hihat",
}
DRUM_NAMES = {"kick": "Kick", "snare": "Snare", "hihat": "Hi-hat", "open_hat": "Open hat",
              "tom": "Tom", "crash": "Crash", "perc": "Perc"}
# Вид ударного -> візуальний ефект
DRUM_EFFECTS = {"kick": "pulse", "snare": "burst", "hihat": "sparkle", "open_hat": "sparkle",
                "tom": "ring", "crash": "flash", "perc": "sparkle"}
# Скільки секунд живе ефект
DRUM_LIFETIME = {"kick": 0.6, "snare": 0.8, "hihat": 0.35, "open_hat": 0.9,
                 "tom": 0.7, "crash": 1.5, "perc": 0.4}

MIN_RADIUS, MAX_RADIUS = 5.0, 30.0


def track_color(index: int) -> tuple[int, int, int]:
    """Колір доріжки — з палітри за її номером."""
    return PALETTE[index % len(PALETTE)]


def program_family(program: int) -> str:
    return FAMILY_NAMES[(program % 128) // 8]


def program_to_shape(program: int) -> str:
    """Інструмент (номер програми GM) -> форма об'єкта."""
    return FAMILY_SHAPES[(program % 128) // 8]


def pitch_to_y(pitch: float, lo: float, hi: float, top: float, bottom: float) -> float:
    """Висота ноти -> Y: вища нота — вище на екрані (менший Y)."""
    if hi <= lo:
        return (top + bottom) / 2
    k = (pitch - lo) / (hi - lo)
    k = min(max(k, 0.0), 1.0)
    return bottom - k * (bottom - top)


def velocity_to_size(velocity: int) -> float:
    """Velocity (сила натискання) -> радіус об'єкта у пікселях."""
    k = min(max(velocity, 0), 127) / 127
    return MIN_RADIUS + (MAX_RADIUS - MIN_RADIUS) * k ** 1.2


def velocity_to_brightness(velocity: int) -> float:
    """Velocity -> яскравість кольору 0.35..1.0 (множник RGB; прозорість від velocity не залежить)."""
    return 0.35 + 0.65 * min(max(velocity, 0), 127) / 127


def note_color(base: tuple[int, int, int], pitch: int, lo: int, hi: int,
               brightness: float = 1.0) -> tuple[int, int, int]:
    """Колір ноти: колір доріжки, відтінок якого зсувається з висотою (±18°)."""
    h, l, s = colorsys.rgb_to_hls(*(c / 255 for c in base))
    k = 0.5 if hi <= lo else (pitch - lo) / (hi - lo)
    h = (h + (k - 0.5) * 0.1) % 1.0
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return tuple(int(min(255, c * 255 * brightness)) for c in (r, g, b))


def release_time(duration: float) -> float:
    """Тривалість ноти -> час згасання після note_off (довгі ноти гаснуть повільніше)."""
    return min(max(0.8 + 0.8 * duration, 0.8), 2.5)


def tempo_to_scroll_speed(bpm: float) -> float:
    """Темп -> швидкість руху сцени, пікселів за секунду (120 BPM -> 240 px/s)."""
    return 2.0 * bpm


def drum_kind(pitch: int) -> str:
    return DRUM_KINDS.get(pitch, "perc")


def pop_scale(age: float) -> float:
    """Анімація появи (note_on): об'єкт "вистрибує" з 0 до 1.25 і осідає до 1.0."""
    if age <= 0:
        return 0.0
    if age < 0.08:
        return 1.25 * age / 0.08
    if age < 0.2:
        return 1.25 - 0.25 * (age - 0.08) / 0.12
    return 1.0
