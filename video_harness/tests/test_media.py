from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from video_harness.media import (
    AudioPlacement,
    compare_concat_inputs,
    EncoderSpec,
    MediaInfo,
    OutputSpec,
    capture_previews,
    concat_videos,
    extract_video_segment,
    mux_audio,
    mux_audio_timeline,
    normalize_video,
    preview_timestamps,
    probe_media,
)
from video_harness.performance import PerformanceRecorder


pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg is required",
)


def make_source(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=160x90:rate=10:duration=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(path),
        ],
        check=True,
    )


def media_info(**overrides: object) -> MediaInfo:
    values: dict[str, object] = {
        "video_codec": "h264",
        "audio_codec": "aac",
        "width": 160,
        "height": 90,
        "fps": 10.0,
        "duration_seconds": 1.0,
        "frame_count": 10,
        "pixel_format": "yuv420p",
        "video_time_base": "1/10240",
        "audio_sample_rate": 24000,
        "audio_channels": 1,
        "audio_channel_layout": "mono",
    }
    values.update(overrides)
    return MediaInfo(**values)


def test_concat_preflight_requires_matching_time_base_and_audio_layout():
    """A stream copy must not join inputs with incompatible stream timing/layout."""
    left = media_info(video_time_base="1/15360", audio_channel_layout="mono")
    right = media_info(video_time_base="1/90000", audio_channel_layout="stereo")

    result = compare_concat_inputs([left, right], require_audio=True)

    assert result.compatible is False
    assert result.mismatched_fields == ["video_time_base", "audio_channel_layout"]


def test_concat_preflight_normalizes_and_reprobes_incompatible_inputs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """Incompatible streams are explicitly re-encoded before the concat demuxer runs."""
    left_path = tmp_path / "left.mp4"
    right_path = tmp_path / "right.mp4"
    destination = tmp_path / "joined.mp4"
    left_path.write_bytes(b"left")
    right_path.write_bytes(b"right")
    commands: list[list[str]] = []
    probes: list[Path] = []
    left = media_info(video_time_base="1/15360", audio_channel_layout="mono")
    right = media_info(video_time_base="1/90000", audio_channel_layout="stereo")

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        Path(command[-1]).write_bytes(b"video")
        return subprocess.CompletedProcess(command, 0)

    def fake_probe(path: Path, *, require_audio: bool = False) -> MediaInfo:
        probes.append(path)
        if path == left_path.resolve():
            return left
        if path == right_path.resolve():
            return right
        if path.name == "joined.tmp.mp4":
            return media_info(duration_seconds=2.0, frame_count=20)
        return left

    monkeypatch.setattr("video_harness.media.subprocess.run", fake_run)
    monkeypatch.setattr("video_harness.media.probe_media", fake_probe)
    recorder = PerformanceRecorder()

    result = concat_videos(
        [left_path, right_path],
        destination,
        expected_duration=2.0,
        require_audio=True,
        performance=recorder,
    )

    assert result.mode == "normalized_reencode"
    assert result.normalized_inputs == 2
    assert probes[:2] == [left_path.resolve(), right_path.resolve()]
    assert len(commands) == 3
    assert commands[-1][commands[-1].index("-c") + 1] == "copy"
    assert all(
        "-video_track_timescale" in command
        for command in commands[:-1]
    )
    event = next(event for event in recorder.report().phase_events if event.name == "concat")
    assert event.labels == {
        "mismatched_fields": "video_time_base,audio_channel_layout",
        "mode": "normalized_reencode",
        "normalized_inputs": "2",
    }


def test_concat_normalization_trims_aac_to_each_video_timeline(tmp_path: Path):
    """Long AAC tracks must not extend a normalized concat past its video frames."""
    inputs: list[Path] = []
    for index, time_scale in enumerate((15360, 90000), start=1):
        path = tmp_path / f"input-{index}.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=160x90:rate=10:duration=0.5",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:sample_rate=24000:duration=1",
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-video_track_timescale",
                str(time_scale),
                "-c:a",
                "aac",
                str(path),
            ],
            check=True,
        )
        inputs.append(path)

    result = concat_videos(
        inputs,
        tmp_path / "joined.mp4",
        expected_duration=1.0,
        require_audio=True,
    )

    assert result.mode == "normalized_reencode"
    assert result.media.frame_count == 10
    assert result.media.fps == 10.0
    assert result.media.duration_seconds == pytest.approx(1.0, abs=0.06)
    assert result.media.audio_end_seconds is not None
    assert result.media.audio_end_seconds == pytest.approx(1.0, abs=0.06)


