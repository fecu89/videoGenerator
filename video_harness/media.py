from __future__ import annotations

import json
import math
import subprocess
import tempfile
from collections.abc import Mapping
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence

from .performance import PerformanceRecorder
from .storage import atomic_write


@dataclass(frozen=True)
class MediaInfo:
    video_codec: str
    audio_codec: str | None
    width: int
    height: int
    fps: float
    duration_seconds: float
    frame_count: int | None = None
    pixel_format: str | None = None
    audio_duration_seconds: float | None = None
    audio_end_seconds: float | None = None
    video_time_base: str | None = None
    audio_sample_rate: int | None = None
    audio_channels: int | None = None
    audio_channel_layout: str | None = None


@dataclass(frozen=True)
class ConcatCompatibility:
    compatible: bool
    mismatched_fields: list[str]


@dataclass(frozen=True)
class ConcatResult:
    media: MediaInfo
    mode: Literal["stream_copy", "normalized_reencode"]
    normalized_inputs: int = 0

    def __getattr__(self, name: str) -> object:
        """Keep existing MediaInfo consumers source-compatible during the migration."""
        return getattr(self.media, name)


@dataclass(frozen=True)
class OutputSpec:
    width: int
    height: int
    fps: int
    duration_seconds: float
    frames: int | None = None

    @property
    def frame_count(self) -> int:
        return self.frames if self.frames is not None else round(self.duration_seconds * self.fps)


@dataclass(frozen=True)
class EncoderSpec:
    preset: str
    crf: int


DEFAULT_ENCODER_SPEC = EncoderSpec(preset="medium", crf=18)


@dataclass(frozen=True)
class AudioPlacement:
    source: Path
    start_frame: int
    end_frame: int


def _fraction(value: str) -> float:
    numerator, separator, denominator = value.partition("/")
    if not separator:
        return float(value)
    divisor = float(denominator)
    return float(numerator) / divisor if divisor else 0.0


def compare_concat_inputs(
    inputs: Sequence[MediaInfo], *, require_audio: bool
) -> ConcatCompatibility:
    """Report stream attributes that make an FFmpeg concat stream-copy unsafe."""
    if not inputs:
        raise ValueError("합칠 영상이 없습니다.")
    fields = [
        "video_codec",
        "width",
        "height",
        "fps",
        "pixel_format",
        "video_time_base",
    ]
    if require_audio:
        fields.extend(
            [
                "audio_codec",
                "audio_sample_rate",
                "audio_channels",
                "audio_channel_layout",
            ]
        )
    first = inputs[0]
    mismatched = [
        field
        for field in fields
        if any(getattr(item, field) != getattr(first, field) for item in inputs[1:])
    ]
    return ConcatCompatibility(
        compatible=not mismatched,
        mismatched_fields=mismatched,
    )


def probe_media(path: Path, *, require_audio: bool = False) -> MediaInfo:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-count_frames",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)
    video = next(
        (stream for stream in payload["streams"] if stream.get("codec_type") == "video"),
        None,
    )
    audio = next(
        (stream for stream in payload["streams"] if stream.get("codec_type") == "audio"),
        None,
    )
    if video is None:
        raise ValueError(f"영상 스트림이 없습니다: {path}")
    if require_audio and audio is None:
        raise ValueError(f"음성 스트림이 없습니다: {path}")
    raw_duration = payload.get("format", {}).get("duration") or video.get("duration")
    if raw_duration is None:
        raise ValueError(f"영상 길이를 확인할 수 없습니다: {path}")
    raw_frames = video.get("nb_read_frames") or video.get("nb_frames")
    raw_audio_duration = audio.get("duration") if audio is not None else None
    audio_duration = (
        float(raw_audio_duration)
        if raw_audio_duration not in (None, "N/A")
        else None
    )
    raw_audio_start = audio.get("start_time") if audio is not None else None
    audio_start = (
        float(raw_audio_start)
        if raw_audio_start not in (None, "N/A")
        else 0.0
    )
    return MediaInfo(
        video_codec=str(video["codec_name"]),
        audio_codec=str(audio["codec_name"]) if audio is not None else None,
        width=int(video["width"]),
        height=int(video["height"]),
        fps=_fraction(str(video.get("r_frame_rate") or video["avg_frame_rate"])),
        duration_seconds=float(raw_duration),
        frame_count=int(raw_frames) if raw_frames not in (None, "N/A") else None,
        pixel_format=str(video.get("pix_fmt")) if video.get("pix_fmt") else None,
        audio_duration_seconds=audio_duration,
        audio_end_seconds=(
            audio_start + audio_duration if audio_duration is not None else None
        ),
        video_time_base=str(video.get("time_base")) if video.get("time_base") else None,
        audio_sample_rate=(
            int(audio["sample_rate"])
            if audio is not None and audio.get("sample_rate") not in (None, "N/A")
            else None
        ),
        audio_channels=(
            int(audio["channels"])
            if audio is not None and audio.get("channels") not in (None, "N/A")
            else None
        ),
        audio_channel_layout=(
            str(audio.get("channel_layout"))
            if audio is not None and audio.get("channel_layout")
            else None
        ),
    )


