from __future__ import annotations

import json
import math
import re
import subprocess
from contextlib import nullcontext
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path, PurePosixPath
from typing import Literal, Mapping, Sequence

from pydantic import Field

from .media import (
    MediaInfo,
    capture_preview_frames,
    create_contact_sheet,
    preview_timestamps,
    probe_media,
)
from .models import StrictModel
from .performance import PerformanceRecorder, RendererBackend, RendererTimings
from .production import script_sha256
from .production_models import ProductionPlan
from .sequence_models import LocalSequence, LocalSequencePlan, OnlinePlan
from .sequence_render import (
    SequenceArtifactSource,
    SequenceRenderReport,
    SequenceResult,
    resolve_sequence_artifact_sources,
)
from .settings import HarnessSettings, settings_sha256
from .storage import atomic_write


AAC_PACKET_TOLERANCE_SECONDS = 0.05


class QaIssue(StrictModel):
    code: str
    message: str
    sequence_id: str | None = None
    frame: int | None = None


class SequenceQaResult(StrictModel):
    sequence_id: str
    media_valid: bool
    state_valid: bool
    black_frames: list[int]
    undeclared_freeze_ranges: list[tuple[int, int]]
    preview_files: list[str]
    issues: list[QaIssue]


class QaReport(StrictModel):
    schema_version: Literal[1] = 1
    quality: Literal["draft", "final"]
    status: Literal["passed", "failed"]
    production_plan_sha256: str
    local_sequence_plan_sha256: str
    settings_sha256: str = Field(default_factory=lambda: settings_sha256(HarnessSettings()))
    preview_interval_seconds: float = HarnessSettings().render.preview_interval_seconds
    contact_sheet_columns: int = HarnessSettings().render.contact_sheet_columns
    sequence_results: list[SequenceQaResult]
    contact_sheet_file: str
    issue_codes: list[str]
    issues: list[QaIssue]


class StateCamera(StrictModel):
    position: tuple[float, float, float]
    target: tuple[float, float, float]


class StateSample(StrictModel):
    continuity: dict[str, object] | None = None
    canonical_frame: int = Field(ge=0)
    simulation_time: float
    visible_layers: list[str]
    geometry_operation_keys: list[str]
    camera: StateCamera
    entity_scales: dict[str, float]
    state_fingerprint: str = Field(min_length=1)
    # Text-gate evidence: CalloutLayer screen state and Three.js text attestation.
    callouts: list[dict[str, object]] | None = None
    # Scientific graph labels are checked against the plan by the text gate.
    graph_text: list[dict[str, object]] = Field(default_factory=list)
    canvas_text_calls: int | None = Field(default=None, ge=0)


class SequenceStateReport(StrictModel):
    sequence_id: str
    frame_count: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    frames: list[str]
    sample_frames: list[int] | None = None
    state_samples: list[StateSample]
    browser_version: str = Field(default="unknown", min_length=1)
    capture_method: str | None = None
    capture_timing_mode: Literal[
        "legacy_combined", "split", "playwright_combined"
    ] = "legacy_combined"
    capture_transport_bytes: int | None = Field(default=None, ge=0)
    backend: RendererBackend | None = None
    timings: RendererTimings | None = None


@dataclass(frozen=True)
class DecodedFrame:
    frame: int
    timestamp_seconds: float
    digest: str


def _issue(
    code: str,
    message: str,
    *,
    sequence_id: str | None = None,
    frame: int | None = None,
) -> QaIssue:
    return QaIssue(
        code=code,
        message=message,
        sequence_id=sequence_id,
        frame=frame,
    )


def _artifact_path(root: Path, relative: str) -> Path:
    declared = PurePosixPath(relative)
    if declared.is_absolute() or ".." in declared.parts or "\\" in relative:
        raise ValueError(f"artifact path must be a safe relative descendant: {relative}")
    resolved_root = root.resolve()
    candidate = (resolved_root / Path(*declared.parts)).resolve()
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise ValueError(f"artifact path escapes artifact root: {relative}")
    return candidate


def _relative_to(root: Path, path: Path) -> str:
    resolved_root = root.resolve()
    resolved_path = path.resolve()
    if resolved_path != resolved_root and resolved_root not in resolved_path.parents:
        raise ValueError(f"artifact path escapes artifact root: {path}")
    return resolved_path.relative_to(resolved_root).as_posix()


def _output_boundary(
    canonical_frame: int,
    *,
    output_fps: int,
    canonical_fps: int,
) -> int:
    return (canonical_frame * output_fps + canonical_fps - 1) // canonical_fps


def _expected_output_frames(
    sequence: LocalSequence,
    *,
    output_fps: int,
    canonical_fps: int,
) -> int:
    return _output_boundary(
        sequence.duration_frames,
        output_fps=output_fps,
        canonical_fps=canonical_fps,
    )


