"""Determinism and visual-quality gates for local sequence rendering.

This command deliberately keeps exact same-backend checks separate from the
cross-backend SSIM/PSNR result.  Only the former can ever decide whether a
sequence is safe to reuse from a cache.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, Sequence

from .media import EncoderSpec
from .models import ScriptArtifact
from .sequence_plans import load_local_sequence_plan
from .sequence_render import _canonical_state_cache, _physics_payload, _style_payload, _timeline_payload
from .settings import resolve_run_settings
from .simulation import load_simulation
from .storage import atomic_write


RendererBackend = Literal["metal", "swiftshader"]


@dataclass(frozen=True)
class RepeatComparisonIssue:
    frame: int
    reason: str
    left: str | None = None
    right: str | None = None


@dataclass(frozen=True)
class BackendQualityResult:
    """Cross-backend metrics.  This intentionally has no cache decision."""

    ssim: float
    psnr: float
    encode_baseline_ssim: float
    encode_baseline_psnr: float | None = None

    @property
    def cache_eligible(self) -> None:
        return None

    @property
    def visual_regression_passed(self) -> bool:
        return self.ssim >= self.encode_baseline_ssim and (
            self.encode_baseline_psnr is None or self.psnr >= self.encode_baseline_psnr
        )


def compare_repeat_hashes(
    left: Sequence[str], right: Sequence[str]
) -> RepeatComparisonIssue | None:
    """Return the first ordered decoded-frame mismatch, if any."""
    for frame, (left_hash, right_hash) in enumerate(zip(left, right, strict=False)):
        if left_hash != right_hash:
            return RepeatComparisonIssue(frame, "rgba_hash_mismatch", left_hash, right_hash)
    if len(left) != len(right):
        frame = min(len(left), len(right))
        return RepeatComparisonIssue(
            frame,
            "frame_count_mismatch",
            str(len(left)),
            str(len(right)),
        )
    return None


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=True)


def _png_dimensions(path: Path) -> tuple[int, int]:
    result = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "json",
            str(path),
        ]
    )
    stream = json.loads(result.stdout)["streams"][0]
    return int(stream["width"]), int(stream["height"])


def rgba_sha256(path: Path) -> str:
    """Hash FFmpeg-decoded RGBA pixels, never the PNG container bytes."""
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgba", "-"],
        capture_output=True,
        check=True,
    )
    width, height = _png_dimensions(path)
    expected = width * height * 4
    if len(result.stdout) != expected:
        raise ValueError(
            f"RGBA decode size differs for {path}: {len(result.stdout)} / {expected}"
        )
    return hashlib.sha256(result.stdout).hexdigest()


def _report_frame_paths(report: dict[str, Any]) -> list[Path]:
    frames = report.get("frames")
    if not isinstance(frames, list) or not all(isinstance(frame, str) for frame in frames):
        raise ValueError("renderer report has an invalid frames list")
    return [Path(frame) for frame in frames]


def _state_fingerprints(report: dict[str, Any]) -> list[str]:
    samples = report.get("state_samples")
    if not isinstance(samples, list):
        raise ValueError("renderer report has no state samples")
    fingerprints = [sample.get("state_fingerprint") for sample in samples if isinstance(sample, dict)]
    if len(fingerprints) != len(samples) or not all(isinstance(value, str) for value in fingerprints):
        raise ValueError("renderer report has an invalid state fingerprint")
    return fingerprints


def _repeat_issue(
    left: dict[str, Any], right: dict[str, Any]
) -> RepeatComparisonIssue | None:
    for key in ("frame_count", "width", "height"):
        if left.get(key) != right.get(key):
            return RepeatComparisonIssue(
                0,
                f"{key}_mismatch",
                str(left.get(key)),
                str(right.get(key)),
            )
    left_frames = _report_frame_paths(left)
    right_frames = _report_frame_paths(right)
    for index, (left_frame, right_frame) in enumerate(zip(left_frames, right_frames, strict=False)):
        if _png_dimensions(left_frame) != _png_dimensions(right_frame):
            return RepeatComparisonIssue(index, "frame_dimensions_mismatch")
    frame_issue = compare_repeat_hashes(
        [rgba_sha256(frame) for frame in left_frames],
        [rgba_sha256(frame) for frame in right_frames],
    )
    if frame_issue is not None:
        return frame_issue
    state_issue = compare_repeat_hashes(_state_fingerprints(left), _state_fingerprints(right))
    if state_issue is None:
        return None
    return RepeatComparisonIssue(
        state_issue.frame,
        "state_fingerprint_mismatch"
        if state_issue.reason == "rgba_hash_mismatch"
        else state_issue.reason,
        state_issue.left,
        state_issue.right,
    )


def _metric_value(stderr: str, label: str) -> float:
    matches = re.findall(rf"{re.escape(label)}:([0-9]+(?:\.[0-9]+)?|inf)", stderr, re.I)
    if not matches:
        raise ValueError(f"FFmpeg did not report {label}: {stderr}")
    value = matches[-1]
    return float("inf") if value.lower() == "inf" else float(value)


def _quality_metrics(
    reference_pattern: Path,
    candidate: Path,
    *,
    fps: int,
    candidate_is_video: bool,
) -> tuple[float, float]:
    command = ["ffmpeg", "-v", "info", "-framerate", str(fps), "-i", str(reference_pattern)]
    if candidate_is_video:
        command.extend(["-i", str(candidate)])
    else:
        command.extend(["-framerate", str(fps), "-i", str(candidate)])
    result = _run(
        [
            *command,
            "-lavfi",
            "[0:v][1:v]ssim;[0:v][1:v]psnr",
            "-f",
            "null",
            "-",
        ]
    )
    return _metric_value(result.stderr, "All"), _metric_value(result.stderr, "average")


def _encode_h264(
    frames: Path,
    destination: Path,
    *,
    fps: int,
    encoder: EncoderSpec,
) -> None:
    _run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-framerate",
            str(fps),
            "-i",
            str(frames),
            "-c:v",
            "libx264",
            "-preset",
            encoder.preset,
            "-crf",
            str(encoder.crf),
            "-pix_fmt",
            "yuv420p",
            str(destination),
        ]
    )


def _build_benchmark_job(
    run_dir: Path,
    sequence_id: str,
    *,
    frames: int,
    output_directory: Path,
    backend: RendererBackend,
) -> dict[str, object]:
    script = ScriptArtifact.model_validate_json((run_dir / "script.json").read_text(encoding="utf-8"))
    local = load_local_sequence_plan(run_dir / "local-sequence-plan.json")
    sequence = next((item for item in local.sequences if item.sequence_id == sequence_id), None)
    if sequence is None:
        raise ValueError(f"local sequence not found: {sequence_id}")
    if frames > sequence.duration_frames:
        raise ValueError(f"--frames exceeds {sequence_id} duration: {frames} / {sequence.duration_frames}")
    simulation = load_simulation(run_dir, script)
    return {
        "job_kind": "sequence",
        "sequence_id": sequence.sequence_id,
        "scene_graph": sequence.scene_graph,
        "canonical_fps": local.defaults.fps,
        "duration_frames": sequence.duration_frames,
        "frame_count": frames,
        "output_directory": str(output_directory),
        "output": {
            "width": local.defaults.width,
            "height": local.defaults.height,
            "fps": local.defaults.fps,
        },
        "timeline": _timeline_payload(sequence),
        "canonical_state_cache": _canonical_state_cache(sequence),
        "sample_frames": list(range(frames)),
        "physics": _physics_payload(simulation),
        "style": _style_payload(simulation),
        "renderer_backend": backend,
    }


def _render_job(job: dict[str, object], root: Path) -> dict[str, Any]:
    from .sequence_render import LocalSequenceRenderBackend

    backend = LocalSequenceRenderBackend()
    report_path = backend.render_frames(job, root)
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    requested = payload.get("backend", {}).get("requested") if isinstance(payload.get("backend"), dict) else None
    actual = payload.get("backend", {}).get("actual") if isinstance(payload.get("backend"), dict) else None
    if requested not in ("metal", "swiftshader") or actual != requested:
        raise RuntimeError(f"renderer attestation failed: requested={requested!r} actual={actual!r}")
    return payload


def benchmark_render(
    run_dir: Path,
    *,
    sequence_id: str,
    frames: int,
    report_path: Path | None = None,
) -> Path:
    if frames < 1:
        raise ValueError("--frames must be positive")
    from .sequence_render import LocalSequenceRenderBackend

    LocalSequenceRenderBackend().check_dependencies()
    settings = resolve_run_settings(run_dir)
    encoder = EncoderSpec(
        preset=settings.render.x264_preset,
        crf=settings.render.x264_crf,
    )
    root = Path(tempfile.mkdtemp(prefix="video-harness-render-benchmark-"))
    destination = report_path or root / "render-benchmark.json"
    first_job = _build_benchmark_job(
        run_dir,
        sequence_id,
        frames=frames,
        output_directory=root / "metal-first",
        backend="metal",
    )
    first = _render_job(
        first_job,
        root / "metal-first",
    )
    second = _render_job(
        _build_benchmark_job(run_dir, sequence_id, frames=frames, output_directory=root / "metal-second", backend="metal"),
        root / "metal-second",
    )
    exact_issue = _repeat_issue(first, second)
    if exact_issue is not None:
        atomic_write(
            destination,
            json.dumps(
                {
                    "schema_version": 1,
                    "benchmark_root": str(root),
                    "sequence_id": sequence_id,
                    "frames": frames,
                    "same_backend": {
                        "backend": "metal",
                        "exact_rgba_hashes": False,
                        "state_fingerprints": False,
                        "issue": asdict(exact_issue),
                        "first": first.get("backend"),
                        "second": second.get("backend"),
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
        )
        raise RuntimeError(
            f"same-backend determinism failed for metal {sequence_id} frame {exact_issue.frame}: "
            f"{exact_issue.reason} ({exact_issue.left!r} / {exact_issue.right!r}); report: {destination}"
        )
    swiftshader = _render_job(
        _build_benchmark_job(run_dir, sequence_id, frames=frames, output_directory=root / "swiftshader", backend="swiftshader"),
        root / "swiftshader",
    )
    first_frames = _report_frame_paths(first)
    swiftshader_frames = _report_frame_paths(swiftshader)
    if len(first_frames) != len(swiftshader_frames):
        raise RuntimeError("cross-backend frame count differs")
    encoded = root / "metal-h264-baseline.mp4"
    output = first_job["output"]
    if not isinstance(output, dict) or not isinstance(output.get("fps"), int):
        raise ValueError("benchmark job has no integer FPS")
    fps = output["fps"]
    _encode_h264(
        root / "metal-first" / "frame-%06d.png",
        encoded,
        fps=fps,
        encoder=encoder,
    )
    encode_ssim, encode_psnr = _quality_metrics(
        root / "metal-first" / "frame-%06d.png", encoded, fps=fps, candidate_is_video=True
    )
    cross_ssim, cross_psnr = _quality_metrics(
        root / "metal-first" / "frame-%06d.png",
        root / "swiftshader" / "frame-%06d.png",
        fps=fps,
        candidate_is_video=False,
    )
    quality = BackendQualityResult(
        ssim=cross_ssim,
        psnr=cross_psnr,
        encode_baseline_ssim=encode_ssim,
        encode_baseline_psnr=encode_psnr,
    )
    payload = {
        "schema_version": 1,
        "benchmark_root": str(root),
        "sequence_id": sequence_id,
        "frames": frames,
        "same_backend": {
            "backend": "metal",
            "exact_rgba_hashes": True,
            "state_fingerprints": True,
            "first": first.get("backend"),
            "second": second.get("backend"),
        },
        "cross_backend": {
            "metal": first.get("backend"),
            "swiftshader": swiftshader.get("backend"),
            **asdict(quality),
            "visual_regression_passed": quality.visual_regression_passed,
            "cache_eligible": quality.cache_eligible,
        },
        "encode_baseline": {
            "codec": "libx264",
            "preset": encoder.preset,
            "crf": encoder.crf,
            "ssim": encode_ssim,
            "psnr": encode_psnr,
        },
    }
    atomic_write(destination, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    if not quality.visual_regression_passed:
        raise RuntimeError(
            f"cross-backend visual regression failed for {sequence_id}; report: {destination}"
        )
    return destination


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify deterministic local render output.")
    parser.add_argument("run", type=Path, help="run directory containing local sequence plans")
    parser.add_argument("--sequence", required=True, help="local sequence ID, for example SEQ01")
    parser.add_argument("--frames", type=int, required=True, help="bounded output-frame count")
    parser.add_argument("--report", type=Path, help="explicit destination for render-benchmark.json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = benchmark_render(
            args.run,
            sequence_id=args.sequence,
            frames=args.frames,
            report_path=args.report,
        )
    except (OSError, subprocess.SubprocessError, ValueError, RuntimeError) as error:
        print(f"benchmark-render failed: {error}")
        return 1
    print(report)
    return 0