def validate_media(
    info: MediaInfo,
    spec: OutputSpec,
    *,
    require_audio: bool,
) -> None:
    if info.video_codec != "h264":
        raise ValueError(f"예상하지 못한 영상 코덱입니다: {info.video_codec}")
    if require_audio and info.audio_codec != "aac":
        raise ValueError(f"예상하지 못한 코덱입니다: {info.video_codec}/{info.audio_codec}")
    if not require_audio and info.audio_codec is not None:
        raise ValueError(f"무음 원본에 음성 스트림이 있습니다: {info.audio_codec}")
    if (info.width, info.height) != (spec.width, spec.height):
        raise ValueError(f"영상 크기가 다릅니다: {info.width}x{info.height}")
    if abs(info.fps - spec.fps) > 0.01:
        raise ValueError(f"프레임률이 다릅니다: {info.fps}")
    if info.frame_count is not None and info.frame_count != spec.frame_count:
        raise ValueError(
            f"프레임 수가 다릅니다: {info.frame_count} / {spec.frame_count}"
        )
    if abs(info.duration_seconds - spec.duration_seconds) > (1 / spec.fps + 0.01):
        raise ValueError(
            f"영상 길이가 다릅니다: {info.duration_seconds:.3f}초 / "
            f"{spec.duration_seconds:.3f}초"
        )


def _temporary_output(destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp" + destination.suffix)
    if temporary.exists():
        temporary.unlink()
    return temporary


def normalize_video(
    source: Path,
    destination: Path,
    spec: OutputSpec,
    *,
    encoder: EncoderSpec = DEFAULT_ENCODER_SPEC,
) -> MediaInfo:
    temporary = _temporary_output(destination)
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(source),
                "-map",
                "0:v:0",
                "-vf",
                (
                    f"scale={spec.width}:{spec.height}:force_original_aspect_ratio=decrease,"
                    f"pad={spec.width}:{spec.height}:(ow-iw)/2:(oh-ih)/2,"
                    f"fps={spec.fps}"
                ),
                "-frames:v",
                str(spec.frame_count),
                "-c:v",
                "libx264",
                "-preset",
                encoder.preset,
                "-crf",
                str(encoder.crf),
                "-pix_fmt",
                "yuv420p",
                "-an",
                "-movflags",
                "+faststart",
                str(temporary),
            ],
            check=True,
        )
        info = probe_media(temporary)
        validate_media(info, spec, require_audio=False)
        temporary.replace(destination)
        return info
    finally:
        if temporary.exists():
            temporary.unlink()