def decode_frame_hashes(source: Path, frames: Sequence[int]) -> dict[int, DecodedFrame]:
    """Decode selected frames with their presentation timestamps and content hashes."""
    selected = sorted(set(frames))
    if not selected:
        return {}
    if selected[0] < 0:
        raise ValueError("frame hashes require non-negative frame indexes")
    expression = "+".join(f"eq(n\\,{frame})" for frame in selected)
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-map",
            "0:v:0",
            "-vf",
            f"select={expression}",
            "-vsync",
            "0",
            "-f",
            "framehash",
            "-hash",
            "sha256",
            "pipe:1",
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    time_base = Fraction(1, 1)
    rows: list[tuple[int, str]] = []
    for line in result.stdout.splitlines():
        if line.startswith("#tb 0: "):
            time_base = Fraction(line.removeprefix("#tb 0: ").strip())
            continue
        if line.startswith("#") or not line.strip():
            continue
        columns = [value.strip() for value in line.split(",")]
        if len(columns) < 6:
            raise ValueError(f"unexpected framehash output: {line}")
        rows.append((int(columns[2]), columns[-1]))
    if len(rows) != len(selected):
        raise ValueError(
            f"decoded {len(rows)} boundary frames; expected {len(selected)}"
        )
    return {
        frame: DecodedFrame(
            frame=frame,
            timestamp_seconds=float(pts * time_base),
            digest=digest,
        )
        for frame, (pts, digest) in zip(selected, rows, strict=True)
    }


def _declared_join_transition_seconds(outgoing: LocalSequence, incoming: LocalSequence) -> float:
    """Return the bounded duration of an implemented transition at this join."""
    from .sequence_transitions import STYLES

    if not incoming.timeline or incoming.timeline[0].start_frame != 0:
        return 0.0
    options = incoming.timeline[0].controller_options
    duration = 0.0
    transition = options.get('entry_transition')
    if isinstance(transition, dict) and transition.get('style') in STYLES:
        value = transition.get('duration_seconds')
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 < value <= 1:
            duration = float(value)
    if (outgoing.scene_graph == incoming.scene_graph == 'optical-depth-story-blender-v2'
            and outgoing.timeline):
        pair = (outgoing.timeline[-1].controller_options.get('light_transition'),
                options.get('light_transition'))
        if pair in {('solar_to_lamp', 'lamp_reveal'), ('lamp_to_sun', 'sun_pullback')}:
            # The native renderer's brightness reveal lasts 0.3 seconds.
            duration = max(duration, 0.3)
    return duration


def validate_concat_boundaries(
    source: Path,
    inputs: Sequence[LocalSequence],
    input_frame_counts: Sequence[int],
    media: MediaInfo,
) -> list[QaIssue]:
    """Check join timing and repeats, allowing planned transitions only if motion resumes."""
    if len(inputs) != len(input_frame_counts):
        raise ValueError("concat boundary inputs and frame counts must have the same length")
    expected_frames = sum(input_frame_counts)
    issues: list[QaIssue] = []
    if media.frame_count != expected_frames:
        issues.append(
            _issue(
                "concat_boundary_frame_count_mismatch",
                f"concat has {media.frame_count} frames; expected {expected_frames}",
            )
        )
        return issues
    boundaries: list[tuple[int, LocalSequence]] = []
    recovery_frames: dict[int, tuple[int, int]] = {}
    cumulative = 0
    for index, count in enumerate(input_frame_counts[:-1]):
        cumulative += count
        if cumulative <= 0 or cumulative + 1 >= expected_frames:
            continue
        boundaries.append((cumulative, inputs[index + 1]))
        outgoing, incoming = inputs[index], inputs[index + 1]
        duration = _declared_join_transition_seconds(outgoing, incoming)
        if duration:
            end = cumulative + math.ceil(duration * media.fps)
            # Sample across 0.1 s, not just adjacent high-fps frames whose
            # quantized pixels may still be identical during slow movement.
            following = min(end + max(1, math.ceil(0.1 * media.fps)),
                            cumulative + input_frame_counts[index + 1] - 1)
            if following > end:
                recovery_frames[cumulative] = (end, following)
    requested = [frame for boundary, _ in boundaries for frame in (boundary - 1, boundary, boundary + 1)]
    requested.extend(frame for frames in recovery_frames.values() for frame in frames)
    try:
        decoded = decode_frame_hashes(source, requested)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        return [
            *issues,
            _issue("concat_boundary_probe_failed", f"could not inspect concat boundaries: {error}"),
        ]
    for boundary, incoming in boundaries:
        indices = [boundary - 1, boundary, boundary + 1]
        if boundary in recovery_frames:
            indices.extend(recovery_frames[boundary])
        samples = [decoded.get(frame) for frame in indices]
        if any(sample is None for sample in samples):
            issues.append(
                _issue("concat_boundary_probe_failed", "boundary frame was not decoded", sequence_id=incoming.sequence_id, frame=boundary)
            )
            continue
        previous, current, following = samples[:3]
        assert previous is not None and current is not None and following is not None
        for sample in samples:
            if abs(sample.timestamp_seconds - sample.frame / media.fps) > 0.01:
                issues.append(
                    _issue(
                        "concat_boundary_timestamp_mismatch",
                        f"decoded timestamp {sample.timestamp_seconds:.6f}s does not match frame {sample.frame}",
                        sequence_id=incoming.sequence_id,
                        frame=sample.frame,
                    )
                )
        reveal_recovers = (boundary in recovery_frames
                           and samples[-2].digest != previous.digest
                           and samples[-1].digest != samples[-2].digest)
        if (
            previous.digest == current.digest == following.digest
            and not _is_declared_hold(incoming, 0)
            and not reveal_recovers
        ):
            issues.append(
                _issue(
                    "undeclared_concat_boundary_freeze",
                    "outgoing boundary frame repeats through both incoming samples",
                    sequence_id=incoming.sequence_id,
                    frame=boundary,
                )
            )
    return issues


