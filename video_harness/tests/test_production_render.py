from __future__ import annotations

import copy
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from video_harness.production import script_sha256
from video_harness.production_models import ProductionPlan
from video_harness.production_render import approve_shot, render_production
from video_harness.prompt_compiler import write_compiled_artifacts
from video_harness.storage import RunStore, scene_filename
from video_harness.tests.test_production_models import make_plan_payload, make_script
from video_harness.tests.test_shot_backends import make_test_png, make_test_video
from video_harness.variants import VariantPlan


pytestmark = pytest.mark.skipif(
    any(shutil.which(name) is None for name in ("ffmpeg", "ffprobe", "npm")),
    reason="FFmpeg and Node are required",
)


def make_audio(path: Path, duration: float) -> None:
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
            f"sine=frequency=330:duration={duration}",
            "-codec:a",
            "libmp3lame",
            "-q:a",
            "4",
            str(path),
        ],
        check=True,
    )


def prepare_mixed_run(
    tmp_path: Path,
    *,
    include_second_scene: bool = False,
) -> tuple[Path, ProductionPlan]:
    run_dir = tmp_path / "mixed-run"
    run_dir.mkdir()
    store = RunStore(run_dir)
    store.audio_dir.mkdir()
    store.video_prompt_dir.mkdir()
    store.ensure_production_directories()

    script = make_script(duration=2.0)
    if include_second_scene:
        second_scene = script.scenes[0].model_copy(deep=True)
        second_scene.scene_id = 2
        second_scene.title = "두번째 장면"
        second_scene.narration = "두 번째 장면의 전환 렌더를 검증합니다."
        second_scene.duration_seconds = 1.0
        second_scene.audio_file = "audioFiles/02_두번째_장면.mp3"
        script.scenes.append(second_scene)
    store.write_script(script)
    payload = make_plan_payload(script_sha256(run_dir / "script.json"))
    payload["defaults"].update({"width": 160, "height": 90, "fps": 5})
    payload["scenes"][0]["duration_seconds"] = 2.0
    durations = [0.6, 0.4, 0.6, 0.4]
    for shot, duration in zip(payload["scenes"][0]["shots"], durations, strict=True):
        shot["duration_seconds"] = duration
        shot["end_state"]["at_seconds"] = duration
    payload["scenes"][0]["shots"][3]["still_motion"]["camera_keyframes"][-1][
        "at_seconds"
    ] = 0.4
    payload["scenes"][0]["shots"][2]["overlays"][0]["keyframes"][-1][
        "at_seconds"
    ] = 0.6
    if include_second_scene:
        second_shot = payload["scenes"][0]["shots"][3].copy()
        second_shot["shot_id"] = "02A"
        second_shot["title"] = "두번째 고정 이미지"
        second_shot["duration_seconds"] = 1.0
        second_shot["dependencies"] = []
        second_shot["end_state"] = {"at_seconds": 1.0, "entities": {}}
        second_shot["still_motion"] = {
            "source_image": "shotAssets/backgrounds/02A.png",
            "camera_keyframes": [
                {"at_seconds": 0.0, "center": [0.5, 0.5], "scale": 1.0},
                {"at_seconds": 1.0, "center": [0.5, 0.5], "scale": 1.05},
            ],
            "layers": [],
        }
        payload["scenes"].append(
            {"scene_id": 2, "duration_seconds": 1.0, "shots": [second_shot]}
        )
    simulation = payload["scenes"][0]["shots"][1]
    simulation["relationships"][0]["type"] = "fixed_distance"
    simulation["simulation"]["parameters"] = {
        "earth_period_days": 365.0,
        "mars_period_days": 687.0,
        "earth_orbit_radius": 1.0,
        "mars_orbit_radius": 1.52,
        "opposition_day": 0.0,
        "simulation_day_start": -10.0,
        "simulation_day_end": 10.0,
    }
    simulation["simulation"]["renderer_options"] = {
        "style": {"seed": 1, "earth_scale": 0.075, "mars_scale": 0.055}
    }
    plan = ProductionPlan.model_validate(payload)
    store.write_model("production-plan.json", plan)

    make_test_png(run_dir / "shotAssets/starts/01A.png")
    make_test_png(run_dir / "shotAssets/backgrounds/01D.png")
    if include_second_scene:
        make_test_png(run_dir / "shotAssets/backgrounds/02A.png")
    make_test_video(run_dir / "shotFiles/inbox/01A_생성.mp4", duration=1.0)
    make_test_video(run_dir / "shotFiles/inbox/01C_합성.mp4", duration=1.0)
    scene = script.scenes[0]
    make_audio(store.audio_dir / scene_filename(scene, ".mp3"), 2.0)
    if include_second_scene:
        second_scene = script.scenes[1]
        make_audio(store.audio_dir / scene_filename(second_scene, ".mp3"), 1.0)
    write_compiled_artifacts(run_dir, plan, script)
    return run_dir, plan