def extract_video_segment(
    source: Path,
    destination: Path,
    *,
    start_frame: int,
    end_frame: int,
    fps: int,
    encoder: EncoderSpec = DEFAULT_ENCODER_SPEC,
) -> MediaInfo:
    if start_frame < 0:
        raise ValueError("start_frame must be non-negative")
    if end_frame <= start_frame:
        raise ValueError("end_frame must exceed start_frame")
    if fps <= 0:
        raise ValueError("fps must be positive")
    source_info = probe_media(source)
    if abs(source_info.fps - fps) > 0.01:
        raise ValueError(f"source frame rate differs from requested fps: {source_info.fps}")
    if source_info.frame_count is not None and end_frame > source_info.frame_count:
        raise ValueError(
            f"segment end_frame exceeds source timeline: {end_frame} / "
            f"{source_info.frame_count}"
        )
    spec = OutputSpec(
        width=source_info.width,
        height=source_info.height,
        fps=fps,
        duration_seconds=(end_frame - start_frame) / fps,
        frames=end_frame - start_frame,
    )
    temporary = _temporary_output(destination)
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(source),
                "-map",
                "0:v:0",
                "-vf",
                (
                    f"trim=start_frame={start_frame}:end_frame={end_frame},"
                    "setpts=PTS-STARTPTS"
                ),
                "-frames:v",
                str(spec.frame_count),
                "-c:v",
                "libx264",
                "-preset",
                encoder.preset,
                "-crf",
                str(encoder.crf),
                "-pix_fmt",
                "yuv420p",
                "-an",
                "-movflags",
                "+faststart",
                str(temporary),
            ],
            check=True,
        )
        info = probe_media(temporary)
        validate_media(info, spec, require_audio=False)
        temporary.replace(destination)
        return info
    finally:
        if temporary.exists():
            temporary.unlink()


def encode_frames(
    frame_pattern: Path,
    destination: Path,
    spec: OutputSpec,
    *,
    encoder: EncoderSpec = DEFAULT_ENCODER_SPEC,
) -> MediaInfo:
    temporary = _temporary_output(destination)
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-framerate",
                str(spec.fps),
                "-i",
                str(frame_pattern),
                "-frames:v",
                str(spec.frame_count),
                "-c:v",
                "libx264",
                "-preset",
                encoder.preset,
                "-crf",
                str(encoder.crf),
                "-pix_fmt",
                "yuv420p",
                "-an",
                "-movflags",
                "+faststart",
                str(temporary),
            ],
            check=True,
        )
        info = probe_media(temporary)
        validate_media(info, spec, require_audio=False)
        temporary.replace(destination)
        return info
    finally:
        if temporary.exists():
            temporary.unlink()


def mux_audio(
    video: Path,
    audio: Path,
    destination: Path,
    spec: OutputSpec,
    *,
    encoder: EncoderSpec = DEFAULT_ENCODER_SPEC,
) -> MediaInfo:
    # Video is stream-copied to retain exact frame boundaries; retain the encoder
    # argument so every public render boundary carries one explicit media policy.
    _ = encoder
    temporary = _temporary_output(destination)
    frame_aligned_duration = spec.frame_count / spec.fps
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(video),
                "-i",
                str(audio),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "copy",
                "-af",
                (
                    f"apad=pad_dur={frame_aligned_duration:.9f},"
                    f"atrim=duration={frame_aligned_duration:.9f},"
                    "asetpts=PTS-STARTPTS"
                ),
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-movflags",
                "+faststart",
                str(temporary),
            ],
            check=True,
        )
        info = probe_media(temporary, require_audio=True)
        validate_media(info, spec, require_audio=True)
        temporary.replace(destination)
        return info
    finally:
        if temporary.exists():
            temporary.unlink()


