"""Сцена анімації: малює кадр для довільного моменту часу t.

Сцена "без пам'яті": кадр повністю визначається часом t і даними MIDI, тому
пауза, перемотування і експорт у відео працюють однаково та детерміновано.

Частини екрана: верхня панель (час, темп, прогрес), сцена (анімовані об'єкти),
права панель (легенда доріжок + журнал подій MIDI -> анімація), піано-рол унизу.
"""
from __future__ import annotations

import bisect
import math
import random
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pygame
import pygame.gfxdraw

import mapping as mp
from midi_loader import Song, note_name
from synth import TAIL

BG = (6, 7, 16)
PANEL_BG = (16, 18, 34)
TEXT = (225, 228, 240)
MUTED = (120, 125, 150)
FADE_MAX = 2.5           # максимальне значення mapping.release_time
LABEL_MIN_DURATION = 0.25
ROLL_BEFORE, ROLL_AFTER = 2.5, 7.5   # вікно піано-ролу, секунд до/після поточного моменту


@dataclass
class ViewState:
    """Те, що змінює користувач: видимість доріжок, фокус, підписи тощо."""
    hidden: set[int] = field(default_factory=set)
    focus: int | None = None
    labels: bool = True
    playing: bool = True
    help: bool = False
    audio: bool = True
    message: str = ""
    message_error: bool = False
    warnings: list[str] = field(default_factory=list)


@dataclass
class NoteSprite:
    voice: int
    pitch: int
    velocity: int
    x: float
    tail_x: float
    y: float
    r: float
    color: tuple[int, int, int]
    alpha: int
    age: float
    duration: float
    held: bool


def _font(names: str, size: int, bold: bool = False) -> pygame.font.Font:
    path = pygame.font.match_font(names, bold=bold)
    return pygame.font.Font(path, size) if path else pygame.font.Font(None, int(size * 1.3))


def _mix(c1, c2, k: float) -> tuple[int, int, int]:
    return tuple(int(a + (b - a) * k) for a, b in zip(c1, c2))


def shape_points(shape: str, cx: float, cy: float, r: float) -> list[tuple[int, int]]:
    """Вершини багатокутника для форми об'єкта."""
    if shape == "square":
        k = r * 0.85
        return [(cx - k, cy - k), (cx + k, cy - k), (cx + k, cy + k), (cx - k, cy + k)]
    if shape == "diamond":
        return [(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)]
    if shape == "triangle":
        angles, radii = [-90, 30, 150], [r * 1.1] * 3
    elif shape == "hexagon":
        angles, radii = [i * 60 for i in range(6)], [r] * 6
    elif shape == "star":
        angles = [-90 + i * 36 for i in range(10)]
        radii = [r * 1.15 if i % 2 == 0 else r * 0.5 for i in range(10)]
    else:  # коло апроксимуємо 20-кутником (для багатокутних функцій)
        angles, radii = [i * 18 for i in range(20)], [r] * 20
    return [(cx + rr * math.cos(math.radians(a)), cy + rr * math.sin(math.radians(a)))
            for a, rr in zip(angles, radii)]


def draw_shape(surf, shape: str, cx: float, cy: float, r: float, color, alpha: int = 255,
               outline=None) -> None:
    """Малює форму з прозорістю (gfxdraw змішує кольори з урахуванням alpha)."""
    if r < 1 or alpha <= 0:
        return
    rgba = (*color, max(0, min(255, alpha)))
    if shape == "circle":
        pygame.gfxdraw.filled_circle(surf, int(cx), int(cy), int(r), rgba)
        pygame.gfxdraw.aacircle(surf, int(cx), int(cy), int(r), (*(outline or color), rgba[3]))
    else:
        pts = [(int(x), int(y)) for x, y in shape_points(shape, cx, cy, r)]
        pygame.gfxdraw.filled_polygon(surf, pts, rgba)
        pygame.gfxdraw.aapolygon(surf, pts, (*(outline or color), rgba[3]))


