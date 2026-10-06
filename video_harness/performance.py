from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from pydantic import Field

from .models import StrictModel
from .storage import atomic_write


class PerformancePhaseEvent(StrictModel):
    name: str = Field(min_length=1)
    duration_ms: float = Field(ge=0)
    labels: dict[str, str] = Field(default_factory=dict)


class RendererBackend(StrictModel):
    requested: Literal["metal", "swiftshader", "blender_eevee"]
    actual: Literal["metal", "swiftshader", "blender_eevee", "unknown"]
    vendor: str
    renderer: str


class RendererTimings(StrictModel):
    frame_count: int = Field(ge=0)
    initialization_ms: float = Field(default=0, ge=0)
    render_ms: float = Field(ge=0)
    capture_ms: float = Field(ge=0)
    canvas_encode_capture_ms: float = Field(default=0, ge=0)
    browser_to_node_transfer_ms: float = Field(default=0, ge=0)
    write_ms: float = Field(ge=0)
    total_ms: float = Field(ge=0)


class RendererPerformanceReport(StrictModel):
    sequence_id: str = Field(min_length=1)
    frame_count: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: int = Field(gt=0)
    browser_version: str = Field(default="unknown", min_length=1)
    capture_method: str = Field(min_length=1)
    capture_timing_mode: Literal[
        "legacy_combined", "split", "playwright_combined"
    ] = "legacy_combined"
    capture_transport_bytes: int = Field(default=0, ge=0)
    backend: RendererBackend
    timings: RendererTimings


class OutputFrameCounts(StrictModel):
    """Rendered and reused frame volume attributable to one published output."""

    rendered_frame_count: int = Field(default=0, ge=0)
    reused_frame_count: int = Field(default=0, ge=0)
    rendered_sequence_ids: list[str] = Field(default_factory=list)
    reused_sequence_ids: list[str] = Field(default_factory=list)


class RenderPerformanceReport(StrictModel):
    schema_version: Literal[1] = 1
    quality: Literal["draft", "final"] | None = None
    phase_events: list[PerformancePhaseEvent] = Field(default_factory=list)
    phase_totals_ms: dict[str, float] = Field(default_factory=dict)
    output_totals_ms: dict[str, float] = Field(default_factory=dict)
    output_frame_counts: dict[str, OutputFrameCounts] = Field(default_factory=dict)
    rendered_frame_count: int = Field(default=0, ge=0)
    reused_frame_count: int = Field(default=0, ge=0)
    rendered_sequence_ids: list[str] = Field(default_factory=list)
    reused_sequence_ids: list[str] = Field(default_factory=list)
    avoided_copy_files: int = Field(default=0, ge=0)
    avoided_copy_bytes: int = Field(default=0, ge=0)
    renderer_reports: list[RendererPerformanceReport] = Field(default_factory=list)
    encoder_settings: dict[str, str | int | float] = Field(default_factory=dict)