def mux_audio_timeline(
    video: Path,
    placements: Sequence[AudioPlacement],
    destination: Path,
    spec: OutputSpec,
    *,
    encoder: EncoderSpec = DEFAULT_ENCODER_SPEC,
) -> MediaInfo:
    _ = encoder
    if not placements:
        raise ValueError("audio timeline requires at least one placement")
    ordered = sorted(placements, key=lambda item: (item.start_frame, item.end_frame))
    previous_end = 0
    for placement in ordered:
        if placement.start_frame < 0 or placement.end_frame <= placement.start_frame:
            raise ValueError("audio placement requires a positive half-open frame range")
        if placement.end_frame > spec.frame_count:
            raise ValueError("audio placement falls outside the video timeline")
        if placement.start_frame < previous_end:
            raise ValueError("audio placements must not overlap")
        previous_end = placement.end_frame

    temporary = _temporary_output(destination)
    duration = spec.frame_count / spec.fps
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(video),
    ]
    for placement in ordered:
        command.extend(["-i", str(placement.source)])

    filters: list[str] = []
    labels: list[str] = []
    for index, placement in enumerate(ordered, start=1):
        clip_duration = (placement.end_frame - placement.start_frame) / spec.fps
        delay_ms = round(placement.start_frame * 1000 / spec.fps)
        label = f"a{index}"
        filters.append(
            f"[{index}:a]atrim=duration={clip_duration:.9f},"
            f"asetpts=PTS-STARTPTS,adelay={delay_ms}:all=1[{label}]"
        )
        labels.append(f"[{label}]")
    filters.append(
        f"anullsrc=r=24000:cl=mono:d={duration:.9f}[timeline_silence]"
    )
    labels.append("[timeline_silence]")
    filters.append(
        f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0,"
        f"apad=pad_dur={duration:.9f},atrim=duration={duration:.9f}[aout]"
    )
    command.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "0:v:0",
            "-map",
            "[aout]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(temporary),
        ]
    )
    try:
        subprocess.run(command, check=True)
        info = probe_media(temporary, require_audio=True)
        validate_media(info, spec, require_audio=True)
        temporary.replace(destination)
        return info
    finally:
        if temporary.exists():
            temporary.unlink()


def preview_timestamps(duration_seconds: float, interval_seconds: float) -> list[float]:
    timestamps: list[float] = []
    index = 0
    while index * interval_seconds < duration_seconds - 1e-9:
        timestamps.append(round(index * interval_seconds, 6))
        index += 1
    return timestamps


def capture_preview_frames(
    source: Path,
    output_directory: Path,
    timestamps: Sequence[float],
    names: Sequence[str],
) -> list[Path]:
    if len(timestamps) != len(names):
        raise ValueError("preview timestamp and filename counts differ")
    output_directory.mkdir(parents=True, exist_ok=True)
    expected_names = set(names)
    for stale in output_directory.glob("*.png"):
        if stale.name not in expected_names:
            stale.unlink()
    paths: list[Path] = []
    for timestamp, name in zip(timestamps, names, strict=True):
        destination = output_directory / name
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                f"{timestamp:.6f}",
                "-i",
                str(source),
                "-map",
                "0:v:0",
                "-frames:v",
                "1",
                str(destination),
            ],
            check=True,
        )
        paths.append(destination)
    return paths


def capture_previews(
    source: Path,
    output_directory: Path,
    interval_seconds: float,
) -> list[Path]:
    info = probe_media(source)
    timestamps = preview_timestamps(info.duration_seconds, interval_seconds)
    names = [f"{round(timestamp * 1000):04d}ms.png" for timestamp in timestamps]
    return capture_preview_frames(source, output_directory, timestamps, names)


def create_contact_sheet(
    source: Path,
    destination: Path,
    interval_seconds: float = 0.5,
    columns: int = 8,
) -> Path:
    if interval_seconds <= 0:
        raise ValueError("contact-sheet interval must be positive")
    if columns <= 0:
        raise ValueError("contact-sheet columns must be positive")
    info = probe_media(source)
    sample_count = len(preview_timestamps(info.duration_seconds, interval_seconds))
    if sample_count < 1:
        raise ValueError("contact-sheet source has no sampleable frames")
    rows = math.ceil(sample_count / columns)
    temporary = _temporary_output(destination)
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(source),
                "-vf",
                (
                    f"fps=fps={1 / interval_seconds:.9f}:start_time=0,"
                    "scale=320:-2:flags=lanczos,"
                    f"tile={columns}x{rows}:nb_frames={sample_count}:padding=2:margin=2"
                ),
                "-frames:v",
                "1",
                str(temporary),
            ],
            check=True,
        )
        temporary.replace(destination)
        return destination
    finally:
        if temporary.exists():
            temporary.unlink()


