"""Завантаження MIDI-файлу: ноти й події з абсолютним часом у секундах.

MIDI зберігає час у тіках (ticks) між подіями. Щоб перевести тіки в секунди,
потрібні ticks_per_beat (тіків на чвертну ноту) і темп (мікросекунд на чвертну),
який може змінюватися подіями set_tempo. Цим займається клас TempoMap.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from pathlib import Path

import mido

DRUM_CHANNEL = 9           # канал 10 у звичній нумерації 1..16 — ударні (General MIDI)
DEFAULT_TEMPO = 500_000    # мкс на чвертну ноту = 120 BPM (значення за замовчуванням у MIDI)

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def note_name(pitch: int) -> str:
    """Назва ноти за MIDI-номером: 60 -> C4, 69 -> A4."""
    return f"{NOTE_NAMES[pitch % 12]}{pitch // 12 - 1}"


@dataclass
class Note:
    start: float      # секунди
    end: float        # секунди
    pitch: int        # 0..127
    velocity: int     # 1..127 — сила натискання
    channel: int

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class Voice:
    """Логічна доріжка для анімації: ноти одного MIDI-треку на одному каналі."""
    index: int
    name: str
    track_index: int
    channel: int
    program: int
    notes: list[Note] = field(default_factory=list)

    @property
    def is_drum(self) -> bool:
        return self.channel == DRUM_CHANNEL


@dataclass
class MidiEvent:
    """Подія для журналу: note_on / note_off / program / tempo."""
    time: float
    voice: int        # індекс Voice; -1 для подій темпу (вони спільні для всіх доріжок)
    kind: str
    value: int        # висота ноти / номер програми / BPM
    velocity: int = 0


class TempoMap:
    """Перетворення тіків у секунди з урахуванням усіх змін темпу."""

    def __init__(self, ticks_per_beat: int, changes: list[tuple[int, int]]):
        self.tpb = ticks_per_beat
        changes = sorted(changes, key=lambda c: c[0])      # стабільне сортування за тіком
        if not changes or changes[0][0] != 0:
            changes.insert(0, (0, DEFAULT_TEMPO))
        self.ticks: list[int] = []
        self.tempos: list[int] = []
        self.seconds: list[float] = []
        sec = 0.0
        for tick, tempo in changes:
            if self.ticks and tick == self.ticks[-1]:
                self.tempos[-1] = tempo                      # кілька змін в один тік — діє остання
                continue
            if self.ticks:
                sec += self._span(tick - self.ticks[-1], self.tempos[-1])
            self.ticks.append(tick)
            self.tempos.append(tempo)
            self.seconds.append(sec)

    def _span(self, ticks: int, tempo: int) -> float:
        # тіки -> біти -> мікросекунди -> секунди
        return ticks / self.tpb * tempo / 1_000_000

    def to_seconds(self, tick: int) -> float:
        i = bisect.bisect_right(self.ticks, tick) - 1
        return self.seconds[i] + self._span(tick - self.ticks[i], self.tempos[i])

    def bpm_at(self, sec: float) -> float:
        i = max(bisect.bisect_right(self.seconds, sec) - 1, 0)
        return mido.tempo2bpm(self.tempos[i])

    def segments(self) -> list[tuple[float, float]]:
        """Відрізки сталого темпу: [(початок у секундах, BPM), ...]."""
        return [(s, mido.tempo2bpm(t)) for s, t in zip(self.seconds, self.tempos)]


@dataclass
class Song:
    path: str
    midi_type: int
    track_count: int              # кількість треків у файлі (включно з "диригентським")
    ticks_per_beat: int
    tempo_map: TempoMap
    voices: list[Voice]
    events: list[MidiEvent]
    duration: float
    beat_times: list[float]
    bar_times: list[float]
    issues: list[str] = field(default_factory=list)   # що довелося виправити під час розбору

    @property
    def note_track_count(self) -> int:
        """Кількість MIDI-треків, які містять ноти."""
        return len({v.track_index for v in self.voices})


class MidiLoadError(Exception):
    """Файл не вдалося прочитати як MIDI. Текст помилки показується користувачу."""


MAX_DURATION = 30 * 60      # с; довші файли майже напевно мають пошкоджені часові позначки


def open_midi(path) -> mido.MidiFile:
    """Відкриває MIDI-файл; помилки mido (англійською, часто без тексту) перетворює на зрозумілі."""
    p = Path(path)
    if p.is_dir():
        raise MidiLoadError(f"це папка, а не файл: {p}")
    if not p.is_file():
        raise MidiLoadError(f"файл не знайдено: {p}")
    if p.stat().st_size == 0:
        raise MidiLoadError("файл порожній (0 байт)")
    try:
        return mido.MidiFile(p)
    except EOFError:
        raise MidiLoadError("файл обрізаний: дані закінчились раніше, ніж очікувалось") from None
    except OSError as exc:
        if "MThd" in str(exc):
            raise MidiLoadError("це не MIDI-файл: на початку немає заголовка MThd") from None
        raise MidiLoadError(f"пошкоджені дані всередині треку ({exc})") from None
    except (ValueError, KeyError, IndexError) as exc:
        raise MidiLoadError(f"пошкоджені дані MIDI: {exc}") from None


def load_song(source) -> Song:
    """Читає MIDI з файлу (шлях) або з готового mido.MidiFile."""
    mid = source if isinstance(source, mido.MidiFile) else open_midi(source)
    tpb = mid.ticks_per_beat
    if tpb < 0:
        raise MidiLoadError("час у форматі SMPTE (кадри за секунду) не підтримується, потрібні тіки на чверть")
    if tpb == 0:
        raise MidiLoadError(f"некоректний заголовок: ticks_per_beat = {tpb}")

    # 1) Темп і розмір такту збираємо з усіх треків: у файлах типу 1
    #    set_tempo зазвичай лежить у треку 0, але це не обов'язково.
    tempo_changes: list[tuple[int, int]] = []
    beats_per_bar = 4
    end_tick = 0
    for track in mid.tracks:
        tick = 0
        for msg in track:
            tick += msg.time
            if msg.type == "set_tempo":
                tempo_changes.append((tick, msg.tempo))
            elif msg.type == "time_signature" and tick == 0:
                beats_per_bar = msg.numerator
        end_tick = max(end_tick, tick)
    bad = [tempo for _, tempo in tempo_changes if tempo <= 0]
    if bad:
        raise MidiLoadError(f"некоректна подія set_tempo: {bad[0]} мкс на чверть (має бути більше 0)")
    tmap = TempoMap(tpb, tempo_changes)
    sec = tmap.to_seconds
    if sec(end_tick) > MAX_DURATION:
        raise MidiLoadError(f"файл задовгий: {sec(end_tick) / 60:.0f} хв (підтримується до "
                            f"{MAX_DURATION // 60} хв); ймовірно, пошкоджені часові позначки")

    # 2) Ноти: пара note_on -> note_off для кожної (канал, висота).
    #    note_on з velocity = 0 за стандартом означає note_off.
    raw_voices: dict[tuple[int, int], dict] = {}
    raw_events: list[tuple[float, tuple[int, int] | None, str, int, int]] = []
    orphan_offs = unclosed = 0
    for ti, track in enumerate(mid.tracks):
        name = None
        programs: dict[int, int] = {}
        active: dict[tuple[int, int], list[tuple[int, int]]] = {}
        tick = 0

        def voice(ch: int) -> dict:
            # Доріжка створюється на першій ноті й запам'ятовує інструмент, що діяв у той момент.
            return raw_voices.setdefault(
                (ti, ch), {"program": programs.get(ch, 0), "notes": [], "name": None})

        for msg in track:
            tick += msg.time
            if msg.type == "track_name" and name is None:
                name = msg.name.strip()
            elif msg.type == "program_change":
                programs[msg.channel] = msg.program
                raw_events.append((sec(tick), (ti, msg.channel), "program", msg.program, 0))
            elif msg.type == "note_on" and msg.velocity > 0:
                voice(msg.channel)
                active.setdefault((msg.channel, msg.note), []).append((tick, msg.velocity))
                raw_events.append((sec(tick), (ti, msg.channel), "note_on", msg.note, msg.velocity))
            elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
                stack = active.get((msg.channel, msg.note))
                if not stack:
                    orphan_offs += 1                      # note_off без note_on — ігноруємо
                    continue
                on_tick, vel = stack.pop(0)               # FIFO для однакових нот, що перекриваються
                voice(msg.channel)["notes"].append(
                    Note(sec(on_tick), sec(tick), msg.note, vel, msg.channel))
                raw_events.append((sec(tick), (ti, msg.channel), "note_off", msg.note, 0))

        # Ноти без note_off закриваємо в кінці треку.
        for (ch, pitch), stack in active.items():
            for on_tick, vel in stack:
                unclosed += 1
                voice(ch)["notes"].append(Note(sec(on_tick), sec(tick), pitch, vel, ch))
                raw_events.append((sec(tick), (ti, ch), "note_off", pitch, 0))
        for (t_i, ch), v in raw_voices.items():
            if t_i == ti and v["name"] is None:
                v["name"] = name or f"Track {ti}"

    # 3) Формуємо логічні доріжки (тільки ті, де є ноти) у порядку (трек, канал).
    channels_in_track: dict[int, int] = {}
    for (ti, _ch), v in raw_voices.items():
        if v["notes"]:
            channels_in_track[ti] = channels_in_track.get(ti, 0) + 1
    voices: list[Voice] = []
    key_to_index: dict[tuple[int, int], int] = {}
    for (ti, ch) in sorted(k for k, v in raw_voices.items() if v["notes"]):
        v = raw_voices[(ti, ch)]
        label = v["name"] if channels_in_track[ti] == 1 else f"{v['name']} ch{ch + 1}"
        notes = sorted(v["notes"], key=lambda n: (n.start, n.pitch))
        key_to_index[(ti, ch)] = len(voices)
        voices.append(Voice(len(voices), label, ti, ch, v["program"], notes))

    events = [MidiEvent(t, key_to_index[k], kind, val, vel)
              for t, k, kind, val, vel in raw_events if k in key_to_index]
    events += [MidiEvent(s, -1, "tempo", round(bpm), 0) for s, bpm in tmap.segments()]
    order = {"tempo": 0, "program": 1, "note_off": 2, "note_on": 3}
    events.sort(key=lambda e: (e.time, order[e.kind], e.voice))

    duration = max((n.end for v in voices for n in v.notes), default=sec(end_tick))
    n_beats = end_tick // tpb + 2
    beat_times = [sec(b * tpb) for b in range(n_beats)]
    bar_times = beat_times[::max(beats_per_bar, 1)]
    issues = []
    if unclosed:
        issues.append(f"нот без note_off: {unclosed} (закрито в кінці треку)")
    if orphan_offs:
        issues.append(f"note_off без note_on: {orphan_offs} (пропущено)")
    return Song(str(getattr(source, "filename", source)), mid.type, len(mid.tracks), tpb,
                tmap, voices, events, duration, beat_times, bar_times, issues)


def validate_song(song: Song) -> list[str]:
    """Перевірка вимог лабораторної: щонайменше дві доріжки з нотами."""
    warnings = []
    if not song.voices:
        warnings.append("У файлі немає нот")
    elif song.note_track_count < 2 and len(song.voices) < 2:
        warnings.append("MIDI має менше двох доріжок з нотами (вимога: ≥ 2)")
    return warnings + song.issues
