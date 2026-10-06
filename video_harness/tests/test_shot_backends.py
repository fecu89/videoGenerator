from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest

from video_harness.media import MediaInfo, probe_media
from video_harness.production import script_sha256
from video_harness.production_models import ProductionPlan
from video_harness.shot_backends import (
    CompositeBackend,
    GeneratedClipBackend,
    MediaRecord,
    ShotBackendRegistry,
    ShotContext,
    ShotRenderRecord,
    ShotReviewRecord,
    SimulationBackend,
    StillMotionBackend,
)
from video_harness.migration import build_simulation_plan
from video_harness.simulation import SimulationConfig
from video_harness.tests.test_production_models import make_plan_payload, make_script
from video_harness.tests.test_simulation import make_script as make_simulation_script
from video_harness.tests.test_simulation import simulation_payload


def make_context(tmp_path: Path) -> tuple[ShotContext, object]:
    script = make_script()
    script_path = tmp_path / "script.json"
    script_path.write_text(script.model_dump_json() + "\n", encoding="utf-8")
    plan = ProductionPlan.model_validate(make_plan_payload(script_sha256(script_path)))
    start = tmp_path / "shotAssets/starts/01A.png"
    start.parent.mkdir(parents=True)
    start.write_bytes(b"start")
    background = tmp_path / "shotAssets/backgrounds/01D.png"
    background.parent.mkdir(parents=True)
    background.write_bytes(b"background")
    context = ShotContext(
        run_dir=tmp_path,
        plan=plan,
        backend_versions={"generated": "generated-v1"},
        media_probe=lambda _: MediaInfo(
            "h264", None, 1920, 1080, 30.0, 2.0, 60, "yuv420p"
        ),
    )
    return context, plan.scenes[0].shots[0]


def test_shot_fingerprint_changes_when_asset_bytes_change(tmp_path: Path):
    context, shot = make_context(tmp_path)
    first = context.input_fingerprint(shot)
    context.asset_path("shotAssets/starts/01A.png").write_bytes(b"changed")
    assert context.input_fingerprint(shot) != first


def test_cached_output_is_reused_only_when_hash_and_media_match(tmp_path: Path):
    context, shot = make_context(tmp_path)
    output = context.output_path(shot)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"rendered")
    info = context.media_probe(output)
    record = ShotRenderRecord(
        shot_id=shot.shot_id,
        input_fingerprint=context.input_fingerprint(shot),
        output_file=output.relative_to(tmp_path).as_posix(),
        output_sha256=context.file_sha256(output),
        media=MediaRecord.from_media_info(info),
    )
    assert context.can_reuse(shot, record) is True

    bad = record.model_copy(
        update={"media": record.media.model_copy(update={"width": 1280})}
    )
    assert context.can_reuse(shot, bad) is False


def test_review_is_invalidated_when_shot_output_changes(tmp_path: Path):
    context, shot = make_context(tmp_path)
    output = context.output_path(shot)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"first")
    review = ShotReviewRecord(
        shot_id=shot.shot_id,
        output_sha256=context.file_sha256(output),
        status="approved",
        invariant_results={shot.invariants[0]: True},
        note="checked",
    )
    assert context.is_review_approved(shot, review) is True
    output.write_bytes(b"new output")
    assert context.is_review_approved(shot, review) is False


def test_registry_reports_unregistered_mode():
    registry = ShotBackendRegistry()
    with pytest.raises(ValueError, match="simulation"):
        registry.get("simulation")


def make_test_video(path: Path, duration: float = 1.0) -> None:
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
            f"testsrc2=size=160x90:rate=10:duration={duration}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={duration}",
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