def _concat_stream_copy(
    inputs: Sequence[Path],
    destination: Path,
    *,
    expected_duration: float,
    require_audio: bool,
) -> MediaInfo:
    if not inputs:
        raise ValueError("합칠 영상이 없습니다.")
    list_path = destination.with_suffix(".concat.txt")
    temporary = _temporary_output(destination)
    lines = []
    for path in inputs:
        escaped = str(path.resolve()).replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    atomic_write(list_path, "\n".join(lines) + "\n")
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_path),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(temporary),
            ],
            check=True,
        )
        info = probe_media(temporary, require_audio=require_audio)
        if abs(info.duration_seconds - expected_duration) > 0.2:
            raise ValueError(
                f"합본 길이가 다릅니다: {info.duration_seconds:.3f}초 / "
                f"{expected_duration:.3f}초"
            )
        temporary.replace(destination)
        return info
    finally:
        if list_path.exists():
            list_path.unlink()
        if temporary.exists():
            temporary.unlink()


def _time_base_scale(time_base: str | None) -> int:
    if time_base is None:
        raise ValueError("concat normalization requires a video time base")
    numerator, separator, denominator = time_base.partition("/")
    if separator != "/" or numerator != "1" or not denominator.isdigit():
        raise ValueError(f"unsupported concat video time base: {time_base}")
    scale = int(denominator)
    if scale <= 0:
        raise ValueError(f"unsupported concat video time base: {time_base}")
    return scale


def _normalize_concat_input(
    source: Path,
    destination: Path,
    reference: MediaInfo,
    source_info: MediaInfo,
    *,
    require_audio: bool,
    encoder: EncoderSpec,
) -> MediaInfo:
    """Re-encode one concat input to the first input's explicit stream spec."""
    source_duration = (
        source_info.frame_count / source_info.fps
        if source_info.frame_count is not None
        else source_info.duration_seconds
    )
    output_frame_count = round(source_duration * reference.fps)
    if output_frame_count <= 0:
        raise ValueError("concat normalization requires at least one video frame")
    output_duration = output_frame_count / reference.fps
    temporary = _temporary_output(destination)
    try:
        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-map",
            "0:v:0",
            "-vf",
            (
                f"scale={reference.width}:{reference.height}:force_original_aspect_ratio=decrease,"
                f"pad={reference.width}:{reference.height}:(ow-iw)/2:(oh-ih)/2,"
                f"fps={reference.fps}"
            ),
            "-frames:v",
            str(output_frame_count),
            "-c:v",
            "libx264",
            "-preset",
            encoder.preset,
            "-crf",
            str(encoder.crf),
            "-pix_fmt",
            reference.pixel_format or "yuv420p",
            "-video_track_timescale",
            str(_time_base_scale(reference.video_time_base)),
        ]
        if require_audio:
            if (
                reference.audio_sample_rate is None
                or reference.audio_channels is None
                or reference.audio_channel_layout is None
            ):
                raise ValueError("concat normalization requires complete audio stream details")
            command.extend(
                [
                    "-map",
                    "0:a:0",
                    "-af",
                    (
                        f"apad=pad_dur={output_duration:.9f},"
                        f"atrim=duration={output_duration:.9f},"
                        "asetpts=PTS-STARTPTS"
                    ),
                    "-c:a",
                    "aac",
                    "-ar",
                    str(reference.audio_sample_rate),
                    "-ac",
                    str(reference.audio_channels),
                    "-channel_layout",
                    reference.audio_channel_layout,
                ]
            )
        else:
            command.append("-an")
        command.extend(
            [
                "-t",
                f"{output_duration:.9f}",
                "-movflags",
                "+faststart",
                str(temporary),
            ]
        )
        subprocess.run(command, check=True)
        info = probe_media(temporary, require_audio=require_audio)
        temporary.replace(destination)
        return info
    finally:
        if temporary.exists():
            temporary.unlink()


