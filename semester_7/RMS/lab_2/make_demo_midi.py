"""Створює демонстраційні MIDI-файли в папці midi/.

demo_song.mid    — ~40 с, 5 доріжок (Lead, Pad, Arp, Bass, Drums) + диригентська,
                   три зміни темпу (100 -> 124 -> 92 BPM), різна velocity.
mapping_test.mid — ~17 с, наочна перевірка правил: висхідна гама з crescendo
                   (вище -> вище на екрані, гучніше -> більше), ноти різної тривалості,
                   окремо kick / snare / hi-hat / crash / toms, зміна темпу 90 -> 150 BPM.
"""
from __future__ import annotations

import random
from pathlib import Path

import mido

TPB = 480
DRUMS = 9
NOTE_INDEX = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def n(name: str) -> int:
    """'E5' -> 76, 'C#4' -> 61."""
    pitch = NOTE_INDEX[name[0]]
    rest = name[1:]
    if rest[0] in "#b":
        pitch += 1 if rest[0] == "#" else -1
        rest = rest[1:]
    return pitch + (int(rest) + 1) * 12


class TrackBuilder:
    """Збирає ноти в абсолютних долях (beats) і перетворює їх на MIDI-трек."""

    def __init__(self, name: str, channel: int, program: int | None = None, zero_vel_off=False):
        self.name, self.channel, self.program = name, channel, program
        self.zero_vel_off = zero_vel_off      # note_off як note_on з velocity 0 (часто буває в реальних файлах)
        self.events: list[tuple[int, int, mido.Message]] = []

    def note(self, beat: float, dur: float, pitch: int, vel: int) -> None:
        vel = max(1, min(127, int(vel)))
        on, off = round(beat * TPB), round((beat + dur) * TPB)
        self.events.append((on, 1, mido.Message("note_on", note=pitch, velocity=vel, channel=self.channel)))
        off_msg = (mido.Message("note_on", note=pitch, velocity=0, channel=self.channel) if self.zero_vel_off
                   else mido.Message("note_off", note=pitch, velocity=64, channel=self.channel))
        self.events.append((off, 0, off_msg))   # при однаковому тіку note_off іде раніше за note_on

    def build(self) -> mido.MidiTrack:
        track = mido.MidiTrack([mido.MetaMessage("track_name", name=self.name, time=0)])
        if self.program is not None:
            track.append(mido.Message("program_change", program=self.program, channel=self.channel, time=0))
        last = 0
        for tick, _order, msg in sorted(self.events, key=lambda e: (e[0], e[1])):
            track.append(msg.copy(time=tick - last))
            last = tick
        track.append(mido.MetaMessage("end_of_track", time=0))
        return track


def conductor(tempos: list[tuple[float, float]]) -> mido.MidiTrack:
    """Диригентська доріжка: назва, розмір 4/4 і зміни темпу [(beat, bpm), ...]."""
    track = mido.MidiTrack([
        mido.MetaMessage("track_name", name="Conductor", time=0),
        mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0),
    ])
    last = 0
    for beat, bpm in tempos:
        tick = round(beat * TPB)
        track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm), time=tick - last))
        last = tick
    track.append(mido.MetaMessage("end_of_track", time=0))
    return track


