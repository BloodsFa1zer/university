"""Створює набір вхідних файлів для перевірки програми в midi/samples/.

ok_*   — коректні MIDI різної будови: програма відтворює їх без попереджень;
warn_* — файл читається, але з даними щось не так: програма відкриває його і пише «Увага: …»;
bad_*  — файл неможливо прочитати як MIDI: програма показує помилку і не падає.

У вікні програми файли перебираються клавішами N / P (наступний / попередній у папці).
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import mido

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from make_demo_midi import DRUMS, TPB, TrackBuilder, conductor, n  # noqa: E402

OUT = ROOT / "midi" / "samples"


def save(tracks, path: Path, midi_type: int = 1) -> None:
    mid = mido.MidiFile(type=midi_type, ticks_per_beat=TPB)
    mid.tracks.extend(tracks)
    mid.save(path)


def ok_type0_multichannel(path: Path) -> None:
    """Тип 0: усі три партії в одному треку, розрізняються лише каналом."""
    piano, bass, drums = TrackBuilder("Type 0", 0, 0), TrackBuilder("Type 0", 1, 33), TrackBuilder("Type 0", DRUMS)
    melody = ["E5", "G5", "A5", "G5", "E5", "D5", "C5", "D5"] * 2
    for i, name in enumerate(melody):
        piano.note(i, 0.9, n(name), 70 + 6 * (i % 4))
    for bar, root in enumerate(["C3", "A2", "F2", "G2"]):
        for b in range(4):
            bass.note(bar * 4 + b, 0.45, n(root), 95 if b == 0 else 75)
    for b in range(16):
        drums.note(b, 0.1, 36 if b % 2 == 0 else 38, 110)
        drums.note(b + 0.5, 0.1, 42, 60)
    # зливаємо три партії в один трек: саме так виглядає MIDI типу 0
    merged = mido.merge_tracks([piano.build(), bass.build(), drums.build()])
    merged.insert(0, mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(100), time=0))
    save([merged], path, midi_type=0)


def ok_tempo_changes(path: Path) -> None:
    """Темп змінюється 70 -> 140 -> 90 BPM: змінюється швидкість прокрутки сцени."""
    strings, harp = TrackBuilder("Strings", 0, 48), TrackBuilder("Harp", 1, 46)
    chords = [["C4", "E4", "G4"], ["A3", "C4", "E4"], ["F3", "A3", "C4"], ["G3", "B3", "D4"]] * 2
    for bar, chord in enumerate(chords):
        for name in chord:
            strings.note(bar * 4, 3.8, n(name), 60 + 8 * bar)
        for k in range(8):
            harp.note(bar * 4 + k * 0.5, 0.45, n(chord[k % 3]) + 12 * (k // 3), 80)
    save([conductor([(0, 70), (8, 140), (24, 90)]), strings.build(), harp.build()], path)


def ok_extreme_values(path: Path) -> None:
    """Крайні значення: ноти 21 і 108, velocity 1 і 127, ноти в 1 тік і на 8 долей, кластер із 12 нот."""
    lead, drums = TrackBuilder("Extremes", 0, 81), TrackBuilder("Drums", DRUMS)
    lead.note(0, 1, 21, 127)
    lead.note(1, 1, 108, 1)
    for k in range(8):
        lead.note(2 + k * 0.25, 1 / TPB, 60 + k, 127)       # тривалість 1 тік
    lead.note(4, 8, n("C4"), 100)                           # довга нота на 8 долей
    for k in range(12):
        lead.note(6, 2, 48 + k, 30 + 8 * k)                 # 12 нот одночасно
    for k in range(4):                                      # та сама висота перекривається
        lead.note(8 + k * 0.5, 1.5, n("G5"), 90)
    for drum in (35, 36, 38, 42, 46, 49, 51, 57):           # усі барабани в один момент
        drums.note(10, 0.2, drum, 127)
    save([conductor([(0, 120)]), lead.build(), drums.build()], path)


def warn_one_track(path: Path) -> None:
    """Лише одна доріжка з нотами, а вимога — щонайменше дві."""
    flute = TrackBuilder("Flute", 0, 73)
    for i, name in enumerate(["C5", "D5", "E5", "G5", "E5", "D5", "C5", "C5"]):
        flute.note(i, 0.9, n(name), 80)
    save([conductor([(0, 110)]), flute.build()], path)


def warn_no_notes(path: Path) -> None:
    """Коректний MIDI без жодної ноти: є темп, назва треку і зміна інструмента."""
    track = mido.MidiTrack([mido.MetaMessage("track_name", name="Empty", time=0),
                            mido.Message("program_change", program=40, channel=0, time=0),
                            mido.MetaMessage("end_of_track", time=4 * TPB)])
    save([conductor([(0, 120)]), track], path)


def warn_unpaired_notes(path: Path) -> None:
    """Порушені пари подій: note_on без note_off і note_off без note_on."""
    piano = TrackBuilder("Piano", 0, 0)
    for i, name in enumerate(["C4", "E4", "G4", "C5"]):
        piano.note(i, 0.9, n(name), 80)
    track = piano.build()
    end = track.pop()                                        # end_of_track повернемо в кінці
    track += [mido.Message("note_on", note=n("A4"), velocity=90, time=0),          # без note_off
              mido.Message("note_on", note=n("F4"), velocity=90, time=TPB),        # без note_off
              mido.Message("note_off", note=n("B2"), velocity=64, time=TPB),       # без note_on
              end.copy(time=2 * TPB)]
    bass = TrackBuilder("Bass", 1, 33)
    for i in range(8):
        bass.note(i, 0.8, n("C3"), 90)
    save([conductor([(0, 100)]), track, bass.build()], path)


def smf(tpb: int, track: bytes) -> bytes:
    """MIDI-файл «вручну»: заголовок MThd (формат 0, 1 трек, tpb) і один чанк MTrk."""
    return b"MThd" + struct.pack(">IHHH", 6, 0, 1, tpb) + b"MTrk" + struct.pack(">I", len(track)) + track


def bad_files() -> dict[str, bytes]:
    end = b"\x00\xff\x2f\x00"                                           # подія end_of_track
    demo = (ROOT / "midi" / "demo_song.mid").read_bytes()
    return {
        "bad_empty.mid": b"",
        "bad_not_midi.mid": "Це текстовий файл, якому дали розширення .mid\n".encode(),
        "bad_truncated.mid": demo[: len(demo) // 2],                       # обрізаний посередині
        "bad_zero_ticks.mid": smf(0, end),                                 # ticks_per_beat = 0
        "bad_data_byte.mid": smf(TPB, b"\x00\x90\x3c\xc8" + end),          # байт даних 200 > 127
        "bad_wrong_extension.txt": "MIDI-файл має бути .mid або .midi\n".encode(),
    }


def build(out: Path = OUT) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    makers = [ok_type0_multichannel, ok_tempo_changes, ok_extreme_values,
              warn_one_track, warn_no_notes, warn_unpaired_notes]
    for i, make in enumerate(makers, start=1):
        make(out / f"{i:02d}_{make.__name__}.mid")
    for i, (name, data) in enumerate(bad_files().items(), start=len(makers) + 1):
        (out / f"{i:02d}_{name}").write_bytes(data)
    return sorted(out.iterdir())


if __name__ == "__main__":
    for p in build():
        print(p.relative_to(ROOT))