def make_test_png(path: Path) -> None:
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
            "color=c=navy:size=160x90",
            "-frames:v",
            "1",
            str(path),
        ],
        check=True,
    )


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is required")
def test_generated_backend_normalizes_exact_frames_and_strips_audio(tmp_path: Path):
    context, shot = make_context(tmp_path)
    context.plan.defaults.width = 160
    context.plan.defaults.height = 90
    context.plan.defaults.fps = 10
    context.media_probe = probe_media
    shot.duration_seconds = 0.6
    shot.end_state.at_seconds = 0.6
    source = context.safe_path(shot.generation.inbox_file)
    source.parent.mkdir(parents=True, exist_ok=True)
    make_test_video(source)

    output = GeneratedClipBackend().render(shot, context)
    info = context.media_probe(output)

    assert info.frame_count == 6
    assert info.audio_codec is None
    review = ShotReviewRecord.model_validate_json(
        context.review_path(shot).read_text(encoding="utf-8")
    )
    assert review.status == "pending"
    assert context.is_review_approved(shot, review) is False


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is required")
def test_generated_backend_rejects_a_short_source(tmp_path: Path):
    context, shot = make_context(tmp_path)
    context.plan.defaults.width = 160
    context.plan.defaults.height = 90
    context.plan.defaults.fps = 10
    context.media_probe = probe_media
    shot.duration_seconds = 1.0
    shot.end_state.at_seconds = 1.0
    source = context.safe_path(shot.generation.inbox_file)
    source.parent.mkdir(parents=True, exist_ok=True)
    make_test_video(source, duration=0.4)

    with pytest.raises(ValueError, match="짧습니다"):
        GeneratedClipBackend().render(shot, context)


def test_generated_backend_reports_the_exact_missing_inbox_path(tmp_path: Path):
    context, shot = make_context(tmp_path)
    with pytest.raises(FileNotFoundError, match="01A_생성.mp4"):
        GeneratedClipBackend().render(shot, context)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is required")
def test_still_motion_renders_exact_frame_count(tmp_path: Path):
    context, _ = make_context(tmp_path)
    shot = context.plan.scenes[0].shots[3]
    context.plan.defaults.width = 160
    context.plan.defaults.height = 90
    context.plan.defaults.fps = 10
    context.media_probe = probe_media
    shot.duration_seconds = 0.6
    shot.end_state.at_seconds = 0.6
    shot.still_motion.camera_keyframes[-1].at_seconds = 0.6
    source = context.safe_path(shot.still_motion.source_image)
    make_test_png(source)

    output = StillMotionBackend().render(shot, context)
    info = context.media_probe(output)

    assert info.frame_count == 6
    assert info.audio_codec is None
    assert not context.review_path(shot).exists()


def test_simulation_adapter_compiles_manifest_values_without_changing_physics(
    tmp_path: Path,
):
    script = make_simulation_script()
    script_path = tmp_path / "script.json"
    script_path.write_text(script.model_dump_json() + "\n", encoding="utf-8")
    config = SimulationConfig.model_validate(simulation_payload())
    plan = build_simulation_plan(tmp_path, script, config)
    shot = plan.scenes[5].shots[0]
    context = ShotContext(
        run_dir=tmp_path,
        plan=plan,
        backend_versions={"simulation": SimulationBackend.version},
    )

    job = SimulationBackend().build_job(shot, context, tmp_path / "frames")

    assert job["template"] == "earth-overtake"
    assert job["duration_seconds"] == shot.duration_seconds
    assert job["output"] == {"width": 1920, "height": 1080, "fps": 30}
    assert job["physics"]["earth_period_days"] == 365.0
    assert job["physics"]["mars_period_days"] == 687.0
    assert job["simulation_day_start"] == -70.0
    assert job["simulation_day_end"] == 70.0
    assert job["camera"] == shot.camera.model_dump(mode="json", exclude_none=True)
    assert job["renderer_options"] == shot.simulation.renderer_options


