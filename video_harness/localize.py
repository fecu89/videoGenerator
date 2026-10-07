"""Narrated videos from one visual master, with optional burned subtitles and historical audio-only delivery."""
from __future__ import annotations
import json
import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from .creative_gates import _named_gate
from .media import AudioPlacement, EncoderSpec, OutputSpec, mux_audio_timeline, probe_media
from .sequence_plans import load_local_sequence_plan
from .sequence_render import _output_boundary
from .settings import ResolvedHarnessSettings, subtitle_language_list
from .subtitles import SUBTITLE_DIR, gate_name as subtitle_gate_name, speech_spans, write_subtitles
from .music import add_music, resolve_music_file

MASTER = "ko"


def language_outputs(settings: ResolvedHarnessSettings) -> list[str]:
    """['ko', *targets] for subtitle runs with targets; [] for every other run."""
    local_video = getattr(settings, "local_video", None)
    if getattr(local_video, "text_policy", "legacy") != "subtitles":
        return []
    targets = subtitle_language_list(settings)
    return [MASTER, *targets] if targets else []


def delivery_mode(settings: ResolvedHarnessSettings) -> str:
    return getattr(getattr(settings, "local_video", None), "localized_delivery", "burned_videos") or "burned_videos"


def final_name(lang: str, quality: str, delivery: str = "burned_videos") -> str:
    """Each language is an MP4, except historical audio_tracks delivery."""
    suffix = ".m4a" if delivery == "audio_tracks" else ".mp4"
    return f"final-{lang}{suffix}" if quality == "final" else f"final-draft-{lang}{suffix}"


def gate_file(quality: str) -> str:
    return f"localization-{quality}-gate.json"


def expected_language_outputs(settings: ResolvedHarnessSettings) -> set[str]:
    relatives: set[str] = set()
    delivery = delivery_mode(settings)
    for lang in language_outputs(settings):
        relatives.update({final_name(lang, "final", delivery), final_name(lang, "draft", delivery), f"{SUBTITLE_DIR}/{lang}.ass", f"{SUBTITLE_DIR}/{lang}.srt"})
    return relatives


def _language_audio(run: Path, lang: str, scene_audio: Mapping[int, str]) -> dict[int, Path]:
    if lang == MASTER:
        return {scene_id: run / relative for scene_id, relative in scene_audio.items()}
    from .localize_voice import language_audio_issues
    problems = language_audio_issues(run, lang)
    if problems:
        raise ValueError("\n".join(problems) + f"\n→ python -m video_harness voice runs/<run>/script.json --target-language {lang} --force")
    report_path = run / f"voice-generation-report-{lang}.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {"scenes": []}
    declared = {int(s["scene_id"]): s.get("audio_file") for s in report.get("scenes", [])}
    resolved: dict[int, Path] = {}
    for scene_id, relative in scene_audio.items():
        candidate = declared.get(scene_id) or f"audioFiles/{lang}/{Path(relative).name}"
        path = run / candidate
        if not path.is_file():
            raise FileNotFoundError(f"{lang} 음성이 없습니다: {candidate} (voice --target-language {lang})")
        resolved[scene_id] = path
    return resolved


def _placements(run: Path, audio: Mapping[int, Path], *, output_fps: int) -> list[AudioPlacement]:
    local = load_local_sequence_plan(run / "local-sequence-plan.json")
    canonical = local.defaults.fps
    placements: list[AudioPlacement] = []
    cursor = 0
    for sequence in local.sequences:
        for span in sequence.scene_spans:
            if span.scene_id not in audio:
                continue
            start = cursor + _output_boundary(span.audio_start_frame, output_fps=output_fps, canonical_fps=canonical)
            end = cursor + _output_boundary(span.audio_end_frame, output_fps=output_fps, canonical_fps=canonical)
            placements.append(AudioPlacement(source=audio[span.scene_id], start_frame=start, end_frame=end))
        cursor += _output_boundary(sequence.duration_frames, output_fps=output_fps, canonical_fps=canonical)
    return placements


_FILTER_SPECIALS = "\\:,'[];"


def ass_filter_argument(path: Path) -> str:
    """`ass=<path>` with libavfilter argument escaping so :,'[]; and backslashes in run paths survive."""
    escaped = "".join("\\" + ch if ch in _FILTER_SPECIALS else ch for ch in str(path))
    return f"ass={escaped}"


def _burn(runner: Callable[..., subprocess.CompletedProcess], source: Path, ass: Path, destination: Path, encoder: EncoderSpec) -> None:
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
               "-vf", ass_filter_argument(ass), "-c:v", "libx264", "-preset", encoder.preset, "-crf", str(encoder.crf),
               "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", str(destination)]
    completed = runner(command, capture_output=True, text=True)
    if getattr(completed, "returncode", 0):
        raise RuntimeError(f"자막 번인 실패 {destination.name}: {getattr(completed, 'stderr', '')[-800:]}")
    if not destination.is_file() or destination.stat().st_size == 0:
        raise RuntimeError(f"자막 번인 결과가 없습니다: {destination}")


def _extract_audio(runner: Callable[..., subprocess.CompletedProcess], source: Path, destination: Path) -> None:
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source), "-vn", "-c:a", "copy",
               "-movflags", "+faststart", str(destination)]
    completed = runner(command, capture_output=True, text=True)
    if getattr(completed, "returncode", 0):
        raise RuntimeError(f"오디오 트랙 추출 실패 {destination.name}: {getattr(completed, 'stderr', '')[-800:]}")
    if not destination.is_file() or destination.stat().st_size == 0:
        raise RuntimeError(f"오디오 트랙 결과가 없습니다: {destination}")