def _preflight_concat_inputs(
    inputs: Sequence[Path],
    *,
    normalized_root: Path,
    require_audio: bool,
    encoder: EncoderSpec,
) -> tuple[list[Path], ConcatCompatibility, int]:
    resolved = [path.resolve() for path in inputs]
    infos = [probe_media(path, require_audio=require_audio) for path in resolved]
    compatibility = compare_concat_inputs(infos, require_audio=require_audio)
    if compatibility.compatible:
        return resolved, compatibility, 0

    normalized: list[Path] = []
    normalized_infos: list[MediaInfo] = []
    for index, source in enumerate(resolved):
        path = normalized_root / f"normalized-{index:03d}.mp4"
        normalized_infos.append(
            _normalize_concat_input(
                source,
                path,
                infos[0],
                infos[index],
                require_audio=require_audio,
                encoder=encoder,
            )
        )
        normalized.append(path)
    normalized_compatibility = compare_concat_inputs(
        normalized_infos, require_audio=require_audio
    )
    if not normalized_compatibility.compatible:
        raise ValueError(
            "normalized concat inputs remain incompatible: "
            + ", ".join(normalized_compatibility.mismatched_fields)
        )
    return normalized, compatibility, len(normalized)


def _create_dip_to_black_transition(
    previous: Path,
    following: Path,
    destination: Path,
    *,
    duration_seconds: float,
    fade_seconds: float,
    require_audio: bool,
    encoder: EncoderSpec,
) -> MediaInfo:
    previous_info = probe_media(previous, require_audio=require_audio)
    following_info = probe_media(following, require_audio=require_audio)
    if (
        previous_info.width,
        previous_info.height,
        round(previous_info.fps, 6),
    ) != (
        following_info.width,
        following_info.height,
        round(following_info.fps, 6),
    ):
        raise ValueError("전환할 영상의 해상도와 FPS가 다릅니다.")

    fps = round(previous_info.fps)
    frame_count = max(4, round(duration_seconds * fps))
    actual_duration = frame_count / fps
    first_frames = math.ceil(frame_count / 2)
    second_frames = frame_count - first_frames
    first_duration = first_frames / fps
    second_duration = second_frames / fps
    fade = min(fade_seconds, first_duration, second_duration)
    second_fade_start = max(0.0, second_duration - fade)

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="video-transition-",
        dir=destination.parent,
    ) as temporary_directory:
        temporary_root = Path(temporary_directory)
        previous_frame = temporary_root / "previous" / "frame.png"
        following_frame = temporary_root / "following" / "frame.png"
        previous_video_duration = (
            previous_info.frame_count / fps
            if previous_info.frame_count is not None
            else previous_info.duration_seconds
        )
        capture_preview_frames(
            previous,
            previous_frame.parent,
            [max(0.0, previous_video_duration - 1 / fps)],
            [previous_frame.name],
        )
        capture_preview_frames(
            following,
            following_frame.parent,
            [0.0],
            [following_frame.name],
        )

        filter_complex = (
            f"[0:v]trim=duration={first_duration:.9f},setpts=PTS-STARTPTS,"
            f"fade=t=out:st=0:d={fade:.9f}[outgoing];"
            f"[1:v]trim=duration={second_duration:.9f},setpts=PTS-STARTPTS,"
            f"fade=t=in:st={second_fade_start:.9f}:d={fade:.9f}[incoming];"
            f"[outgoing][incoming]concat=n=2:v=1:a=0,fps={fps},"
            "format=yuv420p[video]"
        )
        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-loop",
            "1",
            "-framerate",
            str(fps),
            "-i",
            str(previous_frame),
            "-loop",
            "1",
            "-framerate",
            str(fps),
            "-i",
            str(following_frame),
        ]
        if require_audio:
            command.extend(
                [
                    "-f",
                    "lavfi",
                    "-i",
                    "anullsrc=r=24000:cl=mono",
                ]
            )
        command.extend(
            [
                "-filter_complex",
                filter_complex,
                "-map",
                "[video]",
            ]
        )
        if require_audio:
            command.extend(["-map", "2:a:0", "-c:a", "aac", "-b:a", "192k"])
        else:
            command.append("-an")
        command.extend(
            [
                "-frames:v",
                str(frame_count),
                "-t",
                f"{actual_duration:.9f}",
                "-c:v",
                "libx264",
                "-preset",
                encoder.preset,
                "-crf",
                str(encoder.crf),
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(destination),
            ]
        )
        subprocess.run(command, check=True)

    info = probe_media(destination, require_audio=require_audio)
    validate_media(
        info,
        OutputSpec(
            width=previous_info.width,
            height=previous_info.height,
            fps=fps,
            duration_seconds=actual_duration,
            frames=frame_count,
        ),
        require_audio=require_audio,
    )
    return info