def approve_generated_shots(run_dir: Path, plan: ProductionPlan, shot_ids: list[str]) -> None:
    by_id = {
        shot.shot_id: shot for scene in plan.scenes for shot in scene.shots
    }
    for shot_id in shot_ids:
        shot = by_id[shot_id]
        approve_shot(
            run_dir,
            shot_id,
            invariant_results={item: True for item in shot.invariants},
            note="preview checked",
        )


def write_variant_plan(run_dir: Path, plan: ProductionPlan) -> VariantPlan:
    shots = [shot.model_dump(mode="json") for shot in plan.scenes[0].shots]
    explain = copy.deepcopy(shots[1])
    explain["shot_id"] = "01E"
    explain["title"] = "설명 대안"
    explain["simulation"]["renderer_options"]["style"]["seed"] = 2
    dynamic = copy.deepcopy(shots[3])
    dynamic["shot_id"] = "01F"
    dynamic["title"] = "동적 대안"
    dynamic["dependencies"] = []
    dynamic["still_motion"]["camera_keyframes"][-1]["center"] = [0.45, 0.5]
    base_timeline = [shot["shot_id"] for shot in shots]
    variant_plan = VariantPlan.model_validate(
        {
            "schema_version": 1,
            "production_plan_sha256": script_sha256(run_dir / "production-plan.json"),
            "script_sha256": script_sha256(run_dir / "script.json"),
            "alternate_shots": [
                {"scene_id": 1, "shot": explain},
                {"scene_id": 1, "shot": dynamic},
            ],
            "variants": [
                {"variant_id": "balanced", "label": "Balanced", "scenes": [{"scene_id": 1, "shot_ids": base_timeline}]},
                {"variant_id": "explain", "label": "Explain", "scenes": [{"scene_id": 1, "shot_ids": ["01A", "01E", "01C", "01D"]}]},
                {"variant_id": "dynamic", "label": "Dynamic", "scenes": [{"scene_id": 1, "shot_ids": ["01A", "01B", "01C", "01F"]}]},
                {"variant_id": "cinematic", "label": "Cinematic", "scenes": [{"scene_id": 1, "shot_ids": ["01A", "01E", "01C", "01F"]}]},
            ],
        }
    )
    (run_dir / "variant-plan.json").write_text(
        variant_plan.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    return variant_plan


def test_render_production_assembles_shots_scenes_and_final(tmp_path: Path):
    run_dir, plan = prepare_mixed_run(tmp_path)
    prepared = render_production(run_dir, quality="draft", shots_only=True)
    assert prepared.status == "awaiting_review"
    assert prepared.review_required_shot_ids == ["01A", "01C"]
    approve_generated_shots(run_dir, plan, prepared.review_required_shot_ids)

    report = render_production(run_dir, quality="draft")

    assert report.status == "complete"
    assert (run_dir / "shotFiles/01A_생성.mp4").is_file()
    assert (run_dir / "videoFiles/draft/original/01_혼합_장면.mp4").is_file()
    assert (run_dir / "videoFiles/draft/01_혼합_장면.mp4").is_file()
    assert (run_dir / "video-only-draft.mp4").is_file()
    assert (run_dir / "final-draft.mp4").is_file()
    assert (run_dir / "videoFiles/draft/previews/01_혼합_장면/0000ms.png").is_file()
    assert not (run_dir / "videoFiles/variants").exists()


def test_render_production_builds_four_variants_from_shared_shots(tmp_path: Path):
    run_dir, plan = prepare_mixed_run(tmp_path)
    write_variant_plan(run_dir, plan)
    prepared = render_production(run_dir, quality="final", shots_only=True)

    assert set(prepared.rendered_shot_ids) == {"01A", "01B", "01C", "01D", "01E", "01F"}
    approve_generated_shots(run_dir, plan, prepared.review_required_shot_ids)

    report = render_production(run_dir, quality="final")

    assert report.status == "complete"
    assert report.variant_files == [
        "final.mp4",
        "videoFiles/variants/02_explain.mp4",
        "videoFiles/variants/03_dynamic.mp4",
        "videoFiles/variants/04_cinematic.mp4",
    ]
    for relative in (
        "videoFiles/variants/02_explain.mp4",
        "videoFiles/variants/03_dynamic.mp4",
        "videoFiles/variants/04_cinematic.mp4",
        "videoFiles/variants/video-only/02_explain.mp4",
        "videoFiles/variants/video-only/03_dynamic.mp4",
        "videoFiles/variants/video-only/04_cinematic.mp4",
        "videoFiles/variants/previews/balanced/0000ms.png",
        "videoFiles/variants/previews/explain/0000ms.png",
        "videoFiles/variants/previews/dynamic/0000ms.png",
        "videoFiles/variants/previews/cinematic/0000ms.png",
        "videoFiles/variants/variants.json",
    ):
        assert (run_dir / relative).is_file(), relative
    manifest = json.loads(
        (run_dir / "videoFiles/variants/variants.json").read_text(encoding="utf-8")
    )
    assert [item["variant_id"] for item in manifest["variants"]] == [
        "balanced",
        "explain",
        "dynamic",
        "cinematic",
    ]
    assert manifest["unique_shot_count"] == 6
    assert manifest["shared_audio_files"] == ["audioFiles/01_혼합_장면.mp3"]


def test_render_production_adds_scene_transition_frames_to_final(tmp_path: Path):
    run_dir, plan = prepare_mixed_run(tmp_path, include_second_scene=True)
    prepared = render_production(run_dir, quality="draft", shots_only=True)
    approve_generated_shots(run_dir, plan, prepared.review_required_shot_ids)

    render_production(run_dir, quality="draft")

    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-count_frames",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=nb_read_frames",
            "-of",
            "csv=p=0",
            str(run_dir / "video-only-draft.mp4"),
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    assert int(result.stdout.strip()) == 19


def test_force_rerender_invalidates_generated_approval(tmp_path: Path):
    run_dir, plan = prepare_mixed_run(tmp_path)
    prepared = render_production(run_dir, shots_only=True)
    approve_generated_shots(run_dir, plan, prepared.review_required_shot_ids)

    rerendered = render_production(run_dir, shots_only=True, force=True)

    assert rerendered.status == "awaiting_review"
    review = json.loads((run_dir / "shotFiles/reviews/01A.json").read_text(encoding="utf-8"))
    assert review["status"] == "pending"


def test_missing_generated_input_fails_before_scene_assembly(tmp_path: Path):
    run_dir, _ = prepare_mixed_run(tmp_path)
    (run_dir / "shotFiles/inbox/01C_합성.mp4").unlink()

    with pytest.raises(FileNotFoundError, match="01C_합성.mp4"):
        render_production(run_dir, shots_only=True)

    assert not (run_dir / "videoFiles/01_혼합_장면.mp4").exists()


def test_selective_render_does_not_build_final_outputs(tmp_path: Path):
    run_dir, _ = prepare_mixed_run(tmp_path)
    render_production(run_dir, scene_ids={1}, shots_only=True)
    assert not (run_dir / "final.mp4").exists()
    assert not (run_dir / "video-only.mp4").exists()


@pytest.fixture(autouse=True)
def isolate_editorial_gate_dependency(monkeypatch):
    """These subsystem tests use synthetic plans; real gate entrypoints are covered
    without mocks in test_creative_gates.py. Keep this dependency module-scoped.
    """
    monkeypatch.setattr("video_harness.creative_gates.require_legacy_render_gate", lambda *args, **kwargs: [])
