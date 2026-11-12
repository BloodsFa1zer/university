"""Простий власний синтезатор: перетворює ноти Song у звук (numpy).

Мелодичні інструменти — адитивний синтез (сума гармонік-синусоїд) з ADSR-обвідною;
тембр залежить від родини інструмента GM. Ударні — шум і синусоїди з
експоненційним затуханням. Кожна доріжка рендериться окремо (stem), щоб її
можна було вимкнути під час відтворення.
"""
from __future__ import annotations

import wave

import numpy as np

from midi_loader import Song, Voice

SR = 44_100
TAIL = 1.5   # секунд після останньої ноти для затухання звуку і анімації

# Параметри тембрів: гармоніки (множник частоти, амплітуда), ADSR, затухання гармонік
TIMBRES = {
    "pluck": dict(partials=[(k, 1 / k ** 1.3) for k in range(1, 9)], a=0.004, d=0.1, s=1.0, r=0.25,
                  decay=1.6, hdecay=0.7, gain=0.55),
    "bell": dict(partials=[(1, 1), (2, 0.4), (3.01, 0.25), (4.2, 0.12), (5.43, 0.08)],
                 a=0.002, d=0.1, s=1.0, r=0.6, decay=2.5, hdecay=1.2, gain=0.28),
    "organ": dict(partials=[(1, 1), (2, 0.5), (3, 0.3), (4, 0.2), (6, 0.1)],
                  a=0.015, d=0.05, s=1.0, r=0.08, decay=0.0, hdecay=0.0, gain=0.35),
    "bass": dict(partials=[(k, 1 / k) for k in range(1, 11)], a=0.005, d=0.15, s=0.85, r=0.08,
                 decay=0.4, hdecay=0.9, gain=0.42),
    "pad": dict(partials=[(k, 1 / k) for k in range(1, 11)], a=0.35, d=0.3, s=0.8, r=0.7,
                decay=0.0, hdecay=0.15, gain=0.16, detune=True),
    "lead": dict(partials=[(k, 1 / k) for k in range(1, 14, 2)], a=0.01, d=0.1, s=0.8, r=0.18,
                 decay=0.1, hdecay=0.05, gain=0.42, vibrato=True),
}
# Родина GM (program // 8) -> тембр
FAMILY_TIMBRE = ["pluck", "bell", "organ", "pluck", "bass", "pad", "pad", "lead",
                 "lead", "organ", "lead", "pad", "bell", "pluck", "bell", "bell"]
ECHO_TIMBRES = {"bell", "pad", "lead"}


def midi_to_freq(pitch: float) -> float:
    """MIDI-номер -> частота, Гц (A4 = 69 = 440 Гц, 12 півтонів на октаву)."""
    return 440.0 * 2 ** ((pitch - 69) / 12)