def make_demo_song(path: Path) -> None:
    rnd = random.Random(7)

    def hum(v: float, spread: int = 6) -> int:          # невелика "людська" нерівність velocity
        return int(v + rnd.randint(-spread, spread))

    lead = TrackBuilder("Lead", 0, program=80)          # Square Lead -> коло
    pad = TrackBuilder("Pad", 1, program=89)            # Warm Pad -> шестикутник
    arp = TrackBuilder("Arp", 2, program=10)            # Music Box -> зірка
    bass = TrackBuilder("Bass", 3, program=38, zero_vel_off=True)   # Synth Bass -> ромб
    drums = TrackBuilder("Drums", DRUMS, program=0)

    progression = ["Am", "F", "C", "G"]
    pad_voicing = {"Am": ["A3", "C4", "E4"], "F": ["F3", "A3", "C4"],
                   "C": ["G3", "C4", "E4"], "G": ["G3", "B3", "D4"]}
    bass_root = {"Am": "A2", "F": "F2", "C": "C3", "G": "G2"}
    arp_notes = {"Am": ["A4", "C5", "E5", "A5"], "F": ["F4", "A4", "C5", "F5"],
                 "C": ["G4", "C5", "E5", "G5"], "G": ["G4", "B4", "D5", "G5"]}

    # --- Гармонія: такти 1..16 (по 4 долі), секція A = 1..8, секція B = 9..16
    for bar in range(16):
        chord = progression[bar % 4]
        b0 = bar * 4
        section_b = bar >= 8
        for p in pad_voicing[chord]:
            pad.note(b0, 4, n(p), hum(62 if section_b else 50, 3))
        root = n(bass_root[chord])
        if bar < 4:
            bass.note(b0, 2, root, hum(80)), bass.note(b0 + 2, 2, root, hum(70))
        elif not section_b:
            for beat, dur, oct_, v in [(0, 1.5, 0, 90), (1.5, 0.5, 12, 70), (2, 1, 0, 85), (3, 1, 0, 75)]:
                bass.note(b0 + beat, dur, root + oct_, hum(v))
        else:
            for k in range(8):                           # "пульсуючий" бас восьмими
                bass.note(b0 + k * 0.5, 0.45, root + (12 if k in (3, 7) else 0), hum(100 if k % 2 == 0 else 78))
        # арпеджіо: такти 3..12 — восьмі, 13..16 — шістнадцяті
        if bar >= 2:
            pattern = [0, 1, 2, 3, 2, 1, 2, 1]
            step = 0.25 if bar >= 12 else 0.5
            for k in range(int(4 / step)):
                pitch = n(arp_notes[chord][pattern[k % 8]]) + 12
                base = 52 if bar < 8 else 64
                arp.note(b0 + k * step, step * 0.9, pitch, hum(base + (14 if k % 4 == 0 else 0), 4))

    # --- Мелодія
    melody_a = [
        [(0, 1, "E5"), (1, 0.5, "D5"), (1.5, 0.5, "C5"), (2, 1, "D5"), (3, 1, "E5")],
        [(0, 1.5, "F5"), (1.5, 0.5, "E5"), (2, 1, "C5"), (3, 1, "A4")],
        [(0, 1, "G4"), (1, 0.5, "C5"), (1.5, 0.5, "D5"), (2, 1, "E5"), (3, 1, "G5")],
        [(0, 1.5, "D5"), (1.5, 0.5, "C5"), (2, 2, "B4")],
    ]
    melody_b = [
        [(0, .5, "A5"), (.5, .5, "G5"), (1, 1, "E5"), (2, .5, "A5"), (2.5, .5, "G5"), (3, .5, "E5"), (3.5, .5, "D5")],
        [(0, .5, "C5"), (.5, .5, "D5"), (1, 1, "F5"), (2, 1, "A5"), (3, .5, "G5"), (3.5, .5, "F5")],
        [(0, .5, "E5"), (.5, .5, "G5"), (1, 1, "C6"), (2, .5, "B5"), (2.5, .5, "G5"), (3, 1, "E5")],
        [(0, .5, "D5"), (.5, .5, "G5"), (1, 1, "B5"), (2, .5, "A5"), (2.5, .5, "G5"), (3, 1, "D5")],
    ]
    ending = [(0, .5, "D5"), (.5, .5, "G5"), (1, .5, "B5"), (1.5, .5, "D6"), (2, 2, "B5")]
    for i, bar_notes in enumerate(melody_a):                          # такти 5..8
        for beat, dur, name in bar_notes:
            lead.note((4 + i) * 4 + beat, dur * 0.95, n(name), hum(72 + 8 * i + (10 if beat == 0 else 0)))
    for rep in range(2):                                              # такти 9..16
        for i, bar_notes in enumerate(melody_b):
            if rep == 1 and i == 3:
                bar_notes = ending
            for beat, dur, name in bar_notes:
                accent = 14 if beat in (0, 2) else 0
                lead.note((8 + rep * 4 + i) * 4 + beat, dur * 0.92, n(name), hum(88 + rep * 8 + accent))
    lead.note(64, 4, n("A5"), 100)                                    # фінальна нота

    # --- Аутро: такти 17..18
    for p in ["A3", "C4", "E4", "A4"]:
        pad.note(64, 8, n(p), 60)
    bass.note(64, 6, n("A2"), 100)

    # --- Ударні
    kick, snare, chh, ohh, crash = 36, 38, 42, 46, 49
    for bar in range(16):
        b0 = bar * 4
        if bar < 8:
            for k in range(8):
                drums.note(b0 + k * 0.5, 0.1, chh, hum(48 if k % 2 == 0 else 32, 4))
            if bar >= 2:
                drums.note(b0, 0.2, kick, hum(100)), drums.note(b0 + 2, 0.2, kick, hum(92))
            if bar >= 4:
                drums.note(b0 + 3.5, 0.2, kick, hum(70))
                drums.note(b0 + 1, 0.2, snare, hum(68)), drums.note(b0 + 3, 0.2, snare, hum(74))
        else:
            for k in range(16):
                drums.note(b0 + k * 0.25, 0.08, chh, hum([72, 40, 56, 40][k % 4], 4))
            for beat, v in [(0, 118), (1.5, 92), (2, 110)]:
                drums.note(b0 + beat, 0.2, kick, hum(v))
            drums.note(b0 + 1, 0.2, snare, hum(108)), drums.note(b0 + 3, 0.2, snare, hum(112))
            if bar % 2 == 1:
                drums.note(b0 + 3.5, 0.4, ohh, hum(80))
    for bar in (7, 15):                                               # брейки на томах
        b0 = bar * 4
        for k, tom in enumerate([50, 48, 45, 43, 41, 41]):
            drums.note(b0 + 2.5 + k * 0.25, 0.2, tom, 90 + k * 5)
    for beat in (32, 48, 64):
        drums.note(beat, 1.5, crash, 115)
    drums.note(64, 0.3, kick, 120)

    mid = mido.MidiFile(type=1, ticks_per_beat=TPB)
    mid.tracks.append(conductor([(0, 100), (32, 124), (64, 92)]))
    for tb in (lead, pad, arp, bass, drums):
        mid.tracks.append(tb.build())
    mid.save(path)


