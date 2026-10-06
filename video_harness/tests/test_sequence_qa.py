from __future__ import annotations

from video_harness.settings import ArchivedV5HarnessSettings

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from video_harness.sequence_qa import (
    DecodedFrame,
    SequenceStateReport,
    decode_frame_hashes,
    detect_black_frames,
    run_sequence_qa,
    validate_concat_boundaries,
    validate_media_contract,
)
from video_harness.settings import HarnessSettings, settings_sha256
from video_harness.media import (
    AudioPlacement,
    MediaInfo,
    OutputSpec,
    create_contact_sheet,
    mux_audio_timeline,
    probe_media,
)
from video_harness.production import script_sha256
from video_harness.performance import PerformanceRecorder
from video_harness.production_models import ProductionPlan
from video_harness.sequence_models import LocalSequencePlan, OnlinePlan
from video_harness.sequence_render import (
    LocalSequenceRenderBackend,
    SequenceArtifactSource,
    SequenceRenderReport,
    _normalize_frame_report,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _state_sample(frame: int) -> dict[str, object]:
    return {
        "canonical_frame": frame,
        "simulation_time": frame / 10,
        "visible_layers": ["orbitGroup", "sightline", "sightlineHistory"],
        "geometry_operation_keys": [f"geometry-{frame}"],
        "camera": {"position": [0.0, 1.0, 5.0], "target": [0.0, 0.0, 0.0]},
        "entity_scales": {"earth": 1.0, "mars": 1.0},
        "state_fingerprint": f"fnv1a32:{frame:08x}",
    }


@dataclass
class QaFixture:
    run_dir: Path
    production: ProductionPlan
    local: LocalSequencePlan
    online: OnlinePlan
    render_report: SequenceRenderReport
    state_report_path: Path
    media_infos: dict[Path, MediaInfo]

    def arguments(self) -> dict[str, object]:
        return {
            "run_dir": self.run_dir,
            "production": self.production,
            "local": self.local,
            "online": self.online,
            "render_report": self.render_report,
            "quality": "final",
        }

    def state_payload(self) -> dict[str, object]:
        return json.loads(self.state_report_path.read_text(encoding="utf-8"))

    def write_state_payload(self, payload: dict[str, object]) -> None:
        _write_json(self.state_report_path, payload)


@pytest.fixture
def valid_qa_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> QaFixture:
    run_dir = tmp_path / "run"
    production = ProductionPlan.model_validate(
        {
            "schema_version": 2,
            "script_sha256": "a" * 64,
            "defaults": {
                "width": 160,
                "height": 90,
                "fps": 10,
                "preview_interval_seconds": 0.5,
                "scene_transition": {
                    "mode": "cut",
                    "duration_seconds": 0.0,
                    "fade_seconds": 0.0,
                },
            },
            "style_bible": {
                "visual_mode": "scientific visualization",
                "entities": [],
                "palette": ["navy", "white"],
                "lighting": "stable",
                "excluded_elements": ["logos"],
            },
            "scenes": [
                {"scene_id": 1, "duration_seconds": 3.0, "shots": []},
                {"scene_id": 2, "duration_seconds": 3.5, "shots": []},
            ],
            "visual_sequences": [
                {
                    "sequence_id": "SEQ01",
                    "scene_ids": [1, 2],
                    "primary_route": "local",
                    "purpose": "continuous explanation",
                    "visual_beat_ids": ["B01", "B02"],
                }
            ],
            "visual_beats": [
                {
                    "beat_id": "B01",
                    "scene_id": 1,
                    "start_frame": 0,
                    "end_frame": 30,
                    "primary_event": "first state",
                    "relationship_owner": "simulation",
                },
                {
                    "beat_id": "B02",
                    "scene_id": 2,
                    "start_frame": 30,
                    "end_frame": 65,
                    "primary_event": "continued state",
                    "relationship_owner": "simulation",
                },
            ],
        }
    )
    production_path = run_dir / "production-plan.json"
    production_path.parent.mkdir(parents=True)
    production_path.write_text(production.model_dump_json(indent=2) + "\n", encoding="utf-8")
    production_hash = script_sha256(production_path)
    local = LocalSequencePlan.model_validate(
        {
            "schema_version": 1,
            "script_sha256": "a" * 64,
            "production_plan_sha256": production_hash,
            "defaults": {"width": 160, "height": 90, "fps": 10},
            "sequences": [
                {
                    "sequence_id": "SEQ01",
                    "scene_ids": [1, 2],
                    "duration_frames": 65,
                    "render_mode": "simulation",
                    "scene_graph": "shared-science-scene",
                    "scene_spans": [
                        {
                            "scene_id": 1,
                            "start_frame": 0,
                            "end_frame": 30,
                            "audio_start_frame": 0,
                            "audio_end_frame": 30,
                            "tail_silence_frames": 0,
                        },
                        {
                            "scene_id": 2,
                            "start_frame": 30,
                            "end_frame": 65,
                            "audio_start_frame": 30,
                            "audio_end_frame": 65,
                            "tail_silence_frames": 0,
                        },
                    ],
                    "timeline": [
                        {
                            "beat_id": "B01",
                            "start_frame": 0,
                            "end_frame": 30,
                            "simulation_time_start": 0.0,
                            "simulation_time_end": 3.0,
                            "controller": "first-controller",
                            "patch_targets": ["geometry", "layers"],
                            "priority": 0,
                        },
                        {
                            "beat_id": "B02",
                            "start_frame": 30,
                            "end_frame": 65,
                            "simulation_time_start": 3.0,
                            "simulation_time_end": 6.5,
                            "controller": "second-controller",
                            "patch_targets": ["geometry", "camera"],
                            "priority": 0,
                        },
                    ],
                }
            ],
        }
    )
    local_path = run_dir / "local-sequence-plan.json"
    local_path.write_text(local.model_dump_json(indent=2) + "\n", encoding="utf-8")
    local_hash = script_sha256(local_path)
    online = OnlinePlan.model_validate(
        {
            "schema_version": 1,
            "script_sha256": "a" * 64,
            "production_plan_sha256": production_hash,
            "shots": [
                {
                    "online_shot_id": "ON-B01",
                    "beat_ids": ["B01"],
                    "scene_ids": [1],
                    "source_sequence_id": "SEQ01",
                    "source_start_frame": 0,
                    "source_end_frame": 40,
                    "duration_seconds": 4.0,
                    "preferred_mode": "v2v",
                    "science_authority": "local_reference",
                    "primary_event": "first state",
                    "invariants": ["state stays continuous"],
                    "reference_video_file": "videoFiles/onlineReferences/ON-B01.mp4",
                    "prompt_file": "videoFiles/prompts/online/SEQ01/ON-B01.txt",
                    "metadata_file": "videoFiles/prompts/online/SEQ01/ON-B01.json",
                }
            ],
        }
    )
    artifact_root = run_dir.resolve()
    state_report_path = artifact_root / "videoFiles/sequences/final/SEQ01-frame-report.json"
    _write_json(
        state_report_path,
        {
            "sequence_id": "SEQ01",
            "frame_count": 65,
            "width": 160,
            "height": 90,
            "frames": [f".render-cache/frame-{frame:06d}.png" for frame in range(65)],
            "state_samples": [_state_sample(frame) for frame in range(65)],
        },
    )
    for frame in range(65):
        frame_path = artifact_root / ".render-cache" / f"frame-{frame:06d}.png"
        frame_path.parent.mkdir(parents=True, exist_ok=True)
        frame_path.write_bytes(b"png")
    report = SequenceRenderReport.model_validate(
        {
            "quality": "final",
            "artifact_root": artifact_root,
            "production_plan_sha256": production_hash,
            "local_sequence_plan_sha256": local_hash,
            "sequences": [
                {
                    "sequence_id": "SEQ01",
                    "frame_count": 65,
                    "width": 160,
                    "height": 90,
                    "fps": 10,
                    "master_file": "videoFiles/sequences/final/SEQ01.mp4",
                    "narrated_file": "videoFiles/sequences/final/SEQ01-narrated.mp4",
                    "state_report_file": "videoFiles/sequences/final/SEQ01-frame-report.json",
                    "state_cache_file": "videoFiles/sequences/state-cache/SEQ01.json",
                    "scene_slices": [],
                }
            ],
            "final_file": "final.mp4",
            "final_original_file": "video-only.mp4",
        }
    )
    silent_info = MediaInfo("h264", None, 160, 90, 10.0, 6.5, 65, "yuv420p")
    narrated_info = MediaInfo(
        "h264",
        "aac",
        160,
        90,
        10.0,
        6.5,
        65,
        "yuv420p",
        audio_duration_seconds=6.5,
        audio_end_seconds=6.5,
    )
    media_infos = {
        artifact_root / report.sequences[0].master_file: silent_info,
        artifact_root / report.sequences[0].narrated_file: narrated_info,
        artifact_root / report.final_original_file: silent_info,
        artifact_root / report.final_file: narrated_info,
    }
    for path in media_infos:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake-media")
    reference = artifact_root / "videoFiles/onlineReferences/ON-B01.mp4"
    reference.parent.mkdir(parents=True, exist_ok=True)
    reference.write_bytes(b"reference")

    fixture = QaFixture(
        run_dir=run_dir,
        production=production,
        local=local,
        online=online,
        render_report=report,
        state_report_path=state_report_path,
        media_infos=media_infos,
    )

    def fake_probe(path: Path, *, require_audio: bool = False) -> MediaInfo:
        info = fixture.media_infos[path.resolve()]
        if require_audio and info.audio_codec is None:
            raise ValueError(f"audio stream missing: {path}")
        return info

    def fake_previews(
        _source: Path,
        output_directory: Path,
        _timestamps: list[float],
        names: list[str],
    ) -> list[Path]:
        output_directory.mkdir(parents=True, exist_ok=True)
        paths = [output_directory / name for name in names]
        for path in paths:
            path.write_bytes(b"png")
        return paths

    def fake_contact_sheet(
        _source: Path,
        destination: Path,
        interval_seconds: float = 0.5,
        columns: int = 8,
    ) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"contact-sheet")
        return destination

    monkeypatch.setattr("video_harness.sequence_qa.probe_media", fake_probe)
    monkeypatch.setattr("video_harness.sequence_qa.capture_preview_frames", fake_previews)
    monkeypatch.setattr("video_harness.sequence_qa.create_contact_sheet", fake_contact_sheet)
    monkeypatch.setattr(
        "video_harness.sequence_qa.detect_black_frames", lambda _path, **_kwargs: []
    )
    return fixture