def validate_media_contract(
    sequence: LocalSequence,
    rendered: SequenceResult,
    silent_info: MediaInfo | None,
    narrated_info: MediaInfo | None,
    *,
    local: LocalSequencePlan,
    quality: Literal["draft", "final"],
    settings: HarnessSettings | None = None,
    audio_packet_tolerance_seconds: float = AAC_PACKET_TOLERANCE_SECONDS,
) -> list[QaIssue]:
    issues: list[QaIssue] = []
    sequence_id = sequence.sequence_id
    settings = settings or HarnessSettings()
    expected_width, expected_height, expected_fps = (
        (
            settings.render.draft_width,
            settings.render.draft_height,
            settings.render.draft_fps,
        )
        if quality == "draft"
        else (local.defaults.width, local.defaults.height, local.defaults.fps)
    )
    expected_frames = _expected_output_frames(
        sequence,
        output_fps=expected_fps,
        canonical_fps=local.defaults.fps,
    )
    if (rendered.width, rendered.height) != (expected_width, expected_height):
        issues.append(
            _issue(
                "report_dimension_mismatch",
                f"render report dimensions are {rendered.width}x{rendered.height}; "
                f"expected {expected_width}x{expected_height}",
                sequence_id=sequence_id,
            )
        )
    if rendered.fps != expected_fps:
        issues.append(
            _issue(
                "report_fps_mismatch",
                f"render report FPS is {rendered.fps}; expected {expected_fps}",
                sequence_id=sequence_id,
            )
        )
    if rendered.frame_count != expected_frames:
        issues.append(
            _issue(
                "report_frame_count_mismatch",
                f"render report has {rendered.frame_count} frames; expected {expected_frames}",
                sequence_id=sequence_id,
            )
        )

    expected_duration = expected_frames / expected_fps
    for label, info, expected_audio in (
        ("silent", silent_info, None),
        ("narrated", narrated_info, "aac"),
    ):
        if info is None:
            continue
        if info.video_codec != "h264" or info.audio_codec != expected_audio:
            issues.append(
                _issue(
                    "media_codec_mismatch",
                    f"{label} master codecs are {info.video_codec}/{info.audio_codec}; "
                    f"expected h264/{expected_audio}",
                    sequence_id=sequence_id,
                )
            )
        if (info.width, info.height) != (expected_width, expected_height):
            issues.append(
                _issue(
                    "media_dimension_mismatch",
                    f"{label} master dimensions are {info.width}x{info.height}; "
                    f"expected {expected_width}x{expected_height}",
                    sequence_id=sequence_id,
                )
            )
        if abs(info.fps - expected_fps) > 0.01:
            issues.append(
                _issue(
                    "media_fps_mismatch",
                    f"{label} master FPS is {info.fps}; expected {expected_fps}",
                    sequence_id=sequence_id,
                )
            )
        if info.frame_count != expected_frames:
            issues.append(
                _issue(
                    "media_frame_count_mismatch",
                    f"{label} master has {info.frame_count} frames; expected {expected_frames}",
                    sequence_id=sequence_id,
                )
            )
        if abs(info.duration_seconds - expected_duration) > (1 / expected_fps + 0.01):
            issues.append(
                _issue(
                    "media_duration_mismatch",
                    f"{label} master duration is {info.duration_seconds:.6f}; "
                    f"expected {expected_duration:.6f}",
                    sequence_id=sequence_id,
                )
            )

    if silent_info is not None and narrated_info is not None:
        silent_timeline = (
            silent_info.width,
            silent_info.height,
            round(silent_info.fps, 6),
            silent_info.frame_count,
        )
        narrated_timeline = (
            narrated_info.width,
            narrated_info.height,
            round(narrated_info.fps, 6),
            narrated_info.frame_count,
        )
        if silent_timeline != narrated_timeline:
            issues.append(
                _issue(
                    "audio_video_timeline_mismatch",
                    "silent and narrated sequence masters do not share one video timeline",
                    sequence_id=sequence_id,
                )
            )
        if (
            narrated_info.audio_duration_seconds is None
            or narrated_info.audio_end_seconds is None
        ):
            issues.append(
                _issue(
                    "audio_stream_timeline_unavailable",
                    "narrated master has no independently probed AAC duration/end",
                    sequence_id=sequence_id,
                )
            )
        elif (
            narrated_info.audio_end_seconds + audio_packet_tolerance_seconds
            < expected_duration
        ):
            issues.append(
                _issue(
                    "audio_stream_ends_early",
                    f"AAC ends at {narrated_info.audio_end_seconds:.6f}s; "
                    f"expected {expected_duration:.6f}s within "
                    f"{audio_packet_tolerance_seconds:.3f}s packet tolerance",
                    sequence_id=sequence_id,
                )
            )
    return issues