def make_mapping_test(path: Path) -> None:
    scale = TrackBuilder("Scale", 0, program=0)          # Piano -> коло
    bass = TrackBuilder("Bass", 1, program=33)           # Finger Bass -> ромб
    drums = TrackBuilder("Drums", DRUMS, program=0)

    # Висхідна гама C3..C6 з crescendo 20 -> 127: об'єкти піднімаються й ростуть
    c_major = [0, 2, 4, 5, 7, 9, 11]
    pitches = [48 + 12 * (i // 7) + c_major[i % 7] for i in range(22)]
    for i, p in enumerate(pitches):
        scale.note(i * 0.5, 0.45, p, 20 + 107 * i / (len(pitches) - 1))
    # Однакова нота різної тривалості: довший "хвіст" і повільніше згасання
    beat = 12.0
    for dur in (0.25, 0.5, 1, 2, 4):
        scale.note(beat, dur, n("E4"), 100)
        beat += dur + 0.5
    # Спадна гама після зміни темпу з diminuendo
    for i, p in enumerate(reversed(pitches)):
        scale.note(27 + i * 0.25, 0.22, p, 127 - 100 * i / (len(pitches) - 1))

    for k in range(8):
        bass.note(k * 4, 3.5, n("C2") if k % 2 == 0 else n("G2"), 95)

    # По такту на кожен ударний інструмент, щоб було видно різні ефекти
    for k in range(4):
        drums.note(k, 0.2, 36, 120)                       # kick -> пульсація
        drums.note(4 + k, 0.2, 38, 110)                   # snare -> вибух частинок
    for k in range(8):
        drums.note(8 + k * 0.5, 0.1, 42, 90)              # hi-hat -> іскри
    drums.note(12, 1.5, 49, 120)                          # crash -> спалах
    for k, tom in enumerate([50, 48, 45, 43, 41, 41]):
        drums.note(13 + k * 0.5, 0.3, tom, 100)           # tom -> кільця
    for k in range(16, 32):
        drums.note(k, 0.2, 36 if k % 2 == 0 else 38, 110)
        drums.note(k + 0.5, 0.1, 42, 70)

    mid = mido.MidiFile(type=1, ticks_per_beat=TPB)
    mid.tracks.append(conductor([(0, 90), (16, 150)]))
    for tb in (scale, bass, drums):
        mid.tracks.append(tb.build())
    mid.save(path)


def main() -> None:
    out = Path(__file__).resolve().parent / "midi"
    out.mkdir(exist_ok=True)
    make_demo_song(out / "demo_song.mid")
    make_mapping_test(out / "mapping_test.mid")
    print("Створено:", out / "demo_song.mid", ",", out / "mapping_test.mid")


if __name__ == "__main__":
    main()