def concat_videos(
    inputs: Sequence[Path],
    destination: Path,
    *,
    expected_duration: float,
    require_audio: bool,
    transition_seconds: float = 0.0,
    transition_fade_seconds: float = 0.0,
    encoder: EncoderSpec = DEFAULT_ENCODER_SPEC,
    performance: PerformanceRecorder | None = None,
    performance_labels: Mapping[str, object] | None = None,
) -> ConcatResult:
    if not inputs:
        raise ValueError("합칠 영상이 없습니다.")
    if transition_fade_seconds <= 0 or transition_fade_seconds * 2 > transition_seconds:
        if transition_seconds > 0 and len(inputs) >= 2:
            raise ValueError("전환 페이드 길이가 전체 전환 길이에 맞지 않습니다.")

    destination.parent.mkdir(parents=True, exist_ok=True)
    phase_labels: dict[str, object] = {
        "mode": "stream_copy",
        "mismatched_fields": "",
        "normalized_inputs": 0,
        **dict(performance_labels or {}),
    }
    phase = (
        performance.phase(
            "concat",
            **phase_labels,
        )
        if performance is not None
        else nullcontext({})
    )
    with phase as labels:
        with tempfile.TemporaryDirectory(
            prefix="video-concat-",
            dir=destination.parent,
        ) as temporary_directory:
            temporary_root = Path(temporary_directory)
            prepared, compatibility, normalized_count = _preflight_concat_inputs(
                inputs,
                normalized_root=temporary_root / "inputs",
                require_audio=require_audio,
                encoder=encoder,
            )
            if transition_seconds <= 0 or len(prepared) < 2:
                media = _concat_stream_copy(
                    prepared,
                    destination,
                    expected_duration=expected_duration,
                    require_audio=require_audio,
                )
                result = ConcatResult(
                    media=media,
                    mode=("normalized_reencode" if normalized_count else "stream_copy"),
                    normalized_inputs=normalized_count,
                )
                labels.update(
                    mode=result.mode,
                    mismatched_fields=",".join(compatibility.mismatched_fields),
                    normalized_inputs=result.normalized_inputs,
                )
                return result

            expanded: list[Path] = []
            for index, current in enumerate(prepared):
                expanded.append(current)
                if index == len(prepared) - 1:
                    continue
                transition = temporary_root / f"transition-{index + 1:03d}.mp4"
                _create_dip_to_black_transition(
                    current,
                    prepared[index + 1],
                    transition,
                    duration_seconds=transition_seconds,
                    fade_seconds=transition_fade_seconds,
                    require_audio=require_audio,
                    encoder=encoder,
                )
                expanded.append(transition)
            expanded_inputs, expanded_compatibility, expanded_normalized_count = (
                _preflight_concat_inputs(
                    expanded,
                    normalized_root=temporary_root / "expanded",
                    require_audio=require_audio,
                    encoder=encoder,
                )
            )
            media = _concat_stream_copy(
                expanded_inputs,
                destination,
                expected_duration=expected_duration,
                require_audio=require_audio,
            )
            total_normalized = normalized_count + expanded_normalized_count
            mismatched_fields = list(
                dict.fromkeys(
                    [
                        *compatibility.mismatched_fields,
                        *expanded_compatibility.mismatched_fields,
                    ]
                )
            )
            result = ConcatResult(
                media=media,
                mode=("normalized_reencode" if total_normalized else "stream_copy"),
                normalized_inputs=total_normalized,
            )
            labels.update(
                mode=result.mode,
                mismatched_fields=",".join(mismatched_fields),
                normalized_inputs=result.normalized_inputs,
            )
            return result