def draw_ring(surf, cx: float, cy: float, r: float, color, alpha: int, width: int = 2) -> None:
    for k in range(width):
        if r - k > 1:
            pygame.gfxdraw.aacircle(surf, int(cx), int(cy), int(r - k), (*color, max(0, min(255, alpha))))


class Layout:
    def __init__(self, w: int, h: int):
        self.w, self.h = w, h
        self.top = pygame.Rect(0, 0, w, 40)
        panel_w = int(w * 0.26)
        stage_h = int(h * 0.745) - 44
        self.stage = pygame.Rect(0, 44, w - panel_w - 12, stage_h)
        self.panel = pygame.Rect(self.stage.right + 6, 44, panel_w + 6, stage_h)
        self.roll = pygame.Rect(0, self.stage.bottom + 8, w, h - self.stage.bottom - 14)
        self.spawn_x = self.stage.x + int(self.stage.w * 0.8)   # тут з'являються нові ноти


class Scene:
    def __init__(self, song: Song, size: tuple[int, int]):
        self.song = song
        self.L = Layout(*size)
        self.title = Path(song.path).name
        self.f_ui = _font("helveticaneue,arial,dejavusans", 15)
        self.f_bold = _font("helveticaneue,arial,dejavusans", 16, bold=True)
        self.f_small = _font("helveticaneue,arial,dejavusans", 12)
        self.f_mono = _font("menlo,dejavusansmono,consolas,couriernew", 12)
        self.f_label = _font("menlo,dejavusansmono,consolas,couriernew", 11)
        self._text_cache: dict = {}
        self._glow_cache: dict = {}
        self._glow_base = self._make_glow(128)
        self._bg = self._make_gradient(self.L.stage.size, (10, 12, 30), (30, 14, 50))
        self._precompute()

    # ------------------------------------------------------------------ підготовка
    def _precompute(self) -> None:
        song, L = self.song, self.L
        pitches = [n.pitch for v in song.voices if not v.is_drum for n in v.notes]
        self.lo, self.hi = (min(pitches) - 2, max(pitches) + 2) if pitches else (48, 84)
        self.colors = [mp.track_color(v.index) for v in song.voices]
        self.shapes = [mp.program_to_shape(v.program) for v in song.voices]
        self.starts = [[n.start for n in v.notes] for v in song.voices]
        self.max_len = [max((n.duration for n in v.notes), default=0.0) for v in song.voices]
        self.end_time = song.duration + TAIL
        self.bar_set = {round(b, 6) for b in song.bar_times}

        # Темп -> швидкість руху. scroll(t) = пройдений сценою шлях у пікселях (інтеграл швидкості).
        segs = song.tempo_map.segments()
        self.seg_t = [s for s, _ in segs]
        self.seg_v = [mp.tempo_to_scroll_speed(bpm) for _, bpm in segs]
        self.seg_s, dist = [], 0.0
        for i, start in enumerate(self.seg_t):
            self.seg_s.append(dist)
            if i + 1 < len(self.seg_t):
                dist += (self.seg_t[i + 1] - start) * self.seg_v[i]

        # Ударні: кожен удар -> ефект (час, вид, velocity, доріжка, висота, зерно випадковості)
        self.hits = sorted(
            (n.start, mp.drum_kind(n.pitch), n.velocity, v.index, n.pitch, v.index * 10_000 + i)
            for v in song.voices if v.is_drum for i, n in enumerate(v.notes))
        self.hit_times = [h[0] for h in self.hits]

        # Журнал подій: текст пояснює, що саме спричинила кожна MIDI-подія.
        log = []
        for v in song.voices:
            shape = self.shapes[v.index]
            for n in v.notes:
                if v.is_drum:
                    kind = mp.drum_kind(n.pitch)
                    log.append((n.start, v.index, f"{n.start:6.2f} T{v.index + 1} on  "
                                f"{mp.DRUM_NAMES[kind]:<8}v{n.velocity:<3} -> {mp.DRUM_EFFECTS[kind]}"))
                    continue
                y = int(self.note_y(n.pitch))
                r = int(mp.velocity_to_size(n.velocity))
                log.append((n.start, v.index, f"{n.start:6.2f} T{v.index + 1} on  {note_name(n.pitch):<4}"
                            f"v{n.velocity:<3} -> {shape} y={y} r={r}"))
                log.append((n.end, v.index, f"{n.end:6.2f} T{v.index + 1} off {note_name(n.pitch):<4}"
                            f"     -> fade {mp.release_time(n.duration):.1f}s"))
        for e in song.events:
            if e.kind == "tempo":
                log.append((e.time, -1, f"{e.time:6.2f} tempo {e.value} BPM -> scroll "
                                        f"{mp.tempo_to_scroll_speed(e.value):.0f}px/s"))
            elif e.kind == "program":
                v = song.voices[e.voice]
                # Форма й тембр голосу задаються програмою, що діяла на його першій ноті;
                # зміна програми посеред треку на анімацію не впливає — так і пишемо в журналі.
                first = v.notes[0].start if v.notes else float("inf")
                effective = e.time <= first and e.value == v.program
                result = mp.program_to_shape(e.value) if effective else "без змін (після 1-ї ноти)"
                log.append((e.time, e.voice, f"{e.time:6.2f} T{e.voice + 1} prog {e.value:<3}"
                                             f"{mp.program_family(e.value)} -> {result}"))
        log.sort(key=lambda x: x[0])
        self.log = log
        self.log_times = [x[0] for x in log]

    @staticmethod
    def _make_glow(size: int) -> pygame.Surface:
        """М'яке радіальне світіння (для адитивного накладання)."""
        yy, xx = np.mgrid[0:size, 0:size]
        d = np.hypot(xx - size / 2 + 0.5, yy - size / 2 + 0.5) / (size / 2)
        v = (np.clip(1 - d, 0, 1) ** 2.2 * 255).astype(np.uint8)
        surf = pygame.Surface((size, size))
        pygame.surfarray.blit_array(surf, np.dstack([v, v, v]))
        return surf

    @staticmethod
    def _make_gradient(size, top, bottom) -> pygame.Surface:
        w, h = size
        k = np.linspace(0, 1, h)[None, :, None]
        arr = (np.array(top)[None, None, :] * (1 - k) + np.array(bottom)[None, None, :] * k)
        arr = np.repeat(arr, w, axis=0).astype(np.uint8)
        surf = pygame.Surface((w, h))
        pygame.surfarray.blit_array(surf, arr)
        return surf

    # ------------------------------------------------------------------ геометрія
    def scroll(self, t: float) -> float:
        i = max(bisect.bisect_right(self.seg_t, t) - 1, 0)
        return self.seg_s[i] + (t - self.seg_t[i]) * self.seg_v[i]

    def note_y(self, pitch: float) -> float:
        s = self.L.stage
        return mp.pitch_to_y(pitch, self.lo, self.hi, s.top + 30, s.bottom - 40)

    def bpm_at(self, t: float) -> float:
        return self.song.tempo_map.bpm_at(t)

    def sprites_at(self, t: float, st: ViewState) -> list[NoteSprite]:
        """Обчислює всі видимі мелодичні об'єкти в момент t (без малювання)."""
        L = self.L
        now = self.scroll(t)
        out = []
        for v in self.song.voices:
            vi = v.index
            if v.is_drum or vi in st.hidden:
                continue
            starts = self.starts[vi]
            lo_i = bisect.bisect_left(starts, t - self.max_len[vi] - FADE_MAX)
            hi_i = bisect.bisect_right(starts, t)
            for n in v.notes[lo_i:hi_i]:
                rel = mp.release_time(n.duration)
                if t > n.end + rel:
                    continue
                # Об'єкт з'являється на лінії spawn_x і рухається ліворуч зі швидкістю сцени.
                x = L.spawn_x - (now - self.scroll(n.start))
                tail_x = L.spawn_x - (now - self.scroll(min(t, n.end)))
                if tail_x < L.stage.left - 60:
                    continue
                age = t - n.start
                held = t < n.end
                fade = 1.0 if held else max(0.0, 1 - (t - n.end) / rel) ** 1.5
                r = mp.velocity_to_size(n.velocity) * mp.pop_scale(age) * (0.55 + 0.45 * fade)
                if held:
                    r *= 1 + 0.05 * math.sin(age * 2 * math.pi * 3)        # легка "пульсація" поки нота звучить
                dim = 0.25 if st.focus is not None and st.focus != vi else 1.0
                color = mp.note_color(self.colors[vi], n.pitch, self.lo, self.hi,
                                      mp.velocity_to_brightness(n.velocity))
                out.append(NoteSprite(vi, n.pitch, n.velocity, x, tail_x, self.note_y(n.pitch), r,
                                      color, int(255 * fade * dim), age, n.duration, held))
        return out

    # ------------------------------------------------------------------ малювання
    def render(self, surf: pygame.Surface, t: float, st: ViewState) -> None:
        surf.fill(BG)
        self._draw_stage(surf, t, st)
        self._draw_panel(surf, t, st)
        self._draw_roll(surf, t, st)
        self._draw_top(surf, t, st)
        if st.help:
            self._draw_help(surf)
        if st.message:
            self._toast(surf, st.message, st.message_error)

    def _text(self, font, s: str, color) -> pygame.Surface:
        key = (id(font), s, color)
        surf = self._text_cache.get(key)
        if surf is None:
            if len(self._text_cache) > 3000:
                self._text_cache.clear()
            surf = self._text_cache[key] = font.render(s, True, color)
        return surf

    def _glow(self, surf, x, y, r, color, strength: float) -> None:
        d = max(8, int(r * 4.2) // 4 * 4)
        q = max(1, min(12, round(strength * 12)))
        color = tuple(c // 16 * 16 for c in color)          # квантування — менше варіантів у кеші
        key = (d, color, q)
        sprite = self._glow_cache.get(key)
        if sprite is None:
            if len(self._glow_cache) > 1500:
                self._glow_cache.clear()
            sprite = pygame.transform.smoothscale(self._glow_base, (d, d))
            sprite.fill(tuple(int(c * q / 12) for c in color), special_flags=pygame.BLEND_RGB_MULT)
            self._glow_cache[key] = sprite
        surf.blit(sprite, (int(x - d / 2), int(y - d / 2)), special_flags=pygame.BLEND_RGB_ADD)

    def _draw_stage(self, surf, t: float, st: ViewState) -> None:
        L, S = self.L, self.L.stage
        surf.blit(self._bg, S)
        clip = surf.get_clip()
        surf.set_clip(S)
        now = self.scroll(t)

        # Сітка долей рухається зі швидкістю, що залежить від темпу.
        for b in self.song.beat_times:
            x = L.spawn_x - (now - self.scroll(b))
            if S.left <= x <= S.right:
                strong = round(b, 6) in self.bar_set
                pygame.gfxdraw.vline(surf, int(x), S.top, S.bottom, (150, 160, 255, 60 if strong else 22))

        # Фонові ефекти ударних: kick — пульсація, crash — спалах.
        add = np.zeros(3)
        lo_i = bisect.bisect_left(self.hit_times, t - 1.6)
        hi_i = bisect.bisect_right(self.hit_times, t)
        hits = [h for h in self.hits[lo_i:hi_i] if h[3] not in st.hidden]
        for h_t, kind, vel, vi, _p, _seed in hits:
            age, k = t - h_t, vel / 127
            if st.focus is not None and st.focus != vi:
                k *= 0.3
            if kind == "kick":
                add += np.array(self.colors[vi]) * 0.22 * k * math.exp(-age * 7)
            elif kind == "crash":
                add += np.array([255, 255, 255]) * 0.35 * k * math.exp(-age * 3.5)
        if add.any():
            surf.fill(tuple(int(min(255, c)) for c in add), S, special_flags=pygame.BLEND_RGB_ADD)

        sprites = self.sprites_at(t, st)
        # 1) "хвости": довжина = тривалість ноти x швидкість сцени
        for sp in sprites:
            th = max(2, int(sp.r * 0.45))
            x0, x1 = int(sp.x), int(sp.tail_x)
            if x1 - x0 > 2:
                pygame.gfxdraw.box(surf, pygame.Rect(x0, int(sp.y - th / 2), x1 - x0, th),
                                   (*sp.color, int(sp.alpha * 0.45)))
                pygame.gfxdraw.filled_circle(surf, x1, int(sp.y), th // 2, (*sp.color, int(sp.alpha * 0.45)))
        # 2) світіння, 3) тіло об'єкта, 4) кільце появи, 5) підписи
        for sp in sprites:
            self._glow(surf, sp.x, sp.y, sp.r, sp.color, sp.alpha / 255 * 0.7)
        for sp in sprites:
            draw_shape(surf, self.shapes[sp.voice], sp.x, sp.y, sp.r, sp.color, sp.alpha,
                       outline=_mix(sp.color, (255, 255, 255), 0.5))
        for sp in sprites:
            if sp.age < 0.45:
                k = sp.age / 0.45
                base = mp.velocity_to_size(sp.velocity)
                draw_ring(surf, sp.x, sp.y, base * (1 + 1.8 * k), _mix(sp.color, (255, 255, 255), 0.4),
                          int(220 * (1 - k) * sp.alpha / 255), 2)
        if st.labels:
            for sp in sprites:
                focused = st.focus == sp.voice
                if (st.focus is None and sp.duration >= LABEL_MIN_DURATION and sp.age < 0.7) or \
                        (focused and sp.age < 0.9):
                    life = 0.9 if focused else 0.7
                    img = self._text(self.f_label, f"{note_name(sp.pitch)} v{sp.velocity}", (235, 238, 255))
                    img.set_alpha(int(255 * (1 - sp.age / life) * sp.alpha / 255))
                    surf.blit(img, (int(sp.x + sp.r + 4), int(sp.y - sp.r - 10)))
                    img.set_alpha(None)

        # Передні ефекти ударних (детерміновані: випадковість із фіксованим зерном удару).
        for h_t, kind, vel, vi, pitch, seed in hits:
            age = t - h_t
            life = mp.DRUM_LIFETIME[kind]
            if age > life:
                continue
            k, v = age / life, vel / 127
            dim = 0.3 if st.focus is not None and st.focus != vi else 1.0
            color = _mix(self.colors[vi], (255, 255, 255), 0.35)
            rnd = random.Random(seed)
            effect = mp.DRUM_EFFECTS[kind]
            if effect == "pulse":
                rad = 30 + 520 * (1 - (1 - k) ** 2)
                draw_ring(surf, S.centerx - 60, S.bottom - 6, rad, color, int(170 * (1 - k) * v * dim), 3)
            elif effect == "burst":
                ox = S.left + S.w * rnd.uniform(0.2, 0.65)
                oy = S.top + S.h * rnd.uniform(0.3, 0.7)
                for i in range(18):
                    ang = 2 * math.pi * i / 18 + rnd.uniform(-0.15, 0.15)
                    dist = rnd.uniform(160, 360) * (0.6 + 0.4 * v) * age * (1 - 0.5 * k)
                    px, py = ox + math.cos(ang) * dist, oy + math.sin(ang) * dist
                    pygame.gfxdraw.filled_circle(surf, int(px), int(py), max(1, int(5 * (1 - k) + 1.5)),
                                                 (*color, int(240 * (1 - k) * dim)))
            elif effect == "sparkle":
                for _ in range(2):
                    sx = S.left + S.w * rnd.uniform(0.04, 0.78)
                    sy = S.top + rnd.uniform(14, 70)
                    size = (5 + 8 * v) * (1 - 0.5 * k)
                    draw_shape(surf, "star", sx, sy, size, color, int(255 * (1 - k) ** 1.5 * dim))
            elif effect == "flash":
                draw_ring(surf, S.centerx, S.centery, 50 + 700 * k, (255, 255, 255), int(140 * (1 - k) * dim), 4)
            elif effect == "ring":
                cx = S.left + S.w * (0.12 + 0.05 * (pitch - 41))
                draw_ring(surf, cx, S.top + S.h * 0.75, 10 + 150 * k, color, int(210 * (1 - k) * dim), 3)

        # Лінія появи нових нот
        for y in range(S.top, S.bottom, 10):
            pygame.gfxdraw.vline(surf, L.spawn_x, y, y + 5, (255, 255, 255, 70))
        surf.blit(self._text(self.f_small, "note_on", (200, 205, 230)), (L.spawn_x + 6, S.top + 6))
        surf.set_clip(clip)
        pygame.draw.rect(surf, (45, 50, 85), S, 1)

    def _draw_panel(self, surf, t: float, st: ViewState) -> None:
        P = self.L.panel
        pygame.draw.rect(surf, PANEL_BG, P, border_radius=8)
        x, y = P.x + 12, P.y + 10
        surf.blit(self._text(self.f_bold, "Доріжки (1–9 — вкл/викл)", TEXT), (x, y))
        y += 26
        for v in self.song.voices:
            vi = v.index
            hidden = vi in st.hidden
            color = self.colors[vi] if not hidden else (70, 72, 90)
            if st.focus == vi:
                pygame.draw.rect(surf, (40, 44, 80), (P.x + 4, y - 3, P.w - 8, 24), border_radius=5)
            surf.blit(self._text(self.f_mono, f"{vi + 1}", MUTED if hidden else TEXT), (x, y + 2))
            draw_shape(surf, self.shapes[vi] if not v.is_drum else "star", x + 26, y + 9, 7, color)
            name = v.name if len(v.name) <= 12 else v.name[:11] + "…"
            surf.blit(self._text(self.f_ui, name, MUTED if hidden else TEXT), (x + 40, y))
            info = "ударні · канал 10" if v.is_drum else f"{mp.program_family(v.program)} · {v.program}"
            if hidden:
                info = "вимкнено"
            surf.blit(self._text(self.f_small, info, MUTED), (x + 150, y + 2))
            y += 24
            if y > P.y + 190:
                rest = len(self.song.voices) - vi - 1
                if rest:
                    surf.blit(self._text(self.f_small, f"… і ще доріжок: {rest}", MUTED), (x + 40, y))
                    y += 18
                break

        y += 8
        pygame.draw.line(surf, (45, 50, 85), (P.x + 8, y), (P.right - 8, y))
        y += 8
        title = "Журнал: подія MIDI -> дія анімації"
        if st.focus is not None:
            title += f"  [T{st.focus + 1}]"
        surf.blit(self._text(self.f_bold, title, TEXT), (x, y))
        y += 24
        line_h = 16
        n_lines = max(1, (P.bottom - 8 - y) // line_h)
        idx = bisect.bisect_right(self.log_times, t)
        lines = []
        j = idx - 1
        while j >= 0 and len(lines) < n_lines:
            _lt, vi, text = self.log[j]
            if st.focus is None or vi in (st.focus, -1):
                lines.append((vi, text))
            j -= 1
        lines.reverse()
        for i, (vi, text) in enumerate(lines):
            newest = i == len(lines) - 1
            base = (255, 230, 140) if vi == -1 else _mix(self.colors[vi], (255, 255, 255), 0.3)
            if vi in st.hidden:
                base = (80, 82, 100)
            fade = 0.35 + 0.65 * (i + 1) / len(lines)
            color = _mix(PANEL_BG, base, fade)
            ly = y + i * line_h
            if newest:
                pygame.draw.rect(surf, (36, 40, 72), (P.x + 4, ly - 1, P.w - 8, line_h), border_radius=3)
            surf.blit(self._fit(text, P.right - (x - 4) - 6, color), (x - 4, ly))

    def _fit(self, text: str, width: int, color) -> pygame.Surface:
        """Рядок журналу, що вміщується в панель: спершу менший шрифт, потім обрізання по слову
        з «…», щоб ніколи не показати обрізане число (напр. r=2 замість r=27)."""
        for font in (self.f_mono, self.f_label):
            if font.size(text)[0] <= width:
                return self._text(font, text, color)
        words = text.split(" ")
        while len(words) > 1 and self.f_label.size(" ".join(words) + " …")[0] > width:
            words.pop()
        return self._text(self.f_label, " ".join(words) + " …", color)

    def _draw_roll(self, surf, t: float, st: ViewState) -> None:
        R = self.L.roll
        pygame.draw.rect(surf, (12, 13, 26), R, border_radius=6)
        t0 = t - ROLL_BEFORE
        pps = R.w / (ROLL_BEFORE + ROLL_AFTER)
        top, bottom = R.top + 20, R.bottom - 22
        drum_y = R.bottom - 18

        def tx(time: float) -> int:
            return int(R.x + (time - t0) * pps)

        clip = surf.get_clip()
        surf.set_clip(R)
        for b in self.song.beat_times:
            if t0 <= b <= t0 + ROLL_BEFORE + ROLL_AFTER:
                c = (40, 44, 78) if round(b, 6) in self.bar_set else (24, 26, 48)
                pygame.draw.line(surf, c, (tx(b), R.top + 18), (tx(b), R.bottom - 4))
        for v in self.song.voices:
            vi = v.index
            starts = self.starts[vi]
            lo_i = bisect.bisect_left(starts, t0 - self.max_len[vi])
            hi_i = bisect.bisect_right(starts, t0 + ROLL_BEFORE + ROLL_AFTER)
            base = self.colors[vi]
            for n in v.notes[lo_i:hi_i]:
                x0, x1 = tx(n.start), max(tx(n.end), tx(n.start) + 2)
                if vi in st.hidden or (st.focus is not None and st.focus != vi):
                    c = (45, 47, 62)
                elif n.start <= t < n.end:
                    c = _mix(base, (255, 255, 255), 0.35)
                elif n.end <= t:
                    c = _mix((12, 13, 26), base, 0.5)
                else:
                    c = _mix((12, 13, 26), base, 0.85)
                if v.is_drum:
                    hgt = 6 + int(10 * n.velocity / 127)
                    pygame.draw.rect(surf, c, (x0, drum_y + 16 - hgt, 3, hgt))
                else:
                    y = int(mp.pitch_to_y(n.pitch, self.lo, self.hi, top, bottom))
                    pygame.draw.rect(surf, c, (x0, y - 2, x1 - x0, 4), border_radius=2)
        px = tx(t)
        pygame.draw.line(surf, (255, 255, 255), (px, R.top + 16), (px, R.bottom - 2), 2)
        surf.set_clip(clip)
        surf.blit(self._text(self.f_small, f"Піано-рол: −{ROLL_BEFORE:g} с … +{ROLL_AFTER:g} с   "
                                           "(унизу — удари барабанів)", MUTED), (R.x + 10, R.y + 3))

    def _draw_top(self, surf, t: float, st: ViewState) -> None:
        T = self.L.top
        pygame.draw.rect(surf, (14, 15, 30), T)
        surf.blit(self._text(self.f_bold, "MIDI-анімація", TEXT), (12, 10))
        surf.blit(self._text(self.f_ui, self.title, MUTED), (140, 11))
        cx = T.centerx - 40
        # значок стану відтворення
        if st.playing:
            pygame.draw.polygon(surf, (120, 230, 140), [(cx, 12), (cx, 28), (cx + 13, 20)])
        else:
            pygame.draw.rect(surf, (255, 200, 90), (cx, 12, 4, 16))
            pygame.draw.rect(surf, (255, 200, 90), (cx + 8, 12, 4, 16))
        surf.blit(self._text(self.f_mono, f"{_fmt(t)} / {_fmt(self.end_time)}", TEXT), (cx + 24, 13))
        bpm = self._text(self.f_bold, f"{self.bpm_at(t):.0f} BPM", (255, 230, 140))
        surf.blit(bpm, (cx + 200, 10))
        right = "H — довідка" + ("" if st.audio else "   ·   без звуку")
        if st.warnings:   # у шрифті інтерфейсу немає символу ⚠, тому текстом
            more = f" (+{len(st.warnings) - 1})" if len(st.warnings) > 1 else ""
            right = "Увага: " + st.warnings[0]
            room = T.right - (cx + 200 + bpm.get_width()) - 40          # щоб не налізало на темп
            while self.f_ui.size(right + more)[0] > room and len(right) > 10:
                right = right[:-2] + "…"
            right += more
        img = self._text(self.f_ui, right, (255, 120, 120) if st.warnings else MUTED)
        surf.blit(img, (T.right - img.get_width() - 14, 11))
        # прогрес і позначки змін темпу
        k = min(max(t / self.end_time, 0), 1) if self.end_time else 0
        pygame.draw.rect(surf, (30, 32, 58), (0, T.bottom - 3, T.w, 3))
        pygame.draw.rect(surf, (120, 160, 255), (0, T.bottom - 3, int(T.w * k), 3))
        for s in self.seg_t[1:]:
            mx = int(T.w * s / self.end_time)
            pygame.draw.rect(surf, (255, 230, 140), (mx - 1, T.bottom - 7, 3, 7))

    def _draw_help(self, surf) -> None:
        lines = [
            "Пробіл — відтворення / пауза",
            "R — з початку",
            "← / → — перемотка на 5 с",
            "1–9 — сховати/показати доріжку (і вимкнути її звук)",
            "Tab — фокус на доріжці (підписи всіх її нот, фільтр журналу)",
            "L — підписи нот на сцені",
            "S — зберегти скріншот",
            "N / P — наступний / попередній файл у тій самій папці",
            "Перетягніть .mid у вікно, щоб відкрити інший файл",
            "H — сховати довідку,  Esc — вихід",
        ]
        S = self.L.stage
        box = pygame.Rect(0, 0, 560, 40 + 24 * len(lines))
        box.center = S.center
        overlay = pygame.Surface(box.size, pygame.SRCALPHA)
        overlay.fill((8, 9, 20, 225))
        surf.blit(overlay, box)
        pygame.draw.rect(surf, (90, 100, 170), box, 1, border_radius=6)
        surf.blit(self._text(self.f_bold, "Керування", TEXT), (box.x + 20, box.y + 12))
        for i, s in enumerate(lines):
            surf.blit(self._text(self.f_ui, s, TEXT), (box.x + 20, box.y + 40 + 24 * i))

    def _toast(self, surf, msg: str, error: bool = False) -> None:
        S = self.L.stage
        lines, line = [], ""
        for word in msg.split():                     # перенос довгих повідомлень по словах
            if line and self.f_ui.size(line + " " + word)[0] > S.w - 80:
                lines.append(line)
                line = word
            else:
                line = f"{line} {word}".strip()
        lines.append(line)
        imgs = [self._text(self.f_ui, ln, TEXT) for ln in lines]
        box = pygame.Rect(0, 0, max(i.get_width() for i in imgs) + 28, sum(i.get_height() for i in imgs) + 14)
        box.midbottom = (S.centerx, S.bottom - 16)
        pygame.draw.rect(surf, (120, 34, 44) if error else (30, 34, 64), box, border_radius=8)
        y = box.y + 7
        for img in imgs:
            surf.blit(img, img.get_rect(midtop=(box.centerx, y)))
            y += img.get_height()


def _fmt(t: float) -> str:
    t = max(t, 0)
    return f"{int(t // 60):02d}:{t % 60:04.1f}"