def timbre_of(program: int) -> str:
    return FAMILY_TIMBRE[(program % 128) // 8]


def adsr(n: int, n_hold: int, a: float, d: float, s: float, r: float) -> np.ndarray:
    """ADSR-обвідна: Attack (наростання), Decay (спад), Sustain (рівень), Release (згасання)."""
    t = np.arange(n) / SR
    env = np.full(n, s)
    if a > 0:
        env = np.where(t < a, t / a, env)
    dec = (t >= a) & (t < a + d)
    env[dec] = 1 - (1 - s) * (t[dec] - a) / d
    hold_t = n_hold / SR
    level = env[min(n_hold, n - 1)] if n_hold < n else env[-1]
    rel = t >= hold_t
    env[rel] = level * np.clip(1 - (t[rel] - hold_t) / r, 0, 1)
    return env


def render_note(pitch: int, velocity: int, duration: float, program: int) -> np.ndarray:
    p = TIMBRES[timbre_of(program)]
    f = midi_to_freq(pitch)
    n_hold = max(int(duration * SR), 1)
    n = n_hold + int(p["r"] * SR)
    t = np.arange(n) / SR
    phase = 2 * np.pi * f * t
    if p.get("vibrato"):
        # вібрато 5.5 Гц глибиною 0.4%, вступає плавно
        depth = 0.004 * np.clip(t / 0.3, 0, 1)
        phase += 2 * np.pi * f * depth * (1 - np.cos(2 * np.pi * 5.5 * t)) / (2 * np.pi * 5.5)
    sig = np.zeros(n)
    for ratio, amp in p["partials"]:
        if ratio * f >= 0.45 * SR:          # не генеруємо гармоніки вище частоти Найквіста
            break
        damp = np.exp(-t * (p["decay"] + p["hdecay"] * ratio)) if p["decay"] or p["hdecay"] else 1.0
        sig += amp * np.sin(ratio * phase) * damp
        if p.get("detune"):
            sig += amp * np.sin(ratio * phase * 2 ** (8 / 1200)) * damp   # +8 центів — "хорус"
    env = adsr(n, n_hold, p["a"], p["d"], p["s"], p["r"])
    return sig * env * p["gain"] * (velocity / 127) ** 1.3


def render_drum(pitch: int, velocity: int, seed: int) -> np.ndarray:
    from mapping import drum_kind
    kind = drum_kind(pitch)
    rng = np.random.default_rng(seed)
    length = {"kick": 0.5, "snare": 0.3, "hihat": 0.08, "open_hat": 0.45,
              "tom": 0.5, "crash": 1.8, "perc": 0.15}[kind]
    n = int(length * SR)
    t = np.arange(n) / SR
    noise = rng.uniform(-1, 1, n)
    hp = np.diff(noise, prepend=0.0) * 0.5                   # грубий фільтр високих частот
    if kind == "kick":
        freq = 45 + 95 * np.exp(-t * 30)                    # частота падає 140 -> 45 Гц
        sig = np.sin(2 * np.pi * np.cumsum(freq) / SR) * np.exp(-t * 7)
        sig[: int(0.003 * SR)] += noise[: int(0.003 * SR)] * 0.5
        gain = 1.0
    elif kind == "snare":
        sig = hp * np.exp(-t * 16) * 0.9 + np.sin(2 * np.pi * 185 * t) * np.exp(-t * 25) * 0.5
        gain = 0.55
    elif kind in ("hihat", "open_hat"):
        sig = np.diff(hp, prepend=0.0) * np.exp(-t * (60 if kind == "hihat" else 7))
        gain = 0.3
    elif kind == "tom":
        base = 80 + (pitch - 41) * 14
        freq = base * (1 + 0.5 * np.exp(-t * 20))
        sig = np.sin(2 * np.pi * np.cumsum(freq) / SR) * np.exp(-t * 6)
        gain = 0.7
    elif kind == "crash":
        sig = np.diff(hp, prepend=0.0) * np.exp(-t * 2.2)
        gain = 0.3
    else:
        sig = hp * np.exp(-t * 30)
        gain = 0.35
    return sig * gain * (velocity / 127) ** 1.2


def _echo(x: np.ndarray, delay: float = 0.28, feedback: float = 0.3, taps: int = 3) -> np.ndarray:
    """Просте відлуння: додаємо кілька затриманих і тихіших копій сигналу."""
    out = x.copy()
    d = int(delay * SR)
    for k in range(1, taps + 1):
        if d * k >= len(x):
            break
        out[d * k:] += x[: len(x) - d * k] * feedback ** k
    return out


def total_samples(song: Song) -> int:
    return int(round((song.duration + TAIL) * SR))


def render_voice(voice: Voice, n_total: int) -> np.ndarray:
    stem = np.zeros(n_total, dtype=np.float64)
    for i, note in enumerate(voice.notes):
        if voice.is_drum:
            wave_ = render_drum(note.pitch, note.velocity, seed=i * 131 + note.pitch)
        else:
            wave_ = render_note(note.pitch, note.velocity, note.duration, voice.program)
        start = int(note.start * SR)
        end = min(start + len(wave_), n_total)
        if start < n_total:
            stem[start:end] += wave_[: end - start]
    if not voice.is_drum and timbre_of(voice.program) in ECHO_TIMBRES:
        stem = _echo(stem)
    return stem.astype(np.float32)


def render_stems(song: Song) -> list[np.ndarray]:
    """Окремий моно-сигнал для кожної доріжки."""
    n = total_samples(song)
    return [render_voice(v, n) for v in song.voices]


def default_pans(song: Song) -> list[float]:
    """Панорама -1 (ліво) .. 1 (право): ударні, бас і соло по центру, решта — почергово."""
    pans, side = [], -1
    for v in song.voices:
        if v.is_drum or timbre_of(v.program) in ("bass", "lead"):
            pans.append(0.0)
        else:
            pans.append(0.35 * side)
            side = -side
    return pans


def mix(stems: list[np.ndarray], pans: list[float], muted: set[int] = frozenset(),
        master: float = 1.0) -> np.ndarray:
    """Зведення доріжок у стерео (n, 2) з рівнопотужним панорамуванням."""
    n = len(stems[0]) if stems else 0
    out = np.zeros((n, 2), dtype=np.float32)
    for i, (stem, pan) in enumerate(zip(stems, pans)):
        if i in muted:
            continue
        angle = (pan + 1) * np.pi / 4
        out[:, 0] += stem * np.cos(angle)
        out[:, 1] += stem * np.sin(angle)
    return out * master


def master_gain(stems: list[np.ndarray], pans: list[float]) -> float:
    """Множник гучності, щоб пік повного міксу був -1 dBFS."""
    peak = float(np.max(np.abs(mix(stems, pans)))) if stems else 0.0
    return 0.89 / peak if peak > 0 else 1.0


def to_int16(stereo: np.ndarray) -> np.ndarray:
    return (np.clip(stereo, -1, 1) * 32767).astype(np.int16)


def render_song(song: Song) -> np.ndarray:
    """Повний стерео-мікс пісні (float32, нормалізований)."""
    stems = render_stems(song)
    pans = default_pans(song)
    return mix(stems, pans, master=master_gain(stems, pans))


def write_wav(path: str, stereo: np.ndarray) -> None:
    data = to_int16(stereo)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data.tobytes())
