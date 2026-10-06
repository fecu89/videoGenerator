from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import pytest

from video_harness.migration import migrate_run, migration_main, plan_video, retime_run
from video_harness.models import Scene, ScriptArtifact, SelectedTopic, StoryEngine
from video_harness.production import script_sha256
from video_harness.prompt_compiler import expected_prompt_path
from video_harness.settings import HarnessSettings, write_settings_snapshot
from video_harness.storage import RunStore, scene_filename
from video_harness.tests.test_simulation import make_script as make_simulation_script
from video_harness.tests.test_simulation import simulation_payload
from video_harness.variants import SequenceVariantPlan


def make_legacy_script() -> ScriptArtifact:
    scene = Scene(
        scene_id=1,
        title="기존_장면",
        narration="기존 실행 폴더의 나레이션입니다.",
        narrative_role="HOOK",
        visual_subject="실제 터널 벽에서 물이 흐르는 한 장면",
        duration_seconds=6.0,
        audio_file="audioFiles/01_기존_장면.mp3",
        video_prompt_file="videoPrompt/01_기존_장면.txt",
    )
    return ScriptArtifact(
        selected_topic=SelectedTopic(title="기존 실행", reason="마이그레이션 테스트"),
        story_engine=StoryEngine(
            common_belief="상식",
            contradiction="충돌",
            obvious_answer="질문",
            constraint="조건",
            actual_answer="답",
            mechanism="원리",
            payoff="결과",
        ),
        scenes=[scene],
    )


def prepare_run(tmp_path: Path, script: ScriptArtifact) -> RunStore:
    root = tmp_path / "run"
    root.mkdir()
    store = RunStore(root)
    store.audio_dir.mkdir()
    store.video_prompt_dir.mkdir()
    store.write_script(script)
    for scene in script.scenes:
        (store.audio_dir / scene_filename(scene, ".mp3")).write_bytes(b"audio")
    return store


def test_simulation_migration_creates_one_deterministic_shot_per_scene(tmp_path: Path):
    script = make_simulation_script()
    store = prepare_run(tmp_path, script)
    (store.root / "simulation.json").write_text(
        json.dumps(simulation_payload(), ensure_ascii=False),
        encoding="utf-8",
    )
    archived = store.video_prompt_dir / "01_장면_1.txt"
    archived.write_bytes(b"legacy prompt")
    before = archived.read_bytes()

    plan = migrate_run(store.root, schema_version=1)

    assert all(scene.shots[0].render_mode == "simulation" for scene in plan.scenes)
    assert archived.read_bytes() == before
    assert all(expected_prompt_path(scene.shots[0]) is None for scene in plan.scenes)
    assert (store.root / "production-plan.json").is_file()
    assert (store.root / "video-plan.md").is_file()


def test_legacy_migration_preserves_existing_prompts_and_adds_compiled_shot_prompt(
    tmp_path: Path,
):
    script = make_legacy_script()
    store = prepare_run(tmp_path, script)
    legacy_prompt = store.video_prompt_dir / "01_기존_장면.txt"
    legacy_prompt.write_bytes(b"legacy bytes")

    plan = migrate_run(store.root, schema_version=1)

    assert legacy_prompt.read_bytes() == b"legacy bytes"
    assert plan.scenes[0].shots[0].render_mode == "generated"
    assert (store.video_prompt_dir / "01A_기존_장면.txt").is_file()


def test_migration_refuses_to_overwrite_manifest(tmp_path: Path):
    store = prepare_run(tmp_path, make_legacy_script())
    migrate_run(store.root, schema_version=1)
    with pytest.raises(FileExistsError):
        migrate_run(store.root, schema_version=1)


def test_force_rebuilds_only_derived_files(tmp_path: Path):
    store = prepare_run(tmp_path, make_legacy_script())
    source = store.video_prompt_dir / "01_기존_장면.txt"
    source.write_bytes(b"source")
    migrate_run(store.root, schema_version=1)
    (store.root / "video-plan.md").write_text("edited", encoding="utf-8")

    migrate_run(store.root, force=True, schema_version=1)

    assert source.read_bytes() == b"source"
    assert (store.root / "video-plan.md").read_text(encoding="utf-8").startswith(
        "# Video Production Plan"
    )