def validate_state_samples(
    sequence: LocalSequence,
    rendered: SequenceResult,
    state_report: SequenceStateReport,
    *,
    canonical_fps: int,
    artifact_root: Path,
) -> list[QaIssue]:
    issues: list[QaIssue] = []
    sequence_id = sequence.sequence_id
    if state_report.sequence_id != sequence_id:
        issues.append(
            _issue(
                "state_sequence_mismatch",
                f"state report names {state_report.sequence_id}",
                sequence_id=sequence_id,
            )
        )
    if (
        state_report.frame_count != rendered.frame_count
        or len(state_report.frames) != rendered.frame_count
    ):
        issues.append(
            _issue(
                "state_frame_count_mismatch",
                "state report frame metadata does not match the rendered master",
                sequence_id=sequence_id,
            )
        )
    if (state_report.width, state_report.height) != (rendered.width, rendered.height):
        issues.append(
            _issue(
                "state_dimension_mismatch",
                "state report dimensions do not match the rendered master",
                sequence_id=sequence_id,
            )
        )
    if len(state_report.state_samples) != rendered.frame_count:
        issues.append(
            _issue(
                "missing_state_samples",
                f"state report has {len(state_report.state_samples)} samples; "
                f"expected {rendered.frame_count}",
                sequence_id=sequence_id,
            )
        )
    expected_frame_names = {
        f"frame-{frame:06d}.png": frame for frame in range(rendered.frame_count)
    }
    reported_names: set[str] = set()
    reported_paths: set[Path] = set()
    for output_frame, relative in enumerate(state_report.frames):
        expected_name = f"frame-{output_frame:06d}.png"
        declared_name = PurePosixPath(relative).name
        if declared_name in reported_names:
            issues.append(
                _issue(
                    "duplicate_reported_frame",
                    f"reported frame identity is duplicated: {declared_name}",
                    sequence_id=sequence_id,
                    frame=output_frame,
                )
            )
        reported_names.add(declared_name)
        if declared_name != expected_name:
            code = (
                "misordered_reported_frame"
                if declared_name in expected_frame_names
                else "invalid_reported_frame_name"
            )
            issues.append(
                _issue(
                    code,
                    f"reported frame {output_frame} is {declared_name}; "
                    f"expected {expected_name}",
                    sequence_id=sequence_id,
                    frame=output_frame,
                )
            )
        try:
            frame_path = _artifact_path(artifact_root, relative)
        except ValueError as error:
            issues.append(
                _issue(
                    "unsafe_reported_frame_path",
                    str(error),
                    sequence_id=sequence_id,
                    frame=output_frame,
                )
            )
            continue
        if frame_path in reported_paths:
            issues.append(
                _issue(
                    "duplicate_reported_frame",
                    f"reported frame path is duplicated: {relative}",
                    sequence_id=sequence_id,
                    frame=output_frame,
                )
            )
        reported_paths.add(frame_path)
        if frame_path.name != expected_name:
            issues.append(
                _issue(
                    "misordered_reported_frame",
                    f"resolved frame {output_frame} is {frame_path.name}; "
                    f"expected {expected_name}",
                    sequence_id=sequence_id,
                    frame=output_frame,
                )
            )
        if not frame_path.is_file():
            issues.append(
                _issue(
                    "missing_reported_frame_file",
                    f"reported frame file does not exist: {relative}",
                    sequence_id=sequence_id,
                    frame=output_frame,
                )
            )
        elif frame_path.stat().st_size == 0:
            issues.append(
                _issue(
                    "empty_reported_frame",
                    f"reported frame file is empty: {relative}",
                    sequence_id=sequence_id,
                    frame=output_frame,
                )
            )
    for missing_name, output_frame in expected_frame_names.items():
        if missing_name not in reported_names:
            issues.append(
                _issue(
                    "missing_reported_frame",
                    f"state report omits {missing_name}",
                    sequence_id=sequence_id,
                    frame=output_frame,
                )
            )
    previous_time = float("-inf")
    for output_frame, sample in enumerate(state_report.state_samples):
        expected_canonical = min(
            sequence.duration_frames - 1,
            (output_frame * canonical_fps) // rendered.fps,
        )
        if sample.canonical_frame != expected_canonical:
            issues.append(
                _issue(
                    "state_frame_mapping_mismatch",
                    f"state sample maps to canonical frame {sample.canonical_frame}; "
                    f"expected {expected_canonical}",
                    sequence_id=sequence_id,
                    frame=output_frame,
                )
            )
        if not math.isfinite(sample.simulation_time):
            issues.append(
                _issue(
                    "invalid_simulation_time",
                    f"simulation time is not finite: {sample.simulation_time}",
                    sequence_id=sequence_id,
                    frame=output_frame,
                )
            )
            continue
        if sample.simulation_time < previous_time:
            issues.append(
                _issue(
                    "simulation_time_reversal",
                    f"simulation time decreased from {previous_time} "
                    f"to {sample.simulation_time}",
                    sequence_id=sequence_id,
                    frame=output_frame,
                )
            )
        previous_time = sample.simulation_time
    return issues


def _hide_is_declared(sequence: LocalSequence, start_frame: int, end_frame: int) -> bool:
    return any(
        "hide_events" in beat.patch_targets
        and beat.start_frame < end_frame
        and beat.end_frame > start_frame
        for beat in sequence.timeline
    )