def test_qa_writes_deterministic_half_second_artifacts(valid_qa_fixture: QaFixture):
    report = run_sequence_qa(**valid_qa_fixture.arguments())
    report_path = valid_qa_fixture.run_dir / "qa-report.json"
    first_bytes = report_path.read_bytes()

    second = run_sequence_qa(**valid_qa_fixture.arguments())

    assert report.status == "passed"
    assert second == report
    assert report_path.read_bytes() == first_bytes
    assert report.sequence_results[0].preview_files[:3] == [
        "videoFiles/previews/half-second/SEQ01/000000ms.png",
        "videoFiles/previews/half-second/SEQ01/000500ms.png",
        "videoFiles/previews/half-second/SEQ01/001000ms.png",
    ]
    assert report.contact_sheet_file == "videoFiles/previews/half-second/contact-sheet.png"


def test_draft_qa_uses_effective_render_settings(valid_qa_fixture: QaFixture):
    settings = ArchivedV5HarnessSettings(
        render={"draft_width": 384, "draft_height": 216, "draft_fps": 10}
    )
    rendered = valid_qa_fixture.render_report.sequences[0].model_copy(
        update={"frame_count": 65, "width": 384, "height": 216, "fps": 10}
    )
    valid_qa_fixture.render_report = valid_qa_fixture.render_report.model_copy(
        update={"quality": "draft", "sequences": [rendered]}
    )
    silent = MediaInfo("h264", None, 384, 216, 10.0, 6.5, 65, "yuv420p")
    narrated = MediaInfo(
        "h264",
        "aac",
        384,
        216,
        10.0,
        6.5,
        65,
        "yuv420p",
        audio_duration_seconds=6.5,
        audio_end_seconds=6.5,
    )
    valid_qa_fixture.media_infos = {
        valid_qa_fixture.run_dir / rendered.master_file: silent,
        valid_qa_fixture.run_dir / rendered.narrated_file: narrated,
        valid_qa_fixture.run_dir
        / valid_qa_fixture.render_report.final_original_file: silent,
        valid_qa_fixture.run_dir / valid_qa_fixture.render_report.final_file: narrated,
    }
    state_payload = valid_qa_fixture.state_payload()
    state_payload.update({"width": 384, "height": 216})
    valid_qa_fixture.write_state_payload(state_payload)

    arguments = valid_qa_fixture.arguments()
    arguments.update({"quality": "draft", "settings": settings})
    report = run_sequence_qa(**arguments)

    assert report.issue_codes == []
    assert report.status == "passed"
    assert "report_dimension_mismatch" not in report.issue_codes
    assert "report_fps_mismatch" not in report.issue_codes
    assert "report_frame_count_mismatch" not in report.issue_codes