class PerformanceRecorder:
    """Accumulate render diagnostics in memory until the enclosing run is publishable."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] | None = None,
        quality: Literal["draft", "final"] | None = None,
        encoder_settings: Mapping[str, str | int | float] | None = None,
    ) -> None:
        self._clock = clock or time.perf_counter
        self._quality = quality
        self._encoder_settings = dict(encoder_settings or {})
        self._phase_events: list[PerformancePhaseEvent] = []
        self._renderer_reports: list[RendererPerformanceReport] = []
        self._rendered_sequence_ids: set[str] = set()
        self._reused_sequence_ids: set[str] = set()
        self._output_frame_counts: dict[str, OutputFrameCounts] = {}
        self._rendered_frame_count = 0
        self._reused_frame_count = 0
        self._avoided_copy_files = 0
        self._avoided_copy_bytes = 0

    @contextmanager
    def phase(self, name: str, **labels: object) -> Iterator[dict[str, object]]:
        """Record a wall-clock phase without logging or writing on the hot path."""
        started = self._clock()
        try:
            yield labels
        finally:
            duration_ms = (self._clock() - started) * 1000
            self._phase_events.append(
                PerformancePhaseEvent(
                    name=name,
                    duration_ms=duration_ms,
                    labels={key: str(value) for key, value in sorted(labels.items())},
                )
            )

    def record_renderer_report(
        self,
        payload: Mapping[str, object],
        *,
        capture_method: str = "playwright_locator_screenshot",
        fps: int | None = None,
    ) -> None:
        """Keep normalized TypeScript renderer telemetry with the Python report."""
        report_payload = {
            key: payload[key]
            for key in (
                "sequence_id",
                "frame_count",
                "width",
                "height",
                "backend",
                "timings",
            )
        }
        report_payload["fps"] = payload.get("fps", fps)
        report_payload["browser_version"] = payload.get(
            "browser_version", "unknown"
        )
        report_payload["capture_method"] = payload.get(
            "capture_method", capture_method
        )
        report_payload["capture_timing_mode"] = payload.get(
            "capture_timing_mode", "legacy_combined"
        )
        report_payload["capture_transport_bytes"] = payload.get(
            "capture_transport_bytes", 0
        )
        report = RendererPerformanceReport.model_validate(
            report_payload
        )
        self._renderer_reports.append(report)
        labels = {
            "sequence_id": report.sequence_id,
            "backend": report.backend.actual,
            "capture_method": report.capture_method,
        }
        for name, duration_ms in (
            ("renderer_initialization", report.timings.initialization_ms),
            ("blender_render" if report.backend.actual == "blender_eevee" else "webgl_render", report.timings.render_ms),
            ("canvas_capture", report.timings.capture_ms),
            ("canvas_encode_capture", report.timings.canvas_encode_capture_ms),
            (
                "browser_to_node_transfer",
                report.timings.browser_to_node_transfer_ms,
            ),
            ("frame_write", report.timings.write_ms),
        ):
            self._phase_events.append(
                PerformancePhaseEvent(name=name, duration_ms=duration_ms, labels=labels)
            )

    def _record_output_work(
        self,
        *,
        output_key: str,
        rendered_sequence_ids: list[str],
        reused_sequence_ids: list[str],
        rendered_frame_count: int,
        reused_frame_count: int,
    ) -> None:
        if rendered_frame_count < 0 or reused_frame_count < 0:
            raise ValueError("frame counts cannot be negative")
        self._rendered_sequence_ids.update(rendered_sequence_ids)
        self._reused_sequence_ids.update(reused_sequence_ids)
        self._rendered_frame_count += rendered_frame_count
        self._reused_frame_count += reused_frame_count
        current = self._output_frame_counts.get(output_key, OutputFrameCounts())
        self._output_frame_counts[output_key] = OutputFrameCounts(
            rendered_frame_count=(
                current.rendered_frame_count + rendered_frame_count
            ),
            reused_frame_count=current.reused_frame_count + reused_frame_count,
            rendered_sequence_ids=sorted(
                set(current.rendered_sequence_ids) | set(rendered_sequence_ids)
            ),
            reused_sequence_ids=sorted(
                set(current.reused_sequence_ids) | set(reused_sequence_ids)
            ),
        )

    def record_base_output(
        self,
        *,
        output_id: Literal["draft", "final"],
        rendered_sequence_ids: list[str],
        reused_sequence_ids: list[str],
        rendered_frame_count: int,
        reused_frame_count: int,
    ) -> None:
        self._record_output_work(
            output_key=f"base:{output_id}",
            rendered_sequence_ids=rendered_sequence_ids,
            reused_sequence_ids=reused_sequence_ids,
            rendered_frame_count=rendered_frame_count,
            reused_frame_count=reused_frame_count,
        )

    def record_variant_output(
        self,
        *,
        variant_id: str,
        rendered_sequence_ids: list[str],
        reused_sequence_ids: list[str],
        rendered_frame_count: int = 0,
        reused_frame_count: int = 0,
        avoided_copy_files: int = 0,
        avoided_copy_bytes: int = 0,
    ) -> None:
        if not variant_id:
            raise ValueError("variant ID cannot be empty")
        if avoided_copy_files < 0 or avoided_copy_bytes < 0:
            raise ValueError("avoided copy metrics cannot be negative")
        self._record_output_work(
            output_key=f"variant:{variant_id}",
            rendered_sequence_ids=rendered_sequence_ids,
            reused_sequence_ids=reused_sequence_ids,
            rendered_frame_count=rendered_frame_count,
            reused_frame_count=reused_frame_count,
        )
        self._avoided_copy_files += avoided_copy_files
        self._avoided_copy_bytes += avoided_copy_bytes

    def report(self) -> RenderPerformanceReport:
        totals: dict[str, float] = {}
        output_totals: dict[str, float] = {}
        for event in self._phase_events:
            totals[event.name] = totals.get(event.name, 0.0) + event.duration_ms
            output_key = None
            if event.name == "base_output" and event.labels.get("output_id"):
                output_key = f"base:{event.labels['output_id']}"
            elif event.name == "variant" and event.labels.get("variant_id"):
                output_key = f"variant:{event.labels['variant_id']}"
            if output_key is not None:
                output_totals[output_key] = (
                    output_totals.get(output_key, 0.0) + event.duration_ms
                )
        return RenderPerformanceReport(
            quality=self._quality,
            phase_events=list(self._phase_events),
            phase_totals_ms={name: totals[name] for name in sorted(totals)},
            output_totals_ms={
                name: output_totals[name] for name in sorted(output_totals)
            },
            output_frame_counts={
                name: self._output_frame_counts[name]
                for name in sorted(self._output_frame_counts)
            },
            rendered_frame_count=self._rendered_frame_count,
            reused_frame_count=self._reused_frame_count,
            rendered_sequence_ids=sorted(self._rendered_sequence_ids),
            reused_sequence_ids=sorted(self._reused_sequence_ids),
            avoided_copy_files=self._avoided_copy_files,
            avoided_copy_bytes=self._avoided_copy_bytes,
            renderer_reports=list(self._renderer_reports),
            encoder_settings={
                name: self._encoder_settings[name]
                for name in sorted(self._encoder_settings)
            },
        )

    def write_performance_report(self, run_dir: Path) -> Path:
        path = run_dir / "render-performance.json"
        atomic_write(path, self.report().model_dump_json(indent=2) + "\n")
        return path