def validate_layer_continuity(
    sequence: LocalSequence,
    state_report: SequenceStateReport,
) -> list[QaIssue]:
    issues: list[QaIssue] = []
    boundaries = {span.start_frame for span in sequence.scene_spans[1:]}
    samples = state_report.state_samples
    for output_frame, (previous, current) in enumerate(
        zip(samples, samples[1:], strict=False),
        start=1,
    ):
        removed = sorted(set(previous.visible_layers) - set(current.visible_layers))
        if not removed:
            continue
        transition_start = previous.canonical_frame + 1
        transition_end = current.canonical_frame + 1
        if _hide_is_declared(sequence, transition_start, transition_end):
            continue
        at_internal_boundary = any(
            previous.canonical_frame < boundary <= current.canonical_frame
            for boundary in boundaries
        )
        code = "unexpected_layer_reset" if at_internal_boundary else "undeclared_layer_hide"
        issues.append(
            _issue(
                code,
                f"layers disappeared without an explicit hide event: {', '.join(removed)}",
                sequence_id=sequence.sequence_id,
                frame=output_frame,
            )
        )
    return issues


def _is_declared_hold(sequence: LocalSequence, canonical_frame: int) -> bool:
    return any(
        beat.hold_intent is not None
        and beat.start_frame <= canonical_frame < beat.end_frame
        for beat in sequence.timeline
    )


def _freeze_ranges(
    sequence: LocalSequence,
    samples: Sequence[StateSample],
    *,
    output_fps: int,
    max_seconds: float,
) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    start = 0
    while start < len(samples):
        fingerprint = samples[start].state_fingerprint
        end = start + 1
        while end < len(samples) and samples[end].state_fingerprint == fingerprint:
            end += 1
        segment_start: int | None = None
        for index in range(start, end + 1):
            undeclared = (
                index < end
                and not _is_declared_hold(sequence, samples[index].canonical_frame)
            )
            if undeclared and segment_start is None:
                segment_start = index
            if not undeclared and segment_start is not None:
                if index - segment_start > max_seconds * output_fps:
                    ranges.append((segment_start, index))
                segment_start = None
        start = end
    return ranges


def validate_freeze_spans(
    sequence: LocalSequence,
    state_report: SequenceStateReport,
    *,
    output_fps: int,
    max_seconds: float,
) -> list[QaIssue]:
    return [
        _issue(
            "undeclared_freeze",
            f"identical state fingerprint persists for frames [{start}, {end})",
            sequence_id=sequence.sequence_id,
            frame=start,
        )
        for start, end in _freeze_ranges(
            sequence,
            state_report.state_samples,
            output_fps=output_fps,
            max_seconds=max_seconds,
        )
    ]


def validate_reference_coverage(
    online: OnlinePlan,
    artifact_root: Path,
    *,
    quality: Literal["draft", "final"],
) -> list[QaIssue]:
    if quality != "final":
        return []
    issues: list[QaIssue] = []
    for shot in online.shots:
        if shot.preferred_mode != "v2v":
            continue
        if shot.reference_video_file is None:
            issues.append(
                _issue(
                    "missing_v2v_reference",
                    f"V2V shot {shot.online_shot_id} has no declared reference file",
                    sequence_id=shot.source_sequence_id,
                    frame=shot.source_start_frame,
                )
            )
            continue
        try:
            reference = _artifact_path(artifact_root, shot.reference_video_file)
        except ValueError as error:
            issues.append(
                _issue(
                    "invalid_v2v_reference_path",
                    str(error),
                    sequence_id=shot.source_sequence_id,
                    frame=shot.source_start_frame,
                )
            )
            continue
        if not reference.is_file() or reference.stat().st_size == 0:
            issues.append(
                _issue(
                    "missing_v2v_reference",
                    f"V2V reference does not exist: {shot.reference_video_file}",
                    sequence_id=shot.source_sequence_id,
                    frame=shot.source_start_frame,
                )
            )
    return issues


def detect_black_frames(
    source: Path,
    *,
    amount_percent: float,
    threshold: int,
) -> list[int]:
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "info",
            "-i",
            str(source),
            "-vf",
            f"blackframe=amount={amount_percent}:threshold={threshold}",
            "-an",
            "-f",
            "null",
            "-",
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    return sorted({int(value) for value in re.findall(r"frame:(\d+)\s+pblack:", result.stderr)})


def _probe_with_issue(
    path: Path,
    *,
    sequence_id: str | None,
    label: str,
) -> tuple[MediaInfo | None, list[QaIssue]]:
    try:
        if not path.is_file() or path.stat().st_size == 0:
            raise FileNotFoundError(path)
        return probe_media(path), []
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        return None, [
            _issue(
                "media_probe_failed",
                f"could not probe {label}: {error}",
                sequence_id=sequence_id,
            )
        ]