def test_qa_rejects_external_transition_frames_for_continuous_local_assembly(
    valid_qa_fixture: QaFixture,
):
    transition = valid_qa_fixture.production.defaults.scene_transition.model_copy(
        update={
            "mode": "dip_to_black",
            "duration_seconds": 0.65,
            "fade_seconds": 0.15,
        }
    )
    defaults = valid_qa_fixture.production.defaults.model_copy(
        update={"scene_transition": transition}
    )
    valid_qa_fixture.production = valid_qa_fixture.production.model_copy(
        update={"defaults": defaults}
    )
    silent = MediaInfo("h264", None, 160, 90, 10.0, 7.1, 71, "yuv420p")
    narrated = MediaInfo(
        "h264",
        "aac",
        160,
        90,
        10.0,
        7.1,
        71,
        "yuv420p",
        audio_duration_seconds=7.1,
        audio_end_seconds=7.1,
    )
    valid_qa_fixture.media_infos[
        valid_qa_fixture.run_dir / "video-only.mp4"
    ] = silent
    valid_qa_fixture.media_infos[valid_qa_fixture.run_dir / "final.mp4"] = narrated

    report = run_sequence_qa(**valid_qa_fixture.arguments())

    assert report.status == "failed"
    assert "final_media_frame_count_mismatch" in report.issue_codes
    assert report.settings_sha256 == settings_sha256(HarnessSettings())
    assert report.preview_interval_seconds == 0.5
    assert report.contact_sheet_columns == 8


def test_qa_accepts_renderer_telemetry_without_losing_state_validation(
    valid_qa_fixture: QaFixture,
):
    """Telemetry attached to a valid renderer state report is not a QA error."""
    payload = valid_qa_fixture.state_payload()
    payload.update(
        {
            "browser_version": "151.0.7922.34",
            "capture_method": "data-url-png",
            "capture_timing_mode": "split",
            "capture_transport_bytes": 1234,
            "backend": {
                "requested": "metal",
                "actual": "metal",
                "vendor": "Apple",
                "renderer": "ANGLE Metal",
            },
            "timings": {
                "frame_count": 65,
                "render_ms": 1.0,
                "capture_ms": 2.0,
                "write_ms": 3.0,
                "total_ms": 6.0,
            },
        }
    )
    valid_qa_fixture.write_state_payload(payload)

    assert run_sequence_qa(**valid_qa_fixture.arguments()).status == "passed"


def test_qa_preserves_scientific_graph_text_evidence(valid_qa_fixture: QaFixture):
    payload = valid_qa_fixture.state_payload()
    payload["state_samples"][0]["graph_text"] = [
        {"text": "광량", "object": "GraphText:광량", "rect": [0.6, 0.1, 0.7, 0.2]}
    ]
    valid_qa_fixture.write_state_payload(payload)

    assert run_sequence_qa(**valid_qa_fixture.arguments()).status == "passed"
    parsed = SequenceStateReport.model_validate(payload).model_dump()
    assert parsed["state_samples"][0]["graph_text"][0]["text"] == "광량"


def test_sequence_state_report_uses_legacy_safe_telemetry_defaults(
    valid_qa_fixture: QaFixture,
):
    report = SequenceStateReport.model_validate(valid_qa_fixture.state_payload())

    assert report.browser_version == "unknown"
    assert report.capture_timing_mode == "legacy_combined"


def test_qa_rejects_an_unknown_capture_timing_mode(
    valid_qa_fixture: QaFixture,
):
    payload = valid_qa_fixture.state_payload()
    payload["capture_timing_mode"] = "opaque-timing"
    valid_qa_fixture.write_state_payload(payload)

    report = run_sequence_qa(**valid_qa_fixture.arguments())

    assert "invalid_state_report" in report.issue_codes