def test_migration_requires_measured_scene_duration(tmp_path: Path):
    script = make_legacy_script()
    script.scenes[0].duration_seconds = None
    store = prepare_run(tmp_path, script)
    with pytest.raises(ValueError, match="duration_seconds"):
        migrate_run(store.root, schema_version=1)


def test_plan_video_rejects_stale_script_hash_before_writing(tmp_path: Path):
    store = prepare_run(tmp_path, make_legacy_script())
    plan = migrate_run(store.root, schema_version=1)
    compiled = store.video_prompt_dir / "01A_기존_장면.txt"
    compiled.unlink()
    script = store.read_script()
    script.selected_topic.reason = "changed"
    store.write_script(script)

    with pytest.raises(ValueError, match="script_hash_mismatch"):
        plan_video(store.root)
    assert not compiled.exists()


def test_plan_video_rejects_stale_variant_plan_before_writing(tmp_path: Path):
    store = prepare_run(tmp_path, make_legacy_script())
    plan = migrate_run(store.root, schema_version=1)
    base = plan.scenes[0].shots[0].model_dump(mode="json")
    alternates = []
    variants = []
    for index, variant_id in enumerate(
        ("balanced", "explain", "dynamic", "cinematic")
    ):
        shot_id = "01A" if index == 0 else f"01{chr(ord('A') + index)}"
        if index:
            shot = copy.deepcopy(base)
            shot["shot_id"] = shot_id
            shot["title"] = f"대안 {index}"
            shot["generation"]["prompt_file"] = f"videoPrompt/{shot_id}_대안.txt"
            shot["generation"]["inbox_file"] = f"shotFiles/inbox/{shot_id}_대안.mp4"
            alternates.append({"scene_id": 1, "shot": shot})
        variants.append(
            {
                "variant_id": variant_id,
                "label": variant_id,
                "scenes": [{"scene_id": 1, "shot_ids": [shot_id]}],
            }
        )
    store.write_json(
        "variant-plan.json",
        {
            "schema_version": 1,
            "production_plan_sha256": "0" * 64,
            "script_sha256": "0" * 64,
            "alternate_shots": alternates,
            "variants": variants,
        },
    )

    with pytest.raises(ValueError, match="variant_production_hash_mismatch"):
        plan_video(store.root)


def _prepare_simulation_run(tmp_path: Path) -> Path:
    script = make_simulation_script(scene_count=2)
    store = prepare_run(tmp_path, script)
    (store.root / "simulation.json").write_text(
        json.dumps(simulation_payload(scene_count=2), ensure_ascii=False),
        encoding="utf-8",
    )
    return store.root


def test_v2_migration_creates_one_sequence_per_scene(tmp_path: Path):
    run_dir = _prepare_simulation_run(tmp_path)
    (run_dir / "videoPrompt").rmdir()

    plan = migrate_run(run_dir, schema_version=2)

    assert plan.schema_version == 2
    assert [item.scene_ids for item in plan.visual_sequences] == [[1], [2]]
    assert all(item.primary_route == "local" for item in plan.visual_sequences)
    assert (run_dir / "local-sequence-plan.json").is_file()
    assert (run_dir / "online-plan.json").is_file()
    assert not (run_dir / "videoPrompt").exists()


def test_explicit_v1_migration_keeps_shot_plan(tmp_path: Path):
    run_dir = _prepare_simulation_run(tmp_path)

    plan = migrate_run(run_dir, schema_version=1)

    assert plan.schema_version == 1
    assert all(scene.shots for scene in plan.scenes)
    assert not (run_dir / "local-sequence-plan.json").exists()
    assert not (run_dir / "online-plan.json").exists()


def test_v2_migration_preserves_short_generated_boundary_and_mode(tmp_path: Path):
    script = make_legacy_script()
    script.scenes[0].duration_seconds = 3.5
    store = prepare_run(tmp_path, script)
    (store.root / "videoPrompt").rmdir()

    plan = migrate_run(store.root, schema_version=2)
    online = json.loads((store.root / "online-plan.json").read_text(encoding="utf-8"))

    assert plan.visual_sequences[0].primary_route == "online_required"
    assert online["shots"][0]["preferred_mode"] == "t2v"
    assert online["shots"][0]["short_shot_reason"] == "legacy shot boundary preserved"
    assert not (store.root / "videoPrompt").exists()