def localize_outputs(
    run_dir: Path,
    *,
    quality: str,
    artifact_root: Path,
    video_only: Path,
    scene_audio: Mapping[int, str],
    settings: ResolvedHarnessSettings,
    output_fps: int,
    width: int,
    height: int,
    frame_count: int,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> list[str]:
    run = Path(run_dir).resolve()
    root = Path(artifact_root).resolve()
    outputs: list[str] = []
    spec = OutputSpec(width=width, height=height, fps=output_fps, duration_seconds=frame_count / output_fps, frames=frame_count)
    encoder = EncoderSpec(preset=settings.render.x264_preset, crf=settings.render.x264_crf)
    music_path = resolve_music_file(run, settings)
    delivery = delivery_mode(settings)
    for lang in language_outputs(settings):
        audio = _language_audio(run, lang, scene_audio)   # current, gate-passed audio before any file is written
        ass = write_subtitles(run, lang, quality=quality, width=width, height=height, output_fps=output_fps, out_root=root)
        destination = root / final_name(lang, quality, delivery)
        muxed = destination.with_name(destination.stem + ".muxed.mp4")
        scored = destination.with_name(destination.stem + ".music.mp4")
        try:
            mux_audio_timeline(video_only, _placements(run, audio, output_fps=output_fps), muxed, spec, encoder=encoder)
            source = muxed
            if music_path is not None:
                # Background music ducked on this language's own sentence timing.
                add_music(runner, source=muxed, music_path=music_path, destination=scored, duration=spec.duration_seconds,
                          cues=speech_spans(run, lang, output_fps=output_fps), settings=settings)
                source = scored
            if delivery == "audio_tracks":
                _extract_audio(runner, source, destination)
            elif delivery == "videos":
                # Muxing already produced the complete film, including this language's music mix.
                source.replace(destination)
            else:
                _burn(runner, source, ass, destination, encoder)
        finally:
            for temp in (muxed, scored):
                if temp.exists():
                    temp.unlink()
        outputs.append(final_name(lang, quality, delivery))
    return outputs


def probe_audio_track(path: Path) -> tuple[float, str | None]:
    """(duration, audio codec) of an audio-only track; probe_media requires a video stream."""
    result = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                            text=True, capture_output=True, check=True)
    payload = json.loads(result.stdout)
    audio = next((stream for stream in payload.get("streams", []) if stream.get("codec_type") == "audio"), None)
    raw = payload.get("format", {}).get("duration") or (audio or {}).get("duration")
    if raw in (None, "N/A"):
        raise ValueError(f"오디오 길이를 확인할 수 없습니다: {path}")
    return float(raw), (str(audio["codec_name"]) if audio is not None else None)


def localization_issues(run: Path, root: Path, quality: str, languages: Sequence[str], delivery: str = "burned_videos") -> list[str]:
    master_name = "video-only.mp4" if quality == "final" else "video-only-draft.mp4"
    master_path = root / master_name
    if not master_path.is_file():
        return [f"localized_master_missing: {master_name}"]
    master = probe_media(master_path)
    tolerance = 1.0 / max(1.0, master.fps)
    errors: list[str] = []
    for lang in languages:
        path = root / final_name(lang, quality, delivery)
        if not path.is_file():
            errors.append(f"localized_missing: {lang} {path.name}")
            continue
        if delivery == "audio_tracks":
            # Audio tracks: only the timeline length must match (AAC priming may add a few ms).
            duration, codec = probe_audio_track(path)
            if abs(duration - master.duration_seconds) > max(tolerance, 0.1):
                errors.append(f"localized_length_mismatch: {lang} audio {duration:.3f}s vs master {master.duration_seconds:.3f}s")
        else:
            info = probe_media(path, require_audio=True)
            same_frames = info.frame_count is None or master.frame_count is None or abs(info.frame_count - master.frame_count) <= 1
            mismatch = not same_frames or abs(info.duration_seconds - master.duration_seconds) > tolerance or (info.width, info.height) != (master.width, master.height)
            if mismatch:
                errors.append(f"localized_length_mismatch: {lang} {info.frame_count}f/{info.duration_seconds:.3f}s/{info.width}x{info.height} vs master {master.frame_count}f/{master.duration_seconds:.3f}s/{master.width}x{master.height}")
            codec = info.audio_codec
        if not codec:
            errors.append(f"localized_no_audio: {lang}")
        gate = run / subtitle_gate_name(lang)
        status = json.loads(gate.read_text(encoding="utf-8")).get("status") if gate.is_file() else None
        if status != "passed":
            errors.append(f"subtitle_gate_failed: {lang} ({status})")
    return errors


def require_localization(run_dir: Path, artifact_root: Path, quality: str, languages: Sequence[str], delivery: str = "burned_videos") -> None:
    run = Path(run_dir).resolve()
    root = Path(artifact_root).resolve()
    try:
        errors = localization_issues(run, root, quality, languages, delivery)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        errors = [f"localization_unreadable: {error}"]
    _named_gate(run, gate_file(quality), errors, languages=list(languages), delivery=delivery, artifact_root=str(root))
