from __future__ import annotations

import json
from pathlib import Path

import pytest

from video_harness.performance import PerformanceRecorder, RenderPerformanceReport


def test_recorder_aggregates_labeled_phases_without_writing_per_event(
    tmp_path: Path,
) -> None:
    """Removing in-memory aggregation must not silently leave a partial report."""
    clock = iter([10.0, 10.25, 11.0, 11.75]).__next__
    recorder = PerformanceRecorder(clock=clock)

    with recorder.phase("ffmpeg_encode", sequence_id="SEQ01"):
        pass
    with recorder.phase("qa", quality="draft"):
        pass

    report = recorder.report()
    assert report.phase_totals_ms == {"ffmpeg_encode": 250.0, "qa": 750.0}
    assert [(event.name, event.labels) for event in report.phase_events] == [
        ("ffmpeg_encode", {"sequence_id": "SEQ01"}),
        ("qa", {"quality": "draft"}),
    ]
    assert list(tmp_path.iterdir()) == []


def test_report_write_is_atomic_and_includes_renderer_and_variant_metadata(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Dropping renderer attestation or variant reuse data must change the report."""
    import video_harness.performance as module

    writes: list[tuple[Path, str]] = []
    monkeypatch.setattr(module, "atomic_write", lambda path, content: writes.append((path, content)))
    recorder = PerformanceRecorder(
        quality="final",
        encoder_settings={"codec": "libx264", "preset": "slow", "crf": 18},
    )
    recorder.record_renderer_report(
        {
            "sequence_id": "SEQ01",
            "frame_count": 30,
            "width": 1920,
            "height": 1080,
            "fps": 30,
            "backend": {
                "requested": "metal",
                "actual": "metal",
                "vendor": "Apple",
                "renderer": "ANGLE Metal Renderer: Apple M1",
            },
            "timings": {
                "frame_count": 30,
                "render_ms": 10.0,
                "capture_ms": 5.0,
                "write_ms": 2.0,
                "total_ms": 17.0,
            },
        },
        capture_method="playwright_locator_screenshot",
    )
    recorder.record_variant_output(
        variant_id="explain",
        rendered_sequence_ids=["SEQ01"],
        reused_sequence_ids=["SEQ02"],
        rendered_frame_count=30,
        reused_frame_count=20,
    )

    path = recorder.write_performance_report(tmp_path)

    assert path == tmp_path / "render-performance.json"
    assert writes and writes[0][0] == path
    payload = json.loads(writes[0][1])
    assert payload["rendered_sequence_ids"] == ["SEQ01"]
    assert payload["reused_sequence_ids"] == ["SEQ02"]
    assert payload["output_frame_counts"] == {
        "variant:explain": {
            "rendered_frame_count": 30,
            "reused_frame_count": 20,
            "rendered_sequence_ids": ["SEQ01"],
            "reused_sequence_ids": ["SEQ02"],
        }
    }
    assert payload["renderer_reports"] == [
        {
            "sequence_id": "SEQ01",
            "frame_count": 30,
                "width": 1920,
                "height": 1080,
                "fps": 30,
                "browser_version": "unknown",
                "capture_method": "playwright_locator_screenshot",
                "capture_timing_mode": "legacy_combined",
                "capture_transport_bytes": 0,
            "backend": {
                "requested": "metal",
                "actual": "metal",
                "vendor": "Apple",
                "renderer": "ANGLE Metal Renderer: Apple M1",
            },
                "timings": {
                    "frame_count": 30,
                    "initialization_ms": 0.0,
                    "render_ms": 10.0,
                    "capture_ms": 5.0,
                    "canvas_encode_capture_ms": 0.0,
                    "browser_to_node_transfer_ms": 0.0,
                    "write_ms": 2.0,
                "total_ms": 17.0,
            },
        }
    ]
    assert payload["encoder_settings"] == {
        "codec": "libx264", "preset": "slow", "crf": 18
    }


def test_legacy_performance_report_defaults_per_output_counts_to_empty():
    report = RenderPerformanceReport.model_validate({"schema_version": 1})

    assert report.output_frame_counts == {}


def test_renderer_report_keeps_the_effective_capture_method_from_renderer():
    """Changing the selected transport must be visible to performance operators."""
    recorder = PerformanceRecorder()

    recorder.record_renderer_report(
        {
            "sequence_id": "SEQ01",
            "frame_count": 1,
            "width": 1920,
            "height": 1080,
            "fps": 30,
            "capture_method": "data-url-png",
            "capture_transport_bytes": 4321,
            "backend": {
                "requested": "metal",
                "actual": "metal",
                "vendor": "Apple",
                "renderer": "ANGLE Metal",
            },
            "timings": {
                "frame_count": 1,
                "render_ms": 1.0,
                "capture_ms": 2.0,
                "write_ms": 3.0,
                "total_ms": 6.0,
            },
        }
    )

    report = recorder.report().renderer_reports[0]

    assert report.capture_method == "data-url-png"
    assert report.capture_transport_bytes == 4321


def test_renderer_report_defaults_missing_capture_transport_bytes_to_zero():
    """Legacy renderer payloads remain reportable without a byte measurement."""
    recorder = PerformanceRecorder()

    recorder.record_renderer_report(
        {
            "sequence_id": "SEQ01",
            "frame_count": 1,
            "width": 1920,
            "height": 1080,
            "fps": 30,
            "backend": {
                "requested": "metal",
                "actual": "metal",
                "vendor": "Apple",
                "renderer": "ANGLE Metal",
            },
            "timings": {
                "frame_count": 1,
                "render_ms": 1.0,
                "capture_ms": 2.0,
                "write_ms": 3.0,
                "total_ms": 6.0,
            },
        }
    )

    report = recorder.report().renderer_reports[0]
    assert report.capture_transport_bytes == 0
    assert report.browser_version == "unknown"
    assert report.capture_timing_mode == "legacy_combined"
    assert report.timings.initialization_ms == 0
    assert report.timings.canvas_encode_capture_ms == 0
    assert report.timings.browser_to_node_transfer_ms == 0


def test_renderer_report_exposes_initialization_browser_and_split_capture_timings():
    """Collapsing initialization or transfer back into capture hides the bottleneck."""
    recorder = PerformanceRecorder()

    recorder.record_renderer_report(
        {
            "sequence_id": "SEQ01",
            "frame_count": 1,
            "width": 1920,
            "height": 1080,
            "fps": 30,
            "browser_version": "Chromium 140.0.7339.16",
            "capture_method": "data-url-png",
            "capture_timing_mode": "split",
            "backend": {
                "requested": "swiftshader",
                "actual": "swiftshader",
                "vendor": "Google",
                "renderer": "ANGLE SwiftShader",
            },
            "timings": {
                "frame_count": 1,
                "initialization_ms": 4.0,
                "render_ms": 1.0,
                "capture_ms": 5.0,
                "canvas_encode_capture_ms": 3.0,
                "browser_to_node_transfer_ms": 2.0,
                "write_ms": 6.0,
                "total_ms": 16.0,
            },
        }
    )

    report = recorder.report()
    renderer = report.renderer_reports[0]
    assert renderer.browser_version == "Chromium 140.0.7339.16"
    assert renderer.capture_timing_mode == "split"
    assert renderer.timings.initialization_ms == 4.0
    assert renderer.timings.canvas_encode_capture_ms == 3.0
    assert renderer.timings.browser_to_node_transfer_ms == 2.0
    assert {
        event.name: event.duration_ms for event in report.phase_events
    } == {
        "renderer_initialization": 4.0,
        "webgl_render": 1.0,
        "canvas_capture": 5.0,
        "canvas_encode_capture": 3.0,
        "browser_to_node_transfer": 2.0,
        "frame_write": 6.0,
    }


def test_report_exposes_per_output_totals_and_cumulative_frame_counts():
    """Dropping base totals or frame counts makes render work externally underivable."""
    now = [1.0]
    recorder = PerformanceRecorder(clock=lambda: now[0])

    with recorder.phase("base_output", output_id="final"):
        now[0] += 0.4
    recorder.record_base_output(
        output_id="final",
        rendered_sequence_ids=["SEQ01"],
        reused_sequence_ids=["SEQ02"],
        rendered_frame_count=30,
        reused_frame_count=20,
    )
    with recorder.phase("variant", variant_id="explain"):
        now[0] += 0.6
    recorder.record_variant_output(
        variant_id="explain",
        rendered_sequence_ids=["SEQ02"],
        reused_sequence_ids=["SEQ01"],
        rendered_frame_count=20,
        reused_frame_count=30,
    )

    report = recorder.report()
    assert report.output_totals_ms == {
        "base:final": pytest.approx(400.0),
        "variant:explain": pytest.approx(600.0),
    }
    assert report.rendered_frame_count == 50
    assert report.reused_frame_count == 50
    assert report.rendered_sequence_ids == ["SEQ01", "SEQ02"]
    assert report.reused_sequence_ids == ["SEQ01", "SEQ02"]
    assert {
        output_id: counts.model_dump()
        for output_id, counts in report.output_frame_counts.items()
    } == {
        "base:final": {
            "rendered_frame_count": 30,
            "reused_frame_count": 20,
            "rendered_sequence_ids": ["SEQ01"],
            "reused_sequence_ids": ["SEQ02"],
        },
        "variant:explain": {
            "rendered_frame_count": 20,
            "reused_frame_count": 30,
            "rendered_sequence_ids": ["SEQ02"],
            "reused_sequence_ids": ["SEQ01"],
        },
    }


def test_approved_final_outputs_expose_4346_rendered_frames_directly():
    """The accepted base-final plus selective variants subtotal is first-class."""
    recorder = PerformanceRecorder()
    recorder.record_base_output(
        output_id="final",
        rendered_sequence_ids=["SEQ01", "SEQ02", "SEQ03", "SEQ04"],
        reused_sequence_ids=[],
        rendered_frame_count=2286,
        reused_frame_count=0,
    )
    for variant_id, rendered_ids, rendered_frames, reused_frames in (
        ("balanced", [], 0, 2286),
        ("explain", ["SEQ02"], 1393, 893),
        ("dynamic", ["SEQ01"], 463, 1823),
        ("cinematic", ["SEQ04"], 204, 2082),
    ):
        recorder.record_variant_output(
            variant_id=variant_id,
            rendered_sequence_ids=rendered_ids,
            reused_sequence_ids=[
                sequence_id
                for sequence_id in ("SEQ01", "SEQ02", "SEQ03", "SEQ04")
                if sequence_id not in rendered_ids
            ],
            rendered_frame_count=rendered_frames,
            reused_frame_count=reused_frames,
        )

    counts = recorder.report().output_frame_counts
    final_rendered_frames = sum(
        count.rendered_frame_count
        for output_id, count in counts.items()
        if output_id == "base:final" or output_id.startswith("variant:")
    )

    assert final_rendered_frames == 4346