def test_fresh_one_frame_renderer_report_passes_sequence_qa(
    valid_qa_fixture: QaFixture,
):
    """Fresh renderer telemetry must survive normalization and strict sequence QA."""
    backend = LocalSequenceRenderBackend()
    backend.check_dependencies()
    cache_dir = valid_qa_fixture.run_dir / ".render-cache/fresh-one-frame"
    source_report = backend.render_frames(
        {
            "job_kind": "sequence",
            "sequence_id": "SEQ01",
            "scene_graph": "shared-science-scene",
            "canonical_fps": 10,
            "duration_frames": 1,
            "frame_count": 1,
            "output_directory": str(cache_dir),
            "output": {"width": 160, "height": 90, "fps": 10},
            "timeline": [],
            "canonical_state_cache": [
                {
                    "canonical_frame": 0,
                    "active_beat_ids": [],
                    "simulation_time": 0.0,
                }
            ],
            "sample_frames": [0],
            "style": {"seed": 220826, "earth_scale": 0.075, "mars_scale": 0.055},
        },
        cache_dir,
    )
    _normalize_frame_report(
        source_report,
        valid_qa_fixture.state_report_path,
        artifact_root=valid_qa_fixture.run_dir,
        sequence_id="SEQ01",
        frame_count=1,
        width=160,
        height=90,
    )

    production_sequence = valid_qa_fixture.production.visual_sequences[0].model_copy(
        update={"scene_ids": [1], "visual_beat_ids": ["B01"]}
    )
    production_beat = valid_qa_fixture.production.visual_beats[0].model_copy(
        update={"end_frame": 1}
    )
    valid_qa_fixture.production = valid_qa_fixture.production.model_copy(
        update={
            "visual_sequences": [production_sequence],
            "visual_beats": [production_beat],
        }
    )
    production_path = valid_qa_fixture.run_dir / "production-plan.json"
    production_path.write_text(
        valid_qa_fixture.production.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    production_hash = script_sha256(production_path)

    sequence = valid_qa_fixture.local.sequences[0]
    sequence = sequence.model_copy(
        update={
            "scene_ids": [1],
            "duration_frames": 1,
            "scene_spans": [
                sequence.scene_spans[0].model_copy(
                    update={"end_frame": 1, "audio_end_frame": 1}
                )
            ],
            "timeline": [
                sequence.timeline[0].model_copy(
                    update={"end_frame": 1, "simulation_time_end": 0.1}
                )
            ],
        }
    )
    valid_qa_fixture.local = valid_qa_fixture.local.model_copy(
        update={"production_plan_sha256": production_hash, "sequences": [sequence]}
    )
    local_path = valid_qa_fixture.run_dir / "local-sequence-plan.json"
    local_path.write_text(
        valid_qa_fixture.local.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    local_hash = script_sha256(local_path)

    rendered = valid_qa_fixture.render_report.sequences[0].model_copy(
        update={"frame_count": 1}
    )
    valid_qa_fixture.render_report = valid_qa_fixture.render_report.model_copy(
        update={
            "production_plan_sha256": production_hash,
            "local_sequence_plan_sha256": local_hash,
            "sequences": [rendered],
        }
    )
    duration = 0.1
    silent = MediaInfo("h264", None, 160, 90, 10.0, duration, 1, "yuv420p")
    narrated = MediaInfo(
        "h264",
        "aac",
        160,
        90,
        10.0,
        duration,
        1,
        "yuv420p",
        audio_duration_seconds=duration,
        audio_end_seconds=duration,
    )
    valid_qa_fixture.media_infos = {
        valid_qa_fixture.run_dir / rendered.master_file: silent,
        valid_qa_fixture.run_dir / rendered.narrated_file: narrated,
        valid_qa_fixture.run_dir / valid_qa_fixture.render_report.final_original_file: silent,
        valid_qa_fixture.run_dir / valid_qa_fixture.render_report.final_file: narrated,
    }

    payload = valid_qa_fixture.state_payload()
    report = run_sequence_qa(**valid_qa_fixture.arguments())

    assert payload["browser_version"] != "unknown"
    assert payload["capture_timing_mode"] == "split"
    assert report.status == "passed"


def test_qa_reads_reused_sequence_artifacts_from_their_source_root(
    valid_qa_fixture: QaFixture,
    tmp_path: Path,
):
    """Resolving reused artifacts from the workspace would hide a missing copy regression."""
    workspace = valid_qa_fixture.run_dir.resolve()
    source_root = tmp_path / "base"
    result = valid_qa_fixture.render_report.sequences[0]
    state_report = valid_qa_fixture.state_payload()
    relatives = [
        result.master_file,
        result.narrated_file,
        result.state_report_file,
        *state_report["frames"],
    ]
    for relative in relatives:
        source = workspace / relative
        destination = source_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        if source in valid_qa_fixture.media_infos:
            valid_qa_fixture.media_infos[destination.resolve()] = (
                valid_qa_fixture.media_infos[source]
            )
        source.unlink()

    report = run_sequence_qa(
        **valid_qa_fixture.arguments(),
        sequence_sources={
            "SEQ01": SequenceArtifactSource(
                result=result,
                root=source_root,
                reused=True,
            )
        },
    )

    assert report.status == "passed"
    assert (workspace / report.sequence_results[0].preview_files[0]).is_file()
    assert not (source_root / "videoFiles/previews").exists()


def test_qa_rejects_a_missing_sequence_artifact_source(
    valid_qa_fixture: QaFixture,
):
    """A partial source map must not silently fall back to the workspace."""
    with pytest.raises(ValueError, match="missing sources"):
        run_sequence_qa(
            **valid_qa_fixture.arguments(),
            sequence_sources={},
        )


def test_qa_rejects_a_duplicate_rendered_sequence_source(
    valid_qa_fixture: QaFixture,
):
    """Duplicate IDs make source-root ownership ambiguous and must be rejected."""
    result = valid_qa_fixture.render_report.sequences[0]
    valid_qa_fixture.render_report = valid_qa_fixture.render_report.model_copy(
        update={"sequences": [result, result]}
    )
    with pytest.raises(ValueError, match="repeats sequence SEQ01"):
        run_sequence_qa(
            **valid_qa_fixture.arguments(),
            sequence_sources={
                "SEQ01": SequenceArtifactSource(
                    result=result,
                    root=valid_qa_fixture.run_dir,
                    reused=True,
                )
            },
        )


def test_qa_rejects_a_sequence_source_path_that_escapes_its_root(
    valid_qa_fixture: QaFixture,
):
    """Source-root reuse must retain the artifact-relative path boundary."""
    result = valid_qa_fixture.render_report.sequences[0].model_copy(
        update={"master_file": "../outside.mp4"}
    )
    valid_qa_fixture.render_report = valid_qa_fixture.render_report.model_copy(
        update={"sequences": [result]}
    )
    with pytest.raises(ValueError, match="relative descendant"):
        run_sequence_qa(
            **valid_qa_fixture.arguments(),
            sequence_sources={
                "SEQ01": SequenceArtifactSource(
                    result=result,
                    root=valid_qa_fixture.run_dir,
                    reused=True,
                )
            },
        )


def test_configured_freeze_threshold_controls_rejection(valid_qa_fixture: QaFixture):
    payload = valid_qa_fixture.state_payload()
    for sample in payload["state_samples"][0:21]:
        sample["state_fingerprint"] = "fnv1a32:deadbeef"
    valid_qa_fixture.write_state_payload(payload)

    report = run_sequence_qa(
        **valid_qa_fixture.arguments(),
        settings=HarnessSettings(qa={"max_undeclared_freeze_seconds": 3.0}),
    )

    assert "undeclared_freeze" not in report.issue_codes


def test_black_frame_command_uses_configured_detector(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    captured: list[str] = []

    def fake_run(command: list[str], **_kwargs) -> SimpleNamespace:
        captured.extend(command)
        return SimpleNamespace(stderr="")

    monkeypatch.setattr("video_harness.sequence_qa.subprocess.run", fake_run)

    assert detect_black_frames(
        tmp_path / "source.mp4", amount_percent=98.5, threshold=22
    ) == []
    assert "blackframe=amount=98.5:threshold=22" in captured


def test_preview_manifest_uses_configured_interval(valid_qa_fixture: QaFixture):
    settings = ArchivedV5HarnessSettings(
        render={"preview_interval_seconds": 1.0, "contact_sheet_columns": 3}
    )

    report = run_sequence_qa(**valid_qa_fixture.arguments(), settings=settings)

    assert report.sequence_results[0].preview_files == [
        "videoFiles/previews/half-second/SEQ01/000000ms.png",
        "videoFiles/previews/half-second/SEQ01/001000ms.png",
        "videoFiles/previews/half-second/SEQ01/002000ms.png",
        "videoFiles/previews/half-second/SEQ01/003000ms.png",
        "videoFiles/previews/half-second/SEQ01/004000ms.png",
        "videoFiles/previews/half-second/SEQ01/005000ms.png",
        "videoFiles/previews/half-second/SEQ01/006000ms.png",
    ]
    assert report.settings_sha256 == settings_sha256(settings)
    assert report.preview_interval_seconds == 1.0
    assert report.contact_sheet_columns == 3


def test_preview_manifest_uses_canonical_duration_when_draft_rounds_up(
    valid_qa_fixture: QaFixture,
):
    sequence = valid_qa_fixture.render_report.sequences[0].model_copy(
        update={"frame_count": 33, "fps": 5}
    )
    valid_qa_fixture.render_report = valid_qa_fixture.render_report.model_copy(
        update={"sequences": [sequence]}
    )

    report = run_sequence_qa(**valid_qa_fixture.arguments())

    assert report.sequence_results[0].preview_files[-1] == (
        "videoFiles/previews/half-second/SEQ01/006000ms.png"
    )
    assert (
        "videoFiles/previews/half-second/SEQ01/006500ms.png"
        not in report.sequence_results[0].preview_files
    )


def test_qa_rejects_duplicate_sequence_and_forged_whole_frame_count(
    valid_qa_fixture: QaFixture,
):
    sequence = valid_qa_fixture.render_report.sequences[0]
    valid_qa_fixture.render_report = valid_qa_fixture.render_report.model_copy(
        update={"sequences": [sequence, sequence]}
    )
    for filename, audio_codec in (("video-only.mp4", None), ("final.mp4", "aac")):
        path = valid_qa_fixture.run_dir / filename
        valid_qa_fixture.media_infos[path] = MediaInfo(
            "h264",
            audio_codec,
            160,
            90,
            10.0,
            13.0,
            130,
            "yuv420p",
            audio_duration_seconds=13.0 if audio_codec else None,
            audio_end_seconds=13.0 if audio_codec else None,
        )

    report = run_sequence_qa(**valid_qa_fixture.arguments())

    assert "duplicate_rendered_sequence" in report.issue_codes
    assert "rendered_sequence_order_mismatch" in report.issue_codes
    assert "final_media_frame_count_mismatch" in report.issue_codes


def _add_second_sequence(fixture: QaFixture) -> None:
    first_production = fixture.production.visual_sequences[0]
    fixture.production = fixture.production.model_copy(
        update={
            "visual_sequences": [
                first_production,
                first_production.model_copy(update={"sequence_id": "SEQ02"}),
            ]
        }
    )
    production_path = fixture.run_dir / "production-plan.json"
    production_path.write_text(
        fixture.production.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    production_hash = script_sha256(production_path)
    first_local = fixture.local.sequences[0]
    fixture.local = fixture.local.model_copy(
        update={
            "production_plan_sha256": production_hash,
            "sequences": [
                first_local,
                first_local.model_copy(update={"sequence_id": "SEQ02"}),
            ],
        }
    )
    local_path = fixture.run_dir / "local-sequence-plan.json"
    local_path.write_text(fixture.local.model_dump_json(indent=2) + "\n", encoding="utf-8")
    local_hash = script_sha256(local_path)
    fixture.online = fixture.online.model_copy(
        update={"production_plan_sha256": production_hash}
    )

    first_result = fixture.render_report.sequences[0]
    second_result = first_result.model_copy(
        update={
            "sequence_id": "SEQ02",
            "master_file": "videoFiles/sequences/final/SEQ02.mp4",
            "narrated_file": "videoFiles/sequences/final/SEQ02-narrated.mp4",
            "state_report_file": "videoFiles/sequences/final/SEQ02-frame-report.json",
            "state_cache_file": "videoFiles/sequences/state-cache/SEQ02.json",
        }
    )
    fixture.render_report = fixture.render_report.model_copy(
        update={
            "production_plan_sha256": production_hash,
            "local_sequence_plan_sha256": local_hash,
            "sequences": [first_result, second_result],
        }
    )
    second_state_path = fixture.run_dir / second_result.state_report_file
    second_frames: list[str] = []
    for frame in range(65):
        relative = f".render-cache/SEQ02/frame-{frame:06d}.png"
        frame_path = fixture.run_dir / relative
        frame_path.parent.mkdir(parents=True, exist_ok=True)
        frame_path.write_bytes(b"png")
        second_frames.append(relative)
    _write_json(
        second_state_path,
        {
            "sequence_id": "SEQ02",
            "frame_count": 65,
            "width": 160,
            "height": 90,
            "frames": second_frames,
            "state_samples": [_state_sample(frame) for frame in range(65)],
        },
    )
    silent = MediaInfo("h264", None, 160, 90, 10.0, 6.5, 65, "yuv420p")
    narrated = MediaInfo(
        "h264",
        "aac",
        160,
        90,
        10.0,
        6.5,
        65,
        "yuv420p",
        audio_duration_seconds=6.5,
        audio_end_seconds=6.5,
    )
    for relative, info in (
        (second_result.master_file, silent),
        (second_result.narrated_file, narrated),
    ):
        path = fixture.run_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake-media")
        fixture.media_infos[path] = info
    fixture.media_infos[fixture.run_dir / "video-only.mp4"] = MediaInfo(
        "h264", None, 160, 90, 10.0, 13.0, 130, "yuv420p"
    )
    fixture.media_infos[fixture.run_dir / "final.mp4"] = MediaInfo(
        "h264",
        "aac",
        160,
        90,
        10.0,
        13.0,
        130,
        "yuv420p",
        audio_duration_seconds=13.0,
        audio_end_seconds=13.0,
    )


def test_qa_rejects_reordered_sequence_report(valid_qa_fixture: QaFixture):
    _add_second_sequence(valid_qa_fixture)
    first, second = valid_qa_fixture.render_report.sequences
    valid_qa_fixture.render_report = valid_qa_fixture.render_report.model_copy(
        update={"sequences": [second, first]}
    )

    report = run_sequence_qa(**valid_qa_fixture.arguments())

    assert "rendered_sequence_order_mismatch" in report.issue_codes


def test_qa_rejects_missing_reported_frame_identity(valid_qa_fixture: QaFixture):
    payload = valid_qa_fixture.state_payload()
    payload["frames"].pop()
    valid_qa_fixture.write_state_payload(payload)

    report = run_sequence_qa(**valid_qa_fixture.arguments())

    assert "missing_reported_frame" in report.issue_codes


def test_qa_rejects_duplicate_reported_frame_identity(valid_qa_fixture: QaFixture):
    payload = valid_qa_fixture.state_payload()
    payload["frames"][1] = payload["frames"][0]
    valid_qa_fixture.write_state_payload(payload)

    report = run_sequence_qa(**valid_qa_fixture.arguments())

    assert "duplicate_reported_frame" in report.issue_codes
    assert "missing_reported_frame" in report.issue_codes


def test_qa_rejects_swapped_reported_frame_order(valid_qa_fixture: QaFixture):
    payload = valid_qa_fixture.state_payload()
    payload["frames"][1], payload["frames"][2] = payload["frames"][2], payload["frames"][1]
    valid_qa_fixture.write_state_payload(payload)

    report = run_sequence_qa(**valid_qa_fixture.arguments())

    assert "misordered_reported_frame" in report.issue_codes


def test_qa_rejects_traversing_reported_frame_path(valid_qa_fixture: QaFixture):
    payload = valid_qa_fixture.state_payload()
    payload["frames"][0] = "../frame-000000.png"
    valid_qa_fixture.write_state_payload(payload)

    report = run_sequence_qa(**valid_qa_fixture.arguments())

    assert "unsafe_reported_frame_path" in report.issue_codes


def test_qa_rejects_symlink_escape_reported_frame_path(
    valid_qa_fixture: QaFixture,
    tmp_path: Path,
):
    outside = tmp_path / "outside-frame.png"
    outside.write_bytes(b"png")
    frame = valid_qa_fixture.run_dir / ".render-cache/frame-000000.png"
    frame.unlink()
    frame.symlink_to(outside)

    report = run_sequence_qa(**valid_qa_fixture.arguments())

    assert "unsafe_reported_frame_path" in report.issue_codes


def test_qa_rejects_empty_reported_frame_file(valid_qa_fixture: QaFixture):
    (valid_qa_fixture.run_dir / ".render-cache/frame-000003.png").write_bytes(b"")

    report = run_sequence_qa(**valid_qa_fixture.arguments())

    assert "empty_reported_frame" in report.issue_codes


def test_qa_rejects_layer_reset_at_internal_scene_boundary(valid_qa_fixture: QaFixture):
    payload = valid_qa_fixture.state_payload()
    payload["state_samples"][30]["visible_layers"].remove("sightlineHistory")
    valid_qa_fixture.write_state_payload(payload)

    report = run_sequence_qa(**valid_qa_fixture.arguments())

    assert report.status == "failed"
    assert "unexpected_layer_reset" in report.issue_codes


def test_qa_allows_layer_removal_declared_by_hide_event(valid_qa_fixture: QaFixture):
    sequence = valid_qa_fixture.local.sequences[0]
    second = sequence.timeline[1].model_copy(
        update={"patch_targets": ["geometry", "camera", "hide_events"]}
    )
    valid_qa_fixture.local = valid_qa_fixture.local.model_copy(
        update={"sequences": [sequence.model_copy(update={"timeline": [sequence.timeline[0], second]})]}
    )
    payload = valid_qa_fixture.state_payload()
    for sample in payload["state_samples"][30:]:
        sample["visible_layers"].remove("sightlineHistory")
    valid_qa_fixture.write_state_payload(payload)

    report = run_sequence_qa(**valid_qa_fixture.arguments())

    assert "unexpected_layer_reset" not in report.issue_codes
    assert "undeclared_layer_hide" not in report.issue_codes


def test_qa_rejects_undeclared_two_second_freeze(valid_qa_fixture: QaFixture):
    payload = valid_qa_fixture.state_payload()
    for sample in payload["state_samples"][0:21]:
        sample["state_fingerprint"] = "fnv1a32:deadbeef"
    valid_qa_fixture.write_state_payload(payload)

    report = run_sequence_qa(**valid_qa_fixture.arguments())

    assert "undeclared_freeze" in report.issue_codes
    assert report.sequence_results[0].undeclared_freeze_ranges == [(0, 21)]


def test_qa_allows_fingerprint_hold_covered_by_hold_intent(valid_qa_fixture: QaFixture):
    sequence = valid_qa_fixture.local.sequences[0]
    held = sequence.timeline[0].model_copy(
        update={
            "simulation_time_end": 0.0,
            "hold_intent": "pause on the completed evidence",
        }
    )
    valid_qa_fixture.local = valid_qa_fixture.local.model_copy(
        update={"sequences": [sequence.model_copy(update={"timeline": [held, sequence.timeline[1]]})]}
    )
    payload = valid_qa_fixture.state_payload()
    for sample in payload["state_samples"][0:25]:
        sample["state_fingerprint"] = "fnv1a32:deadbeef"
        sample["simulation_time"] = 0.0
    valid_qa_fixture.write_state_payload(payload)

    report = run_sequence_qa(**valid_qa_fixture.arguments())

    assert report.status == "passed"


def test_qa_rejects_simulation_time_reversal(valid_qa_fixture: QaFixture):
    payload = valid_qa_fixture.state_payload()
    payload["state_samples"][31]["simulation_time"] = 1.0
    valid_qa_fixture.write_state_payload(payload)

    report = run_sequence_qa(**valid_qa_fixture.arguments())

    assert "simulation_time_reversal" in report.issue_codes


def test_qa_rejects_nonfinite_simulation_time(valid_qa_fixture: QaFixture):
    payload = valid_qa_fixture.state_payload()
    payload["state_samples"][31]["simulation_time"] = float("nan")
    valid_qa_fixture.write_state_payload(payload)

    report = run_sequence_qa(**valid_qa_fixture.arguments())

    assert "invalid_simulation_time" in report.issue_codes


def test_qa_rejects_black_frame_at_internal_boundary(
    valid_qa_fixture: QaFixture,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "video_harness.sequence_qa.detect_black_frames", lambda _path, **_kwargs: [30]
    )

    report = run_sequence_qa(**valid_qa_fixture.arguments())

    assert "black_frame" in report.issue_codes
    assert report.sequence_results[0].black_frames == [30]


def test_concat_boundary_qa_allows_one_equal_join_frame_but_rejects_a_repeat(
    valid_qa_fixture: QaFixture,
    monkeypatch: pytest.MonkeyPatch,
):
    """A boundary frame may equal its predecessor; carrying it into the next frame may not."""
    source = valid_qa_fixture.run_dir / "video-only.mp4"
    sequence = valid_qa_fixture.local.sequences[0]
    media = MediaInfo("h264", None, 160, 90, 10.0, 8.0, 80, "yuv420p")

    monkeypatch.setattr(
        "video_harness.sequence_qa.decode_frame_hashes",
        lambda _source, frames: {
            frame: DecodedFrame(frame, frame / 10, "same" if frame < 66 else "next")
            for frame in frames
        },
    )
    single_join = validate_concat_boundaries(
        source,
        [sequence, sequence],
        [65, 15],
        media,
    )

    assert single_join == []

    monkeypatch.setattr(
        "video_harness.sequence_qa.decode_frame_hashes",
        lambda _source, frames: {
            frame: DecodedFrame(frame, frame / 10, "same") for frame in frames
        },
    )
    repeated = validate_concat_boundaries(
        source,
        [sequence, sequence],
        [65, 15],
        media,
    )

    assert [issue.code for issue in repeated] == ["undeclared_concat_boundary_freeze"]


@pytest.mark.parametrize('recovers', [True, False])
def test_declared_light_match_checks_motion_after_reveal(valid_qa_fixture, monkeypatch, recovers):
    sequence = valid_qa_fixture.local.sequences[0]
    outgoing = sequence.model_copy(deep=True)
    incoming = sequence.model_copy(deep=True)
    outgoing.scene_graph = incoming.scene_graph = 'optical-depth-story-blender-v2'
    outgoing.timeline[-1].controller_options['light_transition'] = 'solar_to_lamp'
    incoming.timeline[0].controller_options['light_transition'] = 'lamp_reveal'
    monkeypatch.setattr(
        'video_harness.sequence_qa.decode_frame_hashes',
        lambda _source, frames: {
            frame: DecodedFrame(frame, frame / 30, str(frame) if recovers and frame >= 74 else 'white')
            for frame in frames
        },
    )
    issues = validate_concat_boundaries(
        valid_qa_fixture.run_dir / 'video-only.mp4', [outgoing, incoming], [65, 45],
        MediaInfo('h264', None, 160, 90, 30.0, 110 / 30, 110, 'yuv420p'),
    )
    assert [issue.code for issue in issues] == ([] if recovers else ['undeclared_concat_boundary_freeze'])


@pytest.mark.parametrize('fps', [9, 30, 60])
@pytest.mark.parametrize('recovers', [True, False])
def test_planned_entry_transition_checks_recovery(valid_qa_fixture, monkeypatch, fps, recovers):
    sequence = valid_qa_fixture.local.sequences[0]
    incoming = sequence.model_copy(deep=True)
    incoming.timeline[0].controller_options['entry_transition'] = {
        'style': 'fade', 'duration_seconds': 0.4,
    }
    boundary = fps * 2
    monkeypatch.setattr(
        'video_harness.sequence_qa.decode_frame_hashes',
        lambda _source, frames: {
            frame: DecodedFrame(frame, frame / fps,
                                str(frame) if recovers and frame >= boundary + 0.4 * fps else 'same')
            for frame in frames
        },
    )
    issues = validate_concat_boundaries(
        valid_qa_fixture.run_dir / 'video-only.mp4', [sequence, incoming], [boundary, boundary],
        MediaInfo('h264', None, 160, 90, fps, 4.0, boundary * 2, 'yuv420p'),
    )
    assert [issue.code for issue in issues] == ([] if recovers else ['undeclared_concat_boundary_freeze'])


@pytest.mark.parametrize('transition', [
    {'style': 'unknown', 'duration_seconds': 0.4},
    {'style': 'fade', 'duration_seconds': 99},
    {'style': 'fade', 'duration_seconds': float('nan')},
    {'style': 'fade', 'duration_seconds': 'bad'},
])
def test_invalid_transition_cannot_exempt_repeated_boundary(valid_qa_fixture, monkeypatch, transition):
    sequence = valid_qa_fixture.local.sequences[0]
    incoming = sequence.model_copy(deep=True)
    incoming.timeline[0].controller_options['entry_transition'] = transition
    monkeypatch.setattr('video_harness.sequence_qa.decode_frame_hashes', lambda _source, frames: {
        frame: DecodedFrame(frame, frame / 30, 'same' if frame < 65 else str(frame))
        for frame in frames
    })
    issues = validate_concat_boundaries(
        valid_qa_fixture.run_dir / 'video-only.mp4', [sequence, incoming], [60, 60],
        MediaInfo('h264', None, 160, 90, 30, 4.0, 120, 'yuv420p'),
    )
    assert [issue.code for issue in issues] == ['undeclared_concat_boundary_freeze']


def test_decode_frame_hashes_reports_requested_frame_timestamps(tmp_path: Path):
    source = tmp_path / "source.mp4"
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
            "testsrc2=size=16x16:rate=10:duration=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ],
        check=True,
    )

    decoded = decode_frame_hashes(source, [0, 4, 9])

    assert [sample.frame for sample in decoded.values()] == [0, 4, 9]
    assert [sample.timestamp_seconds for sample in decoded.values()] == [0.0, 0.4, 0.9]
    assert all(len(sample.digest) == 64 for sample in decoded.values())


def test_decode_frame_hashes_explicitly_maps_video_from_aac_mp4(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    source = tmp_path / "with-aac.mp4"
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
            "testsrc2=size=16x16:rate=10:duration=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=24000:duration=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(source),
        ],
        check=True,
    )
    commands: list[list[str]] = []
    real_run = subprocess.run

    def spy_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return real_run(command, **kwargs)

    monkeypatch.setattr("video_harness.sequence_qa.subprocess.run", spy_run)

    decoded = decode_frame_hashes(source, [0, 9])

    assert list(decoded) == [0, 9]
    assert commands[-1][commands[-1].index("-map") + 1] == "0:v:0"


def test_concat_boundary_qa_allows_repetition_at_an_incoming_declared_hold(
    valid_qa_fixture: QaFixture,
    monkeypatch: pytest.MonkeyPatch,
):
    sequence = valid_qa_fixture.local.sequences[0]
    held = sequence.model_copy(
        update={
            "timeline": [
                sequence.timeline[0].model_copy(
                    update={"hold_intent": "pause at the incoming join"}
                ),
                sequence.timeline[1],
            ]
        }
    )
    monkeypatch.setattr(
        "video_harness.sequence_qa.decode_frame_hashes",
        lambda _source, frames: {
            frame: DecodedFrame(frame, frame / 10, "same") for frame in frames
        },
    )

    issues = validate_concat_boundaries(
        valid_qa_fixture.run_dir / "video-only.mp4",
        [sequence, held],
        [65, 15],
        MediaInfo("h264", None, 160, 90, 10.0, 8.0, 80, "yuv420p"),
    )

    assert issues == []


def test_qa_reports_undeclared_final_concat_boundary_freezes_to_performance(
    valid_qa_fixture: QaFixture,
    monkeypatch: pytest.MonkeyPatch,
):
    _add_second_sequence(valid_qa_fixture)
    monkeypatch.setattr(
        "video_harness.sequence_qa.decode_frame_hashes",
        lambda _source, frames: {
            frame: DecodedFrame(frame, frame / 10, "same") for frame in frames
        },
    )
    recorder = PerformanceRecorder()

    report = run_sequence_qa(
        **valid_qa_fixture.arguments(), performance=recorder
    )

    assert "undeclared_concat_boundary_freeze" in report.issue_codes
    assert any(event.name == "boundary_qa" for event in recorder.report().phase_events)


def test_qa_does_not_treat_dark_changing_state_as_a_freeze(valid_qa_fixture: QaFixture):
    report = run_sequence_qa(**valid_qa_fixture.arguments())

    assert report.status == "passed"
    assert report.sequence_results[0].black_frames == []
    assert report.sequence_results[0].undeclared_freeze_ranges == []


def test_qa_reports_ffmpeg_decode_work_separately_from_the_enclosing_phase(
    valid_qa_fixture: QaFixture,
):
    """Removing decode subphases must not fold all FFmpeg cost back into QA."""
    recorder = PerformanceRecorder()

    run_sequence_qa(**valid_qa_fixture.arguments(), performance=recorder)

    performance = recorder.report()
    assert any(event.name == "qa" for event in performance.phase_events)
    assert {
        event.labels["operation"]
        for event in performance.phase_events
        if event.name == "ffmpeg_decode"
    } == {"black_frame_scan", "preview_extract", "contact_sheet"}


def test_qa_rejects_silent_and_narrated_timeline_mismatch(valid_qa_fixture: QaFixture):
    narrated = valid_qa_fixture.run_dir / "videoFiles/sequences/final/SEQ01-narrated.mp4"
    valid_qa_fixture.media_infos[narrated] = MediaInfo(
        "h264",
        "aac",
        160,
        90,
        10.0,
        6.4,
        64,
        "yuv420p",
        audio_duration_seconds=6.4,
        audio_end_seconds=6.4,
    )

    report = run_sequence_qa(**valid_qa_fixture.arguments())

    assert "media_frame_count_mismatch" in report.issue_codes
    assert "audio_video_timeline_mismatch" in report.issue_codes


def test_qa_rejects_sequence_aac_stream_ending_early(valid_qa_fixture: QaFixture):
    narrated = valid_qa_fixture.run_dir / "videoFiles/sequences/final/SEQ01-narrated.mp4"
    valid_qa_fixture.media_infos[narrated] = MediaInfo(
        "h264",
        "aac",
        160,
        90,
        10.0,
        6.5,
        65,
        "yuv420p",
        audio_duration_seconds=0.5,
        audio_end_seconds=0.5,
    )

    report = run_sequence_qa(**valid_qa_fixture.arguments())

    assert "audio_stream_ends_early" in report.issue_codes


def test_qa_rejects_whole_aac_stream_ending_early(valid_qa_fixture: QaFixture):
    final = valid_qa_fixture.run_dir / "final.mp4"
    valid_qa_fixture.media_infos[final] = MediaInfo(
        "h264",
        "aac",
        160,
        90,
        10.0,
        6.5,
        65,
        "yuv420p",
        audio_duration_seconds=0.5,
        audio_end_seconds=0.5,
    )

    report = run_sequence_qa(**valid_qa_fixture.arguments())

    assert "final_audio_stream_ends_early" in report.issue_codes


def test_qa_rejects_wrong_whole_video_dimensions_and_fps(valid_qa_fixture: QaFixture):
    for filename, audio_codec in (("video-only.mp4", None), ("final.mp4", "aac")):
        path = valid_qa_fixture.run_dir / filename
        valid_qa_fixture.media_infos[path] = MediaInfo(
            "h264",
            audio_codec,
            320,
            180,
            12.0,
            65 / 12,
            65,
            "yuv420p",
            audio_duration_seconds=65 / 12 if audio_codec else None,
            audio_end_seconds=65 / 12 if audio_codec else None,
        )

    report = run_sequence_qa(**valid_qa_fixture.arguments())

    assert "final_media_dimension_mismatch" in report.issue_codes
    assert "final_media_fps_mismatch" in report.issue_codes


def test_qa_requires_final_v2v_references(valid_qa_fixture: QaFixture):
    (valid_qa_fixture.run_dir / "videoFiles/onlineReferences/ON-B01.mp4").unlink()

    report = run_sequence_qa(**valid_qa_fixture.arguments())

    assert "missing_v2v_reference" in report.issue_codes


def test_video_only_final_qa_does_not_require_v2v_references(
    valid_qa_fixture: QaFixture,
):
    (valid_qa_fixture.run_dir / "videoFiles/onlineReferences/ON-B01.mp4").unlink()
    settings = HarnessSettings(pipeline={"output_mode": "video_only"})

    report = run_sequence_qa(
        **valid_qa_fixture.arguments(),
        settings=settings,
    )

    assert report.status == "passed"
    assert "missing_v2v_reference" not in report.issue_codes


def test_create_contact_sheet_runs_real_ffmpeg(tmp_path: Path):
    source = tmp_path / "source.mp4"
    destination = tmp_path / "contact-sheet.png"
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
            "testsrc2=size=160x90:rate=10:duration=1.1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ],
        check=True,
    )

    result = create_contact_sheet(source, destination, interval_seconds=0.5, columns=2)

    assert result == destination
    assert destination.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_probe_media_reports_aac_stream_duration_and_end(tmp_path: Path):
    source = tmp_path / "early-audio.mp4"
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
            "color=c=white:size=160x90:rate=10:duration=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=24000:duration=0.2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(source),
        ],
        check=True,
    )

    info = probe_media(source, require_audio=True)

    assert info.duration_seconds == pytest.approx(1.0, abs=0.02)
    assert info.audio_duration_seconds == pytest.approx(0.2, abs=0.05)
    assert info.audio_end_seconds == pytest.approx(0.2, abs=0.05)