def test_simulation_adapter_rejects_template_without_required_visual_feature(
    tmp_path: Path,
):
    script = make_simulation_script()
    script_path = tmp_path / "script.json"
    script_path.write_text(script.model_dump_json() + "\n", encoding="utf-8")
    config = SimulationConfig.model_validate(simulation_payload())
    plan = build_simulation_plan(tmp_path, script, config)
    shot = plan.scenes[5].shots[0]
    shot.simulation.renderer_options["required_features"] = [
        "two_stationary_markers"
    ]
    context = ShotContext(
        run_dir=tmp_path,
        plan=plan,
        backend_versions={"simulation": SimulationBackend.version},
    )

    with pytest.raises(ValueError, match="two_stationary_markers"):
        SimulationBackend().build_job(shot, context, tmp_path / "frames")


def test_simulation_adapter_compiles_eclipse_contract_without_mars_parameters(
    tmp_path: Path,
):
    script = make_script(duration=7.92)
    script_path = tmp_path / "script.json"
    script_path.write_text(script.model_dump_json() + "\n", encoding="utf-8")
    payload = make_plan_payload(script_sha256(script_path))
    shot_payload = payload["scenes"][0]["shots"][1]
    shot_payload["duration_seconds"] = 7.92
    shot_payload["end_state"]["at_seconds"] = 7.92
    shot_payload["relationships"] = [
        {
            "relationship_id": "solar_eclipse_occlusion",
            "type": "occlusion_alignment",
            "owner": "simulation",
            "entity_ids": ["sun", "moon", "earth"],
        }
    ]
    shot_payload["simulation"] = {
        "model": "sun-earth-moon-eclipse-teaching-model-v1",
        "template": "solar-eclipse-alignment",
        "parameters": {
            "moon_orbit_inclination_degrees": 5.0,
            "moon_orbit_radius": 2.2,
            "sun_distance": 8.0,
            "sun_longitude_degrees": 0.0,
            "moon_longitude_start_degrees": -6.0,
            "moon_longitude_end_degrees": 0.0,
        },
        "renderer_options": {
            "show_umbra": True,
            "style": {
                "seed": 5107,
                "earth_scale": 1.0,
                "moon_scale": 1.0,
                "sun_scale": 1.0,
            },
        },
    }
    payload["scenes"][0]["duration_seconds"] = 7.92
    payload["scenes"][0]["shots"] = [shot_payload]
    shot_payload["shot_id"] = "01A"
    plan = ProductionPlan.model_validate(payload)
    shot = plan.scenes[0].shots[0]
    context = ShotContext(
        run_dir=tmp_path,
        plan=plan,
        backend_versions={"simulation": SimulationBackend.version},
    )

    job = SimulationBackend().build_job(shot, context, tmp_path / "frames")

    assert job["template"] == "solar-eclipse-alignment"
    assert job["duration_seconds"] == 7.92
    assert "physics" not in job
    assert job["eclipse"]["parameters"] == shot.simulation.parameters
    assert job["eclipse"]["renderer_options"] == shot.simulation.renderer_options


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("npm") is None,
    reason="FFmpeg and Node are required",
)
def test_composite_backend_renders_exact_overlay_and_requires_review(tmp_path: Path):
    context, _ = make_context(tmp_path)
    shot = context.plan.scenes[0].shots[2]
    context.plan.defaults.width = 160
    context.plan.defaults.height = 90
    context.plan.defaults.fps = 10
    context.media_probe = probe_media
    shot.duration_seconds = 0.6
    shot.end_state.at_seconds = 0.6
    shot.overlays[0].keyframes[-1].at_seconds = 0.6
    source = context.safe_path(shot.base.generation.inbox_file)
    source.parent.mkdir(parents=True, exist_ok=True)
    make_test_video(source)

    output = CompositeBackend().render(shot, context)
    info = probe_media(output)

    assert info.frame_count == 6
    assert info.audio_codec is None
    review = ShotReviewRecord.model_validate_json(
        context.review_path(shot).read_text(encoding="utf-8")
    )
    assert review.status == "pending"