def test_v2_plan_video_loads_validates_and_compiles_all_three_plans(tmp_path: Path):
    run_dir = _prepare_simulation_run(tmp_path)
    (run_dir / "videoPrompt").rmdir()
    migrate_run(run_dir)
    for path in (run_dir / "video-plan.md", run_dir / "videoFiles/prompts/local/SEQ01.md"):
        path.unlink()

    written = plan_video(run_dir)

    assert run_dir / "video-plan.md" in written
    assert run_dir / "videoFiles/prompts/local/SEQ01.md" in written
    assert not (run_dir / "videoPrompt").exists()


def test_v2_plan_video_rejects_cross_plan_issue_before_writing(tmp_path: Path):
    run_dir = _prepare_simulation_run(tmp_path)
    (run_dir / "videoPrompt").rmdir()
    migrate_run(run_dir)
    review = run_dir / "video-plan.md"
    review.unlink()
    local_path = run_dir / "local-sequence-plan.json"
    local = json.loads(local_path.read_text(encoding="utf-8"))
    local["script_sha256"] = "f" * 64
    local_path.write_text(json.dumps(local), encoding="utf-8")

    with pytest.raises(ValueError, match="stale_script"):
        plan_video(run_dir)
    assert not review.exists()


def test_retime_v2_run_preserves_design_and_rebinds_all_plan_hashes(tmp_path: Path):
    run_dir = _prepare_simulation_run(tmp_path)
    (run_dir / "videoPrompt").rmdir()
    production = migrate_run(run_dir)
    store = RunStore.open(run_dir)
    sequence_ids = [item.sequence_id for item in production.visual_sequences]
    variants = SequenceVariantPlan.model_validate(
        {
            "schema_version": 2,
            "production_plan_sha256": script_sha256(
                run_dir / "production-plan.json"
            ),
            "local_sequence_plan_sha256": script_sha256(
                run_dir / "local-sequence-plan.json"
            ),
            "script_sha256": script_sha256(run_dir / "script.json"),
            "variants": [
                {
                    "variant_id": "balanced",
                    "label": "Balanced",
                    "sequence_ids": sequence_ids,
                },
                {
                    "variant_id": "explain",
                    "label": "Explain",
                    "sequence_ids": sequence_ids,
                    "overrides": [
                        {
                            "sequence_id": sequence_ids[0],
                            "layer_timing_profile": "explain",
                        }
                    ],
                },
                {
                    "variant_id": "dynamic",
                    "label": "Dynamic",
                    "sequence_ids": sequence_ids,
                    "overrides": [
                        {
                            "sequence_id": sequence_ids[0],
                            "camera_profile": "close",
                        }
                    ],
                },
                {
                    "variant_id": "cinematic",
                    "label": "Cinematic",
                    "sequence_ids": sequence_ids,
                    "overrides": [
                        {
                            "sequence_id": sequence_ids[0],
                            "lighting_profile": "cinematic",
                        }
                    ],
                },
            ],
        }
    )
    store.write_model("variant-plan.json", variants)

    script = store.read_script()
    new_durations = [7.1, 5.75]
    for scene, duration in zip(script.scenes, new_durations, strict=True):
        scene.duration_seconds = duration
    store.write_script(script)
    write_settings_snapshot(run_dir, HarnessSettings())

    retimed = retime_run(run_dir)

    production_payload = store.read_json("production-plan.json")
    local_payload = store.read_json("local-sequence-plan.json")
    online_payload = store.read_json("online-plan.json")
    variant_payload = store.read_json("variant-plan.json")
    expected_audio_frames = [math.ceil(value * 30) for value in new_durations]
    expected_local_frames = [expected_audio_frames[0] + 20, expected_audio_frames[1]]
    assert retimed.visual_sequences == production.visual_sequences
    assert [item["duration_seconds"] for item in production_payload["scenes"]] == new_durations
    assert [item["duration_frames"] for item in local_payload["sequences"]] == expected_local_frames
    assert [item["end_frame"] for item in production_payload["visual_beats"]] == expected_audio_frames
    assert [item["source_end_frame"] for item in online_payload["shots"]] == expected_audio_frames
    assert production_payload["script_sha256"] == script_sha256(run_dir / "script.json")
    assert local_payload["production_plan_sha256"] == script_sha256(
        run_dir / "production-plan.json"
    )
    assert online_payload["production_plan_sha256"] == script_sha256(
        run_dir / "production-plan.json"
    )
    assert variant_payload["local_sequence_plan_sha256"] == script_sha256(
        run_dir / "local-sequence-plan.json"
    )
    assert variant_payload["production_plan_sha256"] == script_sha256(
        run_dir / "production-plan.json"
    )
    assert variant_payload["script_sha256"] == script_sha256(run_dir / "script.json")
    assert plan_video(run_dir)