def test_media_validator_rejects_real_full_video_with_early_aac(
    valid_qa_fixture: QaFixture,
    tmp_path: Path,
):
    source = tmp_path / "early-audio.mp4"
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
            "color=c=white:size=160x90:rate=10:duration=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=24000:duration=0.2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(source),
        ],
        check=True,
    )
    sequence = valid_qa_fixture.local.sequences[0].model_copy(
        update={"duration_frames": 10}
    )
    rendered = valid_qa_fixture.render_report.sequences[0].model_copy(
        update={"frame_count": 10}
    )
    silent = MediaInfo("h264", None, 160, 90, 10.0, 1.0, 10, "yuv420p")

    issues = validate_media_contract(
        sequence,
        rendered,
        silent,
        probe_media(source, require_audio=True),
        local=valid_qa_fixture.local,
        quality="final",
    )

    assert "audio_stream_ends_early" in {issue.code for issue in issues}


def test_media_validator_accepts_muxed_declared_audio_tail(
    valid_qa_fixture: QaFixture,
    tmp_path: Path,
):
    silent_path = tmp_path / "silent.mp4"
    audio_path = tmp_path / "audio.mp3"
    narrated_path = tmp_path / "narrated.mp4"
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
            "color=c=white:size=160x90:rate=10:duration=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(silent_path),
        ],
        check=True,
    )
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
            "sine=frequency=440:sample_rate=24000:duration=0.2",
            "-codec:a",
            "libmp3lame",
            str(audio_path),
        ],
        check=True,
    )
    spec = OutputSpec(width=160, height=90, fps=10, duration_seconds=1.0, frames=10)
    mux_audio_timeline(
        silent_path,
        [AudioPlacement(audio_path, start_frame=0, end_frame=2)],
        narrated_path,
        spec,
    )
    sequence = valid_qa_fixture.local.sequences[0].model_copy(
        update={"duration_frames": 10}
    )
    rendered = valid_qa_fixture.render_report.sequences[0].model_copy(
        update={"frame_count": 10}
    )

    issues = validate_media_contract(
        sequence,
        rendered,
        probe_media(silent_path),
        probe_media(narrated_path, require_audio=True),
        local=valid_qa_fixture.local,
        quality="final",
    )

    assert "audio_stream_ends_early" not in {issue.code for issue in issues}


@pytest.fixture(autouse=True)
def isolate_editorial_gate_dependency(monkeypatch):
    """These subsystem tests use synthetic plans; real gate entrypoints are covered
    without mocks in test_creative_gates.py. Keep this dependency module-scoped.
    """
    monkeypatch.setattr("video_harness.creative_gates.render_report_continuity_issues", lambda *args, **kwargs: [])