def _validate_final_media(
    render_report: SequenceRenderReport,
    planned_sequences: Sequence[LocalSequence],
    *,
    production: ProductionPlan,
    local: LocalSequencePlan,
    quality: Literal["draft", "final"],
    settings: HarnessSettings,
    audio_packet_tolerance_seconds: float = AAC_PACKET_TOLERANCE_SECONDS,
) -> list[QaIssue]:
    root = render_report.artifact_root
    try:
        silent_path = _artifact_path(root, render_report.final_original_file)
        narrated_path = _artifact_path(root, render_report.final_file)
    except ValueError as error:
        return [_issue("invalid_final_media_path", str(error))]
    silent, issues = _probe_with_issue(
        silent_path,
        sequence_id=None,
        label="whole silent master",
    )
    narrated, narrated_issues = _probe_with_issue(
        narrated_path,
        sequence_id=None,
        label="whole narrated master",
    )
    issues.extend(narrated_issues)
    if silent is None or narrated is None:
        return issues
    expected_width, expected_height, expected_fps = (
        (
            settings.render.draft_width,
            settings.render.draft_height,
            settings.render.draft_fps,
        )
        if quality == "draft"
        else (local.defaults.width, local.defaults.height, local.defaults.fps)
    )
    expected_dimensions = (expected_width, expected_height)
    expected_frames = sum(
        _expected_output_frames(
            sequence,
            output_fps=expected_fps,
            canonical_fps=local.defaults.fps,
        )
        for sequence in planned_sequences
    )
    expected_duration = expected_frames / expected_fps
    for label, info, expected_audio in (
        ("silent", silent, None),
        ("narrated", narrated, "aac"),
    ):
        if info.video_codec != "h264" or info.audio_codec != expected_audio:
            issues.append(
                _issue(
                    "final_media_codec_mismatch",
                    f"whole {label} codecs are {info.video_codec}/{info.audio_codec}",
                )
            )
        if info.frame_count != expected_frames:
            issues.append(
                _issue(
                    "final_media_frame_count_mismatch",
                    f"whole {label} has {info.frame_count} frames; expected {expected_frames}",
                )
            )
        if (info.width, info.height) != expected_dimensions:
            issues.append(
                _issue(
                    "final_media_dimension_mismatch",
                    f"whole {label} dimensions are {info.width}x{info.height}; "
                    f"expected {expected_dimensions[0]}x{expected_dimensions[1]}",
                )
            )
        if abs(info.fps - expected_fps) > 0.01:
            issues.append(
                _issue(
                    "final_media_fps_mismatch",
                    f"whole {label} FPS is {info.fps}; expected {expected_fps}",
                )
            )
    if (
        narrated.audio_duration_seconds is None
        or narrated.audio_end_seconds is None
    ):
        issues.append(
            _issue(
                "final_audio_stream_timeline_unavailable",
                "whole narrated output has no independently probed AAC duration/end",
            )
        )
    elif narrated.audio_end_seconds + audio_packet_tolerance_seconds < expected_duration:
        issues.append(
            _issue(
                "final_audio_stream_ends_early",
                f"whole AAC ends at {narrated.audio_end_seconds:.6f}s; "
                f"expected {expected_duration:.6f}s within "
                f"{audio_packet_tolerance_seconds:.3f}s packet tolerance",
            )
        )
    silent_timeline = (silent.width, silent.height, round(silent.fps, 6), silent.frame_count)
    narrated_timeline = (
        narrated.width,
        narrated.height,
        round(narrated.fps, 6),
        narrated.frame_count,
    )
    if silent_timeline != narrated_timeline:
        issues.append(
            _issue(
                "final_audio_video_timeline_mismatch",
                "whole silent and narrated outputs do not share one video timeline",
            )
        )
    return issues


def _qa_report_path(
    artifact_root: Path,
    quality: Literal["draft", "final"],
) -> Path:
    if quality == "draft":
        return artifact_root / "videoFiles" / "sequences" / "draft" / "qa-report.json"
    return artifact_root / "qa-report.json"