def test_retime_local_scenes_embeds_configured_audio_pause_without_changing_online_cap(
    tmp_path: Path,
):
    run_dir = _prepare_simulation_run(tmp_path)
    (run_dir / "videoPrompt").rmdir()
    migrate_run(run_dir)
    store = RunStore.open(run_dir)
    write_settings_snapshot(
        run_dir,
        HarnessSettings(
            voice={"min_scene_seconds": 5.0, "max_scene_seconds": 14.0},
            local_video={
                "min_scene_seconds": 5.0,
                "max_scene_seconds": 15.0,
                "scene_gap_seconds": 0.65,
            },
        ),
    )
    script = store.read_script()
    for scene, duration in zip(script.scenes, [7.6, 5.75], strict=True):
        scene.duration_seconds = duration
    store.write_script(script)

    retime_run(run_dir)

    retimed_production = store.read_json("production-plan.json")
    local = store.read_json("local-sequence-plan.json")
    online = store.read_json("online-plan.json")
    first_span = local["sequences"][0]["scene_spans"][0]
    second_span = local["sequences"][1]["scene_spans"][0]
    assert first_span == {
        "scene_id": 1,
        "start_frame": 0,
        "end_frame": 248,
        "audio_start_frame": 0,
        "audio_end_frame": 228,
        "tail_silence_frames": 20,
    }
    assert second_span == {
        "scene_id": 2,
        "start_frame": 0,
        "end_frame": 173,
        "audio_start_frame": 0,
        "audio_end_frame": 173,
        "tail_silence_frames": 0,
    }
    assert local["defaults"] == {
        "width": 1920,
        "height": 1080,
        "fps": 30,
        "min_scene_seconds": 5.0,
        "max_scene_seconds": 15.0,
        "scene_gap_seconds": 0.65,
    }
    assert local["sequences"][0]["timeline"][0]["end_frame"] == 248
    assert retimed_production["visual_beats"][0]["end_frame"] == 228
    assert online["shots"][0]["source_end_frame"] == 228
    assert online["shots"][0]["duration_seconds"] == pytest.approx(7.6)
    assert online["shots"][0]["duration_seconds"] <= 8
    assert plan_video(run_dir)


def test_retime_splits_long_local_beat_into_online_shots_capped_at_eight_seconds(
    tmp_path: Path,
):
    run_dir = _prepare_simulation_run(tmp_path)
    (run_dir / "videoPrompt").rmdir()
    migrate_run(run_dir)
    store = RunStore.open(run_dir)
    write_settings_snapshot(run_dir, HarnessSettings())
    script = store.read_script()
    for scene, duration in zip(script.scenes, [12.6, 5.75], strict=True):
        scene.duration_seconds = duration
    store.write_script(script)

    retime_run(run_dir)

    local = store.read_json("local-sequence-plan.json")
    online = store.read_json("online-plan.json")
    first_span = local["sequences"][0]["scene_spans"][0]
    first_shots = [shot for shot in online["shots"] if shot["beat_ids"] == ["B01"]]
    assert first_span["audio_end_frame"] == 378
    assert first_span["end_frame"] == 398
    assert len(first_shots) == 2
    assert max(shot["duration_seconds"] for shot in first_shots) <= 8.0
    assert sorted(
        (shot["source_start_frame"], shot["source_end_frame"])
        for shot in first_shots
    ) == [(0, 240), (240, 378)]
    assert plan_video(run_dir)


def test_migration_cli_defaults_to_schema_v2(tmp_path: Path):
    run_dir = _prepare_simulation_run(tmp_path)
    (run_dir / "videoPrompt").rmdir()

    assert migration_main([str(run_dir)]) == 0

    payload = json.loads((run_dir / "production-plan.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == 2


@pytest.fixture(autouse=True)
def isolate_editorial_gate_dependency(monkeypatch):
    """These subsystem tests use synthetic plans; real gate entrypoints are covered
    without mocks in test_creative_gates.py. Keep this dependency module-scoped.
    """
    monkeypatch.setattr("video_harness.creative_gates.require_creative_plan", lambda *args, **kwargs: [])
