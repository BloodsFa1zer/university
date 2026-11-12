"""MIDI-анімація — точка входу.

  python app.py [файл.mid]                       інтерактивний режим (вікно + звук)
  python app.py файл.mid --export out.mp4        рендер у відео без вікна
  python app.py файл.mid --screenshot 5,12.5     зберегти кадри у PNG
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
DEFAULT_MIDI = HERE / "midi" / "demo_song.mid"


def parse_size(text: str) -> tuple[int, int]:
    try:
        w, h = (int(v) for v in text.lower().split("x"))
    except ValueError:
        raise argparse.ArgumentTypeError(f"очікується ШИРИНАxВИСОТА, напр. 1280x720, а не {text!r}")
    if not (640 <= w <= 3840 and 360 <= h <= 2160):
        raise argparse.ArgumentTypeError("розмір має бути від 640x360 до 3840x2160")
    return w, h


def parse_times(text: str) -> list[float]:
    try:
        times = [float(x) for x in text.split(",") if x.strip()]
    except ValueError:
        raise argparse.ArgumentTypeError(f"очікуються моменти часу в секундах через кому, напр. 5,12.5, а не {text!r}")
    if not times or min(times) < 0:
        raise argparse.ArgumentTypeError("моменти часу мають бути невід'ємними числами")
    return times


def parse_tracks(text: str) -> set[int]:
    try:
        tracks = {int(x) for x in text.split(",") if x.strip()}
    except ValueError:
        raise argparse.ArgumentTypeError(f"очікуються номери доріжок через кому, напр. 2,3, а не {text!r}")
    if any(t < 1 for t in tracks):
        raise argparse.ArgumentTypeError("номери доріжок починаються з 1")
    return tracks


def int_range(lo: int, hi: int):
    def parse(text: str) -> int:
        try:
            v = int(text)
        except ValueError:
            raise argparse.ArgumentTypeError(f"очікується ціле число, а не {text!r}")
        if not lo <= v <= hi:
            raise argparse.ArgumentTypeError(f"значення має бути від {lo} до {hi}")
        return v
    return parse


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Анімація на основі MIDI-файлу")
    p.add_argument("midi", nargs="?", default=str(DEFAULT_MIDI), help="шлях до .mid")
    p.add_argument("--size", type=parse_size, default="1280x720", help="розмір кадру, напр. 1280x720")
    p.add_argument("--export", metavar="OUT.mp4", help="зберегти анімацію у відео (H.264 + AAC)")
    p.add_argument("--fps", type=int_range(1, 120), default=30, help="кадрів за секунду для експорту")
    p.add_argument("--start", type=float, default=0.0, help="початок фрагмента для експорту, с")
    p.add_argument("--end", type=float, help="кінець фрагмента для експорту, с")
    p.add_argument("--screenshot", metavar="T1,T2,...", type=parse_times, help="зберегти кадри в моменти часу (с)")
    p.add_argument("--outdir", default=str(HERE / "screenshots"), help="папка для скріншотів")
    p.add_argument("--prefix", default="frame", help="префікс імен файлів скріншотів")
    p.add_argument("--focus", type=int_range(1, 99), help="номер доріжки у фокусі (1..9)")
    p.add_argument("--hide", type=parse_tracks, default=set(), help="сховати доріжки, напр. 2,3")
    p.add_argument("--no-labels", action="store_true", help="без підписів нот на сцені")
    p.add_argument("--no-audio", action="store_true", help="без звуку")
    args = p.parse_args(argv)
    if args.start < 0:
        p.error("--start не може бути від'ємним")
    if args.end is not None and args.end <= args.start:
        p.error("--end має бути більшим за --start")
    return args


def ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"



def describe(exc: Exception) -> str:
    """Текст помилки для повідомлення у вікні: зрозумілий для MidiLoadError, загальний для решти."""
    from midi_loader import MidiLoadError
    if isinstance(exc, MidiLoadError):
        return str(exc)
    return f"непередбачена помилка ({exc.__class__.__name__}: {exc})"

def main(argv=None) -> None:
    args = parse_args(argv)
    size = args.size
    headless = bool(args.export or args.screenshot)
    if headless:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

    import pygame
    import synth
    from midi_loader import load_song, validate_song
    from scene import Scene, ViewState

    if not headless and not args.no_audio:
        pygame.mixer.pre_init(synth.SR, -16, 2, 1024)
    pygame.init()

    state = ViewState(labels=not args.no_labels,
                      hidden={x - 1 for x in args.hide},
                      focus=args.focus - 1 if args.focus else None)

    if headless:
        try:
            song = load_song(args.midi)
        except Exception as exc:             # MidiLoadError — зрозумілий текст; інше — коротко, без трасування
            sys.exit(f"Помилка: {Path(args.midi).name}: {describe(exc)}")
        state.warnings = validate_song(song)
        for w in state.warnings:
            print("Увага:", w)
        if args.screenshot:
            save_screenshots(song, size, state, args.screenshot,
                             Path(args.outdir), args.prefix)
        if args.export:
            if not song.voices:
                sys.exit(f"Помилка: {Path(args.midi).name}: у файлі немає нот — експортувати нічого")
            export_video(song, size, state, Path(args.export), args.fps, args.start, args.end)
        return

    run_interactive(Path(args.midi), size, state, audio=not args.no_audio)


# ---------------------------------------------------------------------------- звук
class AudioPlayer:
    """Відтворює синтезований звук. Годинник анімації запускається разом зі звуком,
    тож анімація і звук стартують, стають на паузу і перемотуються синхронно."""

    def __init__(self, song, enabled: bool = True):
        import pygame
        import synth
        self._pg, self._synth = pygame, synth
        init = pygame.mixer.get_init()
        self.ok = enabled and init is not None and init[2] == 2
        self.total = song.duration + synth.TAIL
        self.offset = 0.0
        self.started: float | None = None
        self.channel = None
        self.muted: set[int] = set()
        self._mixed = None
        if self.ok:
            self.stems = synth.render_stems(song)
            self.pans = synth.default_pans(song)
            self.master = synth.master_gain(self.stems, self.pans)   # фіксуємо гучність повного міксу

    @property
    def playing(self) -> bool:
        return self.started is not None

    def position(self) -> float:
        t = self.offset + (time.perf_counter() - self.started if self.started is not None else 0.0)
        return min(t, self.total)

    def _pcm(self) -> np.ndarray:
        if self._mixed is None:
            self._mixed = self._synth.to_int16(
                self._synth.mix(self.stems, self.pans, self.muted, self.master))
        return self._mixed

    def _stop_sound(self) -> None:
        if self.channel is not None:
            self.channel.stop()
            self.channel = None

    def play(self, t: float | None = None) -> None:
        if t is not None:
            self.offset = max(0.0, min(t, self.total))
        self._stop_sound()
        if self.ok:
            data = self._pcm()[int(self.offset * self._synth.SR):]
            if len(data):
                sound = self._pg.sndarray.make_sound(np.ascontiguousarray(data))
                self.channel = sound.play()
        self.started = time.perf_counter()

    def pause(self) -> None:
        if self.started is None:
            return
        self.offset = self.position()
        self.started = None
        if self.channel is not None:
            self.channel.pause()

    def toggle(self) -> None:
        if self.playing:
            self.pause()
        elif self.offset >= self.total - 0.05:
            self.play(0.0)                       # з кінця — починаємо спочатку
        elif self.channel is not None:
            self.channel.unpause()
            self.started = time.perf_counter()
        else:
            self.play()

    def seek(self, t: float) -> None:
        was_playing = self.playing
        self._stop_sound()
        self.offset = max(0.0, min(t, self.total))
        self.started = None
        if was_playing:
            self.play()

    def set_muted(self, muted: set[int]) -> None:
        """Вимкнення звуку доріжок: перезводимо мікс і продовжуємо з тієї ж позиції."""
        self.muted = set(muted)
        self._mixed = None
        if self.playing:
            self.play(self.position())
        else:
            self._stop_sound()

    def stop(self) -> None:
        self._stop_sound()
        self.started = None


# ---------------------------------------------------------------------------- режими
def run_interactive(path: Path, size, state, audio: bool) -> None:
    import pygame
    from midi_loader import load_song, validate_song
    from scene import Scene

    screen = pygame.display.set_mode(size)
    clock = pygame.time.Clock()

    def splash(text: str) -> None:
        screen.fill((6, 7, 16))
        font = pygame.font.Font(pygame.font.match_font("helveticaneue,arial,dejavusans"), 22)
        img = font.render(text, True, (225, 228, 240))
        screen.blit(img, img.get_rect(center=screen.get_rect().center))
        pygame.display.flip()

    def load(p: Path):
        splash(f"Завантаження {p.name}: розбір MIDI і синтез звуку…")
        song = load_song(p)                  # MidiLoadError — до того, як щось змінилося
        state.warnings = validate_song(song)
        state.hidden = {i for i in state.hidden if i < len(song.voices)}
        if state.focus is not None and state.focus >= len(song.voices):
            state.focus = None
        pygame.display.set_caption(f"MIDI-анімація — {p.name}")
        player = AudioPlayer(song, enabled=audio)
        state.audio = player.ok
        player.set_muted(state.hidden)
        return song, Scene(song, size), player

    message_until = 0.0

    def say(msg: str, error: bool = False) -> None:
        nonlocal message_until
        state.message, state.message_error = msg, error
        message_until = time.time() + (5.0 if error else 2.0)

    cursor = path          # позиція перегляду папки клавішами N/P: рухається і по некоректних файлах
    try:
        song, scene, player = load(path)
    except Exception as exc:                 # стартовий файл зіпсований — відкриваємо демо
        song, scene, player = load(DEFAULT_MIDI)
        say(f"Не вдалося відкрити {path.name}: {describe(exc)}. Відкрито демо.", error=True)
        path = DEFAULT_MIDI
    player.play(0.0)

    def open_file(p: Path) -> None:
        """Відкриває інший файл; якщо він некоректний — лишається попередній."""
        nonlocal song, scene, player, path
        try:                                 # тип файлу визначаємо за вмістом (заголовок MThd), а не за розширенням
            new = load(p)
        except Exception as exc:
            say(f"Не вдалося відкрити {p.name}: {describe(exc)}", error=True)
            return
        player.stop()
        song, scene, player = new
        path = p
        player.play(0.0)
        info = f"{p.name}: доріжок {len(song.voices)}, нот {sum(len(v.notes) for v in song.voices)}"
        say(info + (f". Увага: {'; '.join(state.warnings)}" if state.warnings else ""), error=bool(state.warnings))

    def neighbour(step: int) -> Path:
        """Сусідній файл у тій самій папці (N/P) — щоб по черзі показати всі тестові входи."""
        folder = cursor.parent if cursor.parent.is_dir() else DEFAULT_MIDI.parent
        files = sorted(f for f in folder.iterdir() if f.is_file() and not f.name.startswith("."))
        i = files.index(cursor) if cursor in files else -1
        return files[(i + step) % len(files)]

    running = True
    while running:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            elif ev.type == pygame.DROPFILE:
                cursor = Path(ev.file)
                open_file(cursor)
            elif ev.type == pygame.KEYDOWN:
                key = ev.key
                if key == pygame.K_ESCAPE:
                    running = False
                elif key in (pygame.K_n, pygame.K_p):
                    cursor = neighbour(1 if key == pygame.K_n else -1)
                    open_file(cursor)
                elif key == pygame.K_SPACE:
                    player.toggle()
                elif key == pygame.K_r:
                    player.play(0.0)
                elif key == pygame.K_LEFT:
                    player.seek(player.position() - 5)
                elif key == pygame.K_RIGHT:
                    player.seek(player.position() + 5)
                elif pygame.K_1 <= key <= pygame.K_9:
                    vi = key - pygame.K_1
                    if vi < len(song.voices):
                        state.hidden ^= {vi}
                        player.set_muted(state.hidden)
                        say(f"Доріжка {vi + 1} ({song.voices[vi].name}): "
                            f"{'вимкнено' if vi in state.hidden else 'увімкнено'}")
                elif key == pygame.K_TAB:
                    n = len(song.voices)
                    state.focus = 0 if state.focus is None else (state.focus + 1 if state.focus + 1 < n else None)
                    say("Фокус: всі доріжки" if state.focus is None
                        else f"Фокус: T{state.focus + 1} {song.voices[state.focus].name}")
                elif key == pygame.K_l:
                    state.labels = not state.labels
                elif key == pygame.K_h:
                    state.help = not state.help
                elif key == pygame.K_s:
                    out = Path(__file__).resolve().parent / "screenshots"
                    out.mkdir(exist_ok=True)
                    file = out / f"shot_{player.position():07.2f}.png"
                    pygame.image.save(screen, file)
                    say(f"Скріншот: {file.name}")

        t = player.position()
        if player.playing and t >= scene.end_time:
            player.pause()
        state.playing = player.playing
        if state.message and time.time() > message_until:
            state.message = ""
        scene.render(screen, t, state)
        pygame.display.flip()
        clock.tick(60)
    pygame.quit()


def save_screenshots(song, size, state, times, outdir: Path, prefix: str) -> None:
    import pygame
    from scene import Scene
    outdir.mkdir(parents=True, exist_ok=True)
    scene = Scene(song, size)
    surf = pygame.Surface(size)
    for t in times:
        scene.render(surf, t, state)
        file = outdir / f"{prefix}_{t:06.2f}.png"
        pygame.image.save(surf, file)
        print("saved", file)


def export_video(song, size, state, out: Path, fps: int, start: float = 0.0, end: float | None = None) -> None:
    """Рендер кадрів без вікна і передача їх у ffmpeg разом із синтезованим звуком."""
    import pygame
    import synth
    from scene import Scene
    scene = Scene(song, size)
    surf = pygame.Surface(size)
    end = scene.end_time if end is None else min(end, scene.end_time)
    n_frames = int(round((end - start) * fps))
    if n_frames <= 0:
        sys.exit(f"Помилка: фрагмент {start:.1f}–{end:.1f} с порожній (пісня триває {scene.end_time:.1f} с)")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "audio.wav"
        audio = synth.render_song(song)
        synth.write_wav(wav, audio[int(start * synth.SR): int(end * synth.SR)])
        cmd = [ffmpeg_exe(), "-y", "-loglevel", "error",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{size[0]}x{size[1]}", "-r", str(fps), "-i", "-",
               "-i", str(wav),
               "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(out)]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        t0 = time.time()
        for i in range(n_frames):
            scene.render(surf, start + i / fps, state)
            proc.stdin.write(pygame.image.tobytes(surf, "RGB"))
            if i % (fps * 5) == 0:
                print(f"  кадр {i}/{n_frames}", file=sys.stderr)
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError("ffmpeg завершився з помилкою")
    print(f"Збережено {out} ({n_frames} кадрів за {time.time() - t0:.1f} с)")


if __name__ == "__main__":
    main()
