"""Background music with narration-timed ducking: exact sentence windows, no level guessing."""
from __future__ import annotations
import shutil
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from .settings import PROJECT_ROOT, ResolvedHarnessSettings

LIBRARY_DIR = PROJECT_ROOT / "bgmusic"
RUN_MUSIC_DIR = Path("input") / "bgmusic"
TAIL_FADE_SECONDS = 2.0
MUSIC_SAMPLE_RATE = 48000


def resolve_music_file(run_dir: Path, settings: ResolvedHarnessSettings, *, library: Path | None = None) -> Path | None:
    """The run's own copy of the chosen bgmusic/ track (None when music is off)."""
    name = getattr(getattr(settings, "music", None), "file", "") or ""
    if not name.strip():
        return None
    source = (library or LIBRARY_DIR) / name
    if not source.is_file():
        raise FileNotFoundError(f"배경음악이 bgmusic/ 폴더에 없습니다: {source}")
    destination = Path(run_dir) / RUN_MUSIC_DIR / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.is_file() or destination.stat().st_size != source.stat().st_size:
        shutil.copyfile(source, destination)
    return destination


def score_master(run_dir: Path, *, source: Path, duration: float, fps: int,
                 settings: ResolvedHarnessSettings) -> None:
    """Score a freshly assembled narration master, preserving it if mixing fails."""
    track = resolve_music_file(run_dir, settings)
    if track is None:
        return
    from .subtitles import speech_spans
    destination = source.with_name(source.stem + '.music.tmp.mp4')
    try:
        add_music(subprocess.run, source=source, music_path=track, destination=destination,
                  duration=duration, cues=speech_spans(run_dir, 'ko', output_fps=fps), settings=settings)
        destination.replace(source)
    finally:
        destination.unlink(missing_ok=True)


def speech_intervals(cues: Sequence[tuple[float, float]], *, fade_seconds: float) -> list[tuple[float, float]]:
    """Speech spans, merging only overlaps: short pauses stay, so the music breathes between sentences.

    Merging gaps shorter than a full fade cycle pinned the duck for the whole film at shorts
    pacing (~0.15 s between sentences), so the music never lifted.
    """
    _ = fade_seconds
    merged: list[tuple[float, float]] = []
    for start, end in sorted(cues):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def duck_envelope_expression(intervals: Sequence[tuple[float, float]], *, fade_seconds: float) -> str:
    """0 outside speech, 1 during speech; ramps down before and up after each span over fade_seconds (FFmpeg expr in t)."""
    if not intervals:
        return "0"
    f = f"{fade_seconds:.3f}"
    terms = [f"(clip((t-{start - fade_seconds:.3f})/{f},0,1)*clip(({end + fade_seconds:.3f}-t)/{f},0,1))"
             for start, end in intervals]
    expr = terms[0]
    for term in terms[1:]:
        expr = f"max({expr},{term})"
    return expr


def music_filter_graph(*, duration: float, gain_db: float, duck_db: float, fade_seconds: float,
                       intervals: Sequence[tuple[float, float]], loop: bool, target_lufs: float, true_peak_db: float) -> str:
    envelope = duck_envelope_expression(intervals, fade_seconds=fade_seconds)
    limit = 10 ** (true_peak_db / 20)
    fade_start = max(0.0, duration - TAIL_FADE_SECONDS)
    music_chain = (
        f"[1:a]atrim=duration={duration:.3f},asetpts=PTS-STARTPTS,"
        f"loudnorm=I={target_lufs:.1f}:LRA=7:TP={true_peak_db:.1f},aresample={MUSIC_SAMPLE_RATE},"
        f"volume='pow(10,({gain_db:.1f}+{duck_db:.1f}*{envelope})/20)':eval=frame,"
        f"afade=t=out:st={fade_start:.3f}:d={TAIL_FADE_SECONDS:g}[music]"
    )
    mix = f"[0:a]aresample={MUSIC_SAMPLE_RATE}[voice];[voice][music]amix=inputs=2:normalize=0:duration=first,alimiter=limit={limit:.4f}[aout]"
    _ = loop  # looping is an input option (-stream_loop); kept in the signature for clarity of intent
    return music_chain + ";" + mix


def add_music(runner: Callable[..., subprocess.CompletedProcess], *, source: Path, music_path: Path, destination: Path,
              duration: float, cues: Sequence[tuple[float, float]], settings: ResolvedHarnessSettings) -> None:
    cfg = settings.music
    graph = music_filter_graph(duration=duration, gain_db=cfg.gain_db, duck_db=cfg.duck_db, fade_seconds=cfg.fade_seconds,
                               intervals=speech_intervals(cues, fade_seconds=cfg.fade_seconds), loop=cfg.loop_mode == "loop",
                               target_lufs=settings.voice.loudness_target_lufs, true_peak_db=settings.voice.loudness_true_peak_db)
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source)]
    if cfg.loop_mode == "loop":
        command += ["-stream_loop", "-1"]
    command += ["-i", str(music_path), "-filter_complex", graph, "-map", "0:v:0", "-map", "[aout]",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(destination)]
    completed = runner(command, capture_output=True, text=True)
    if getattr(completed, "returncode", 0):
        raise RuntimeError(f"배경음악 합성 실패 {destination.name}: {getattr(completed, 'stderr', '')[-800:]}")
    if not destination.is_file() or destination.stat().st_size == 0:
        raise RuntimeError(f"배경음악 합성 결과가 없습니다: {destination}")