def test_concat_normalization_pads_short_aac_without_truncating_video(
    tmp_path: Path,
):
    """A short input AAC track must become aligned silence, never shorten video."""
    inputs: list[Path] = []
    for index, (time_scale, audio_duration) in enumerate(
        ((15360, 0.2), (90000, 1.0)), start=1
    ):
        path = tmp_path / f"input-{index}.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=160x90:rate=10:duration=1",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency=440:sample_rate=24000:duration={audio_duration}",
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-video_track_timescale",
                str(time_scale),
                "-c:a",
                "aac",
                str(path),
            ],
            check=True,
        )
        inputs.append(path)

    result = concat_videos(
        inputs,
        tmp_path / "joined.mp4",
        expected_duration=2.0,
        require_audio=True,
    )

    assert result.mode == "normalized_reencode"
    assert result.media.frame_count == 20
    assert result.media.fps == 10.0
    assert result.media.duration_seconds == pytest.approx(2.0, abs=0.06)
    assert result.media.audio_duration_seconds == pytest.approx(2.0, abs=0.06)


def test_concat_performance_phase_times_preflight_and_stream_copy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Concat telemetry must time the work, not an empty reporting context."""
    now = [10.0]
    recorder = PerformanceRecorder(clock=lambda: now[0])
    compatibility = compare_concat_inputs([media_info()], require_audio=False)

    def fake_preflight(*_args: object, **_kwargs: object):
        now[0] += 0.25
        return [tmp_path / "input.mp4"], compatibility, 0

    def fake_concat(*_args: object, **_kwargs: object) -> MediaInfo:
        now[0] += 0.75
        return media_info(audio_codec=None)

    monkeypatch.setattr("video_harness.media._preflight_concat_inputs", fake_preflight)
    monkeypatch.setattr("video_harness.media._concat_stream_copy", fake_concat)

    concat_videos(
        [tmp_path / "input.mp4"],
        tmp_path / "joined.mp4",
        expected_duration=1.0,
        require_audio=False,
        performance=recorder,
        performance_labels={"variant_id": "explain", "output_kind": "narrated"},
    )

    event = next(event for event in recorder.report().phase_events if event.name == "concat")
    assert event.duration_ms == 1000.0
    assert event.labels == {
        "mismatched_fields": "",
        "mode": "stream_copy",
        "normalized_inputs": "0",
        "output_kind": "narrated",
        "variant_id": "explain",
    }


def make_silent_video(path: Path, *, duration: float, fps: int = 10) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=white:size=160x90:rate={fps}:duration={duration}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(path),
        ],
        check=True,
    )


def make_audio(path: Path, *, duration: float) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:sample_rate=24000:duration={duration}",
            "-codec:a",
            "libmp3lame",
            str(path),
        ],
        check=True,
    )


def frame_rgb(path: Path, timestamp: float) -> tuple[int, int, int]:
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            str(timestamp),
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-vf",
            "scale=1:1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ],
        capture_output=True,
        check=True,
    )
    return tuple(result.stdout[:3])


def audio_rms(path: Path, *, start: float, duration: float) -> float:
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            str(start),
            "-t",
            str(duration),
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-f",
            "s16le",
            "-ac",
            "1",
            "-ar",
            "24000",
            "pipe:1",
        ],
        capture_output=True,
        check=True,
    )
    samples = [
        int.from_bytes(result.stdout[index : index + 2], "little", signed=True)
        for index in range(0, len(result.stdout) - 1, 2)
    ]
    return (sum(sample * sample for sample in samples) / len(samples)) ** 0.5


def test_normalize_video_strips_audio_and_uses_exact_frames(tmp_path: Path):
    source = tmp_path / "source.mp4"
    output = tmp_path / "normalized.mp4"
    make_source(source)

    info = normalize_video(
        source,
        output,
        OutputSpec(width=160, height=90, fps=10, duration_seconds=0.6),
    )

    assert info.audio_codec is None
    assert info.frame_count == 6
    assert (info.width, info.height, info.fps) == (160, 90, 10.0)


def test_normalize_video_uses_explicit_encoder_spec(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    source = tmp_path / "source.mp4"
    destination = tmp_path / "normalized.mp4"
    source.write_bytes(b"source")
    commands: list[list[str]] = []
    spec = OutputSpec(width=160, height=90, fps=10, duration_seconds=0.6)

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        Path(command[-1]).write_bytes(b"video")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("video_harness.media.subprocess.run", fake_run)
    monkeypatch.setattr(
        "video_harness.media.probe_media",
        lambda _path: MediaInfo("h264", None, 160, 90, 10.0, 0.6, 6),
    )

    normalize_video(
        source,
        destination,
        spec,
        encoder=EncoderSpec(preset="slow", crf=16),
    )

    command = commands[0]
    assert command[command.index("-preset") + 1] == "slow"
    assert command[command.index("-crf") + 1] == "16"


def test_capture_previews_uses_zero_and_fixed_intervals(tmp_path: Path):
    source = tmp_path / "source.mp4"
    make_source(source)
    output_dir = tmp_path / "previews"

    paths = capture_previews(source, output_dir, interval_seconds=0.4)

    assert [path.name for path in paths] == ["0000ms.png", "0400ms.png", "0800ms.png"]
    assert all(path.stat().st_size > 0 for path in paths)


def test_preview_timestamps_never_include_clip_end():
    assert preview_timestamps(6.0, 2.0) == [0.0, 2.0, 4.0]
    assert preview_timestamps(6.1, 2.0) == [0.0, 2.0, 4.0, 6.0]


def test_probe_reports_pixel_format(tmp_path: Path):
    source = tmp_path / "source.mp4"
    make_source(source)
    info = probe_media(source)
    assert info.pixel_format == "yuv420p"
    assert info.frame_count == 10


def test_mux_audio_preserves_all_video_frames_and_pads_to_frame_boundary(tmp_path: Path):
    video = tmp_path / "video.mp4"
    audio = tmp_path / "audio.mp3"
    output = tmp_path / "muxed.mp4"
    make_silent_video(video, duration=0.7)
    make_audio(audio, duration=0.63)

    info = mux_audio(
        video,
        audio,
        output,
        OutputSpec(width=160, height=90, fps=10, duration_seconds=0.63, frames=7),
    )

    assert info.frame_count == 7
    assert info.duration_seconds == pytest.approx(0.7, abs=0.02)


def test_extract_video_segment_uses_half_open_frame_bounds(tmp_path: Path):
    source = tmp_path / "source.mp4"
    output = tmp_path / "segment.mp4"
    make_silent_video(source, duration=1.0)

    info = extract_video_segment(
        source,
        output,
        start_frame=2,
        end_frame=7,
        fps=10,
    )

    assert info.frame_count == 5
    assert info.duration_seconds == pytest.approx(0.5, abs=0.02)
    assert info.audio_codec is None


def test_extract_video_segment_rejects_empty_or_negative_ranges(tmp_path: Path):
    source = tmp_path / "source.mp4"
    make_silent_video(source, duration=1.0)

    with pytest.raises(ValueError, match="start_frame"):
        extract_video_segment(
            source,
            tmp_path / "negative.mp4",
            start_frame=-1,
            end_frame=2,
            fps=10,
        )
    with pytest.raises(ValueError, match="end_frame"):
        extract_video_segment(
            source,
            tmp_path / "empty.mp4",
            start_frame=2,
            end_frame=2,
            fps=10,
        )


def test_mux_audio_timeline_places_clips_and_preserves_declared_silence(tmp_path: Path):
    video = tmp_path / "video.mp4"
    first_audio = tmp_path / "first.mp3"
    second_audio = tmp_path / "second.mp3"
    output = tmp_path / "timeline.mp4"
    make_silent_video(video, duration=1.0)
    make_audio(first_audio, duration=0.3)
    make_audio(second_audio, duration=0.3)

    info = mux_audio_timeline(
        video,
        [
            AudioPlacement(first_audio, start_frame=0, end_frame=3),
            AudioPlacement(second_audio, start_frame=5, end_frame=8),
        ],
        output,
        OutputSpec(width=160, height=90, fps=10, duration_seconds=1.0, frames=10),
    )

    assert info.frame_count == 10
    assert info.duration_seconds == pytest.approx(1.0, abs=0.02)
    assert audio_rms(output, start=0.1, duration=0.1) > 100
    assert audio_rms(output, start=0.38, duration=0.06) < 10
    assert audio_rms(output, start=0.6, duration=0.1) > 100
    assert audio_rms(output, start=0.88, duration=0.06) < 10


def test_mux_audio_timeline_rejects_overlap_and_out_of_bounds(tmp_path: Path):
    video = tmp_path / "video.mp4"
    audio = tmp_path / "audio.mp3"
    make_silent_video(video, duration=1.0)
    make_audio(audio, duration=0.5)
    spec = OutputSpec(width=160, height=90, fps=10, duration_seconds=1.0, frames=10)

    with pytest.raises(ValueError, match="overlap"):
        mux_audio_timeline(
            video,
            [AudioPlacement(audio, 0, 5), AudioPlacement(audio, 4, 8)],
            tmp_path / "overlap.mp4",
            spec,
        )
    with pytest.raises(ValueError, match="timeline"):
        mux_audio_timeline(
            video,
            [AudioPlacement(audio, 8, 11)],
            tmp_path / "outside.mp4",
            spec,
        )


def test_concat_videos_inserts_silent_dip_to_black_between_scenes(tmp_path: Path):
    inputs = []
    frame_counts = [19, 194, 19]
    for index, frame_count in enumerate(frame_counts, start=1):
        video = tmp_path / f"video-{index}.mp4"
        audio = tmp_path / f"audio-{index}.mp3"
        scene = tmp_path / f"scene-{index}.mp4"
        make_silent_video(video, duration=frame_count / 30, fps=30)
        make_audio(audio, duration=0.63)
        mux_audio(
            video,
            audio,
            scene,
            OutputSpec(
                width=160,
                height=90,
                fps=30,
                duration_seconds=frame_count / 30,
                frames=frame_count,
            ),
        )
        inputs.append(scene)

    output = tmp_path / "joined.mp4"
    info = concat_videos(
        inputs,
        output,
        expected_duration=244 / 30,
        require_audio=True,
        transition_seconds=0.2,
        transition_fade_seconds=0.08,
    )

    assert info.frame_count == 244
    assert info.duration_seconds == pytest.approx(244 / 30, abs=0.06)
    assert max(frame_rgb(output, 22 / 30)) < 20
    assert max(frame_rgb(output, 222 / 30)) < 20