def _run_sequence_qa(
    run_dir: Path,
    production: ProductionPlan,
    local: LocalSequencePlan,
    online: OnlinePlan,
    render_report: SequenceRenderReport,
    *,
    quality: Literal["draft", "final"],
    settings: HarnessSettings | None = None,
    performance: PerformanceRecorder | None = None,
    sequence_sources: Mapping[str, SequenceArtifactSource] | None = None,
) -> QaReport:
    settings = settings or HarnessSettings()
    artifact_root = render_report.artifact_root.resolve()
    sources = (
        resolve_sequence_artifact_sources(render_report, sequence_sources)
        if sequence_sources is not None
        else None
    )
    global_issues: list[QaIssue] = []
    if render_report.quality != quality:
        global_issues.append(
            _issue(
                "quality_mismatch",
                f"QA quality {quality} differs from render quality {render_report.quality}",
            )
        )
    for filename, reported_hash, code in (
        (
            "production-plan.json",
            render_report.production_plan_sha256,
            "production_plan_hash_mismatch",
        ),
        (
            "local-sequence-plan.json",
            render_report.local_sequence_plan_sha256,
            "local_sequence_plan_hash_mismatch",
        ),
    ):
        try:
            actual_hash = script_sha256(run_dir / filename)
        except OSError as error:
            global_issues.append(_issue(code, f"could not hash {filename}: {error}"))
        else:
            if actual_hash != reported_hash:
                global_issues.append(
                    _issue(code, f"render report is not bound to the current {filename}")
                )
    if local.production_plan_sha256 != render_report.production_plan_sha256:
        global_issues.append(
            _issue(
                "production_plan_hash_mismatch",
                "local and rendered production-plan hashes differ",
            )
        )

    planned_ids = [sequence.sequence_id for sequence in local.sequences]
    reported_ids = [result.sequence_id for result in render_report.sequences]
    seen_reported_ids: set[str] = set()
    for sequence_id in reported_ids:
        if sequence_id in seen_reported_ids:
            global_issues.append(
                _issue(
                    "duplicate_rendered_sequence",
                    f"render report repeats sequence {sequence_id}",
                    sequence_id=sequence_id,
                )
            )
        seen_reported_ids.add(sequence_id)
    if reported_ids != planned_ids:
        global_issues.append(
            _issue(
                "rendered_sequence_order_mismatch",
                f"rendered sequence order {reported_ids} differs from plan {planned_ids}",
            )
        )
    rendered_by_id: dict[str, SequenceResult] = {}
    for result in render_report.sequences:
        rendered_by_id.setdefault(result.sequence_id, result)
    production_local_ids = [
        sequence.sequence_id
        for sequence in production.visual_sequences
        if sequence.primary_route == "local"
    ]
    if production_local_ids != planned_ids:
        global_issues.append(
            _issue(
                "sequence_plan_mismatch",
                "production and local plans do not declare the same ordered local sequences",
            )
        )
    extra_ids = sorted(set(rendered_by_id) - set(planned_ids))
    for sequence_id in extra_ids:
        global_issues.append(
            _issue(
                "unexpected_rendered_sequence",
                f"render report contains unplanned sequence {sequence_id}",
                sequence_id=sequence_id,
            )
        )

    sequence_results: list[SequenceQaResult] = []
    for sequence in local.sequences:
        result = rendered_by_id.get(sequence.sequence_id)
        sequence_issues: list[QaIssue] = []
        preview_files: list[str] = []
        black_frames: list[int] = []
        freeze_ranges: list[tuple[int, int]] = []
        media_issue_count = 0
        state_issue_count = 0
        if result is None:
            issue = _issue(
                "missing_rendered_sequence",
                f"render report omits planned sequence {sequence.sequence_id}",
                sequence_id=sequence.sequence_id,
            )
            sequence_issues.append(issue)
            media_issue_count += 1
            state_issue_count += 1
        else:
            source_root = (
                sources[sequence.sequence_id].root
                if sources is not None
                else artifact_root
            )
            try:
                master_path = _artifact_path(source_root, result.master_file)
                narrated_path = _artifact_path(source_root, result.narrated_file)
                state_path = _artifact_path(source_root, result.state_report_file)
            except ValueError as error:
                issue = _issue(
                    "invalid_sequence_artifact_path",
                    str(error),
                    sequence_id=sequence.sequence_id,
                )
                sequence_issues.append(issue)
                media_issue_count += 1
                state_issue_count += 1
            else:
                silent_info, silent_probe_issues = _probe_with_issue(
                    master_path,
                    sequence_id=sequence.sequence_id,
                    label="silent sequence master",
                )
                narrated_info, narrated_probe_issues = _probe_with_issue(
                    narrated_path,
                    sequence_id=sequence.sequence_id,
                    label="narrated sequence master",
                )
                media_issues = [*silent_probe_issues, *narrated_probe_issues]
                media_issues.extend(
                    validate_media_contract(
                        sequence,
                        result,
                        silent_info,
                        narrated_info,
                        local=local,
                        quality=quality,
                        settings=settings,
                        audio_packet_tolerance_seconds=settings.qa.audio_packet_tolerance_seconds,
                    )
                )
                if silent_info is not None:
                    try:
                        with (
                            performance.phase(
                                "ffmpeg_decode",
                                operation="black_frame_scan",
                                sequence_id=sequence.sequence_id,
                            )
                            if performance is not None
                            else nullcontext()
                        ):
                            detected_black = detect_black_frames(
                                master_path,
                                amount_percent=settings.qa.black_frame_amount_percent,
                                threshold=settings.qa.black_frame_threshold,
                            )
                    except (OSError, ValueError, subprocess.SubprocessError) as error:
                        media_issues.append(
                            _issue(
                                "black_frame_probe_failed",
                                f"could not inspect black frames: {error}",
                                sequence_id=sequence.sequence_id,
                            )
                        )
                    else:
                        black_frames = detected_black
                        media_issues.extend(
                            _issue(
                                "black_frame",
                                f"undeclared black frame at output frame {frame}",
                                sequence_id=sequence.sequence_id,
                                frame=frame,
                            )
                            for frame in black_frames
                        )
                    timestamps = preview_timestamps(
                        sequence.duration_frames / local.defaults.fps,
                        settings.render.preview_interval_seconds,
                    )
                    names = [
                        f"{round(timestamp * 1000):06d}ms.png"
                        for timestamp in timestamps
                    ]
                    preview_directory = (
                        artifact_root
                        / "videoFiles"
                        / "previews"
                        / "half-second"
                        / sequence.sequence_id
                    )
                    try:
                        with (
                            performance.phase(
                                "ffmpeg_decode",
                                operation="preview_extract",
                                sequence_id=sequence.sequence_id,
                            )
                            if performance is not None
                            else nullcontext()
                        ):
                            paths = capture_preview_frames(
                                master_path,
                                preview_directory,
                                timestamps,
                                names,
                            )
                    except (OSError, ValueError, subprocess.SubprocessError) as error:
                        media_issues.append(
                            _issue(
                                "preview_generation_failed",
                                f"could not create half-second previews: {error}",
                                sequence_id=sequence.sequence_id,
                            )
                        )
                    else:
                        preview_files = [
                            _relative_to(artifact_root, path) for path in paths
                        ]
                sequence_issues.extend(media_issues)
                media_issue_count += len(media_issues)

                try:
                    state_report = SequenceStateReport.model_validate_json(
                        state_path.read_text(encoding="utf-8")
                    )
                except (OSError, ValueError) as error:
                    state_issues = [
                        _issue(
                            "invalid_state_report",
                            f"could not parse state report: {error}",
                            sequence_id=sequence.sequence_id,
                        )
                    ]
                else:
                    state_issues = validate_state_samples(
                        sequence,
                        result,
                        state_report,
                        canonical_fps=local.defaults.fps,
                        artifact_root=source_root,
                    )
                    state_issues.extend(validate_layer_continuity(sequence, state_report))
                    freeze_ranges = _freeze_ranges(
                        sequence,
                        state_report.state_samples,
                        output_fps=result.fps,
                        max_seconds=settings.qa.max_undeclared_freeze_seconds,
                    )
                    state_issues.extend(
                        validate_freeze_spans(
                            sequence,
                            state_report,
                            output_fps=result.fps,
                            max_seconds=settings.qa.max_undeclared_freeze_seconds,
                        )
                    )
                sequence_issues.extend(state_issues)
                state_issue_count += len(state_issues)

        sequence_results.append(
            SequenceQaResult(
                sequence_id=sequence.sequence_id,
                media_valid=media_issue_count == 0,
                state_valid=state_issue_count == 0,
                black_frames=black_frames,
                undeclared_freeze_ranges=freeze_ranges,
                preview_files=preview_files,
                issues=sequence_issues,
            )
        )

    global_issues.extend(
        _validate_final_media(
            render_report,
            local.sequences,
            production=production,
            local=local,
            quality=quality,
            settings=settings,
            audio_packet_tolerance_seconds=settings.qa.audio_packet_tolerance_seconds,
        )
    )
    ordered_results = [rendered_by_id.get(sequence.sequence_id) for sequence in local.sequences]
    if len(local.sequences) >= 2 and all(
        result is not None for result in ordered_results
    ):
        boundary_source = _artifact_path(artifact_root, render_report.final_original_file)
        try:
            boundary_media = probe_media(boundary_source)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            global_issues.append(
                _issue("concat_boundary_probe_failed", f"could not inspect concat: {error}")
            )
        else:
            boundary_count = len(local.sequences) - 1
            phase = (
                performance.phase("boundary_qa", boundaries=boundary_count)
                if performance is not None
                else nullcontext()
            )
            with phase:
                with (
                    performance.phase(
                        "ffmpeg_decode",
                        operation="boundary_hashes",
                        boundaries=boundary_count,
                    )
                    if performance is not None
                    else nullcontext()
                ):
                    global_issues.extend(
                        validate_concat_boundaries(
                            boundary_source,
                            local.sequences,
                            [result.frame_count for result in ordered_results if result is not None],
                            boundary_media,
                        )
                    )
    if settings.pipeline.output_mode != "video_only":
        global_issues.extend(
            validate_reference_coverage(online, artifact_root, quality=quality)
        )
    contact_sheet = (
        artifact_root
        / "videoFiles"
        / "previews"
        / "half-second"
        / "contact-sheet.png"
    )
    try:
        contact_source = _artifact_path(artifact_root, render_report.final_original_file)
        with (
            performance.phase("ffmpeg_decode", operation="contact_sheet")
            if performance is not None
            else nullcontext()
        ):
            create_contact_sheet(
                contact_source,
                contact_sheet,
                interval_seconds=settings.render.preview_interval_seconds,
                columns=settings.render.contact_sheet_columns,
            )
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        global_issues.append(
            _issue(
                "contact_sheet_generation_failed",
                f"could not create contact sheet: {error}",
            )
        )

    sequence_issues = [
        issue for result in sequence_results for issue in result.issues
    ]
    from .creative_gates import render_report_continuity_issues
    global_issues.extend(_issue('render_continuity_failed', error) for error in render_report_continuity_issues(run_dir, local, render_report, sources))
    all_issues = [*sequence_issues, *global_issues]
    report = QaReport(
        quality=quality,
        status="failed" if all_issues else "passed",
        production_plan_sha256=render_report.production_plan_sha256,
        local_sequence_plan_sha256=render_report.local_sequence_plan_sha256,
        settings_sha256=settings_sha256(settings),
        preview_interval_seconds=settings.render.preview_interval_seconds,
        contact_sheet_columns=settings.render.contact_sheet_columns,
        sequence_results=sequence_results,
        contact_sheet_file=_relative_to(artifact_root, contact_sheet),
        issue_codes=sorted({issue.code for issue in all_issues}),
        issues=all_issues,
    )
    atomic_write(
        _qa_report_path(artifact_root, quality),
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
    )
    return report


def run_sequence_qa(
    run_dir: Path,
    production: ProductionPlan,
    local: LocalSequencePlan,
    online: OnlinePlan,
    render_report: SequenceRenderReport,
    *,
    quality: Literal["draft", "final"],
    settings: HarnessSettings | None = None,
    performance: PerformanceRecorder | None = None,
    sequence_sources: Mapping[str, SequenceArtifactSource] | None = None,
) -> QaReport:
    with (
        performance.phase("qa", quality=quality)
        if performance is not None
        else nullcontext()
    ):
        return _run_sequence_qa(
            run_dir,
            production,
            local,
            online,
            render_report,
            quality=quality,
            settings=settings,
            performance=performance,
            sequence_sources=sequence_sources,
        )
