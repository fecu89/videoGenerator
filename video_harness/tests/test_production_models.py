from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from video_harness.models import Scene, ScriptArtifact, SelectedTopic, StoryEngine
from video_harness.production import (
    load_production_plan,
    script_sha256,
    validate_plan_against_script,
    write_production_schema,
)
from video_harness.production_models import ProductionPlan
from video_harness.storage import shot_filename


def make_script(duration: float = 8.0) -> ScriptArtifact:
    return ScriptArtifact(
        selected_topic=SelectedTopic(title="샷 라우팅", reason="테스트"),
        story_engine=StoryEngine(
            common_belief="상식",
            contradiction="충돌",
            obvious_answer="질문",
            constraint="조건",
            actual_answer="답",
            mechanism="원리",
            payoff="결과",
        ),
        scenes=[
            Scene(
                scene_id=1,
                title="혼합 장면",
                narration="한 장면 안에서 네 가지 제작 방식을 검증합니다.",
                narrative_role="MECHANISM",
                visual_subject="혼합 제작 장면",
                duration_seconds=duration,
                audio_file="audioFiles/01_혼합_장면.mp3",
            )
        ],
    )


def base_shot(shot_id: str, title: str, duration: float, mode: str) -> dict:
    return {
        "shot_id": shot_id,
        "title": title,
        "duration_seconds": duration,
        "render_mode": mode,
        "purpose": f"{title}의 목적",
        "single_event": f"{title}에서 한 사건이 일어난다",
        "coordinate_space": {
            "type": "image_normalized",
            "frame_id": "frame",
            "screen_convention": "x grows right, y grows down",
        },
        "entities": [],
        "paths": [],
        "start_state": {"at_seconds": 0.0, "entities": {}},
        "end_state": {"at_seconds": duration, "entities": {}},
        "invariants": ["배경과 조명이 일정하게 유지된다"],
        "motion_contract": {"primary_event": f"{title}_event", "tracks": []},
        "camera": {
            "projection": "perspective",
            "framing": "medium",
            "movement": "locked",
        },
        "assets": {},
        "relationships": [],
        "dependencies": [],
        "excluded_elements": ["subtitles", "watermarks"],
    }


def make_plan_payload(script_hash: str) -> dict:
    generated = base_shot("01A", "생성", 2.0, "generated")
    generated.update(
        {
            "assets": {"start_image": "shotAssets/starts/01A.png"},
            "relationships": [
                {
                    "relationship_id": "single_subject_motion",
                    "type": "relative_placement",
                    "owner": "generated_model",
                    "entity_ids": ["worker"],
                }
            ],
            "generation": {
                "mode": "i2v",
                "prompt_file": "videoPrompt/01A_생성.txt",
                "inbox_file": "shotFiles/inbox/01A_생성.mp4",
            },
        }
    )

    simulation = base_shot("01B", "시뮬레이션", 2.0, "simulation")
    simulation.update(
        {
            "coordinate_space": {
                "type": "world_3d",
                "frame_id": "heliocentric_ecliptic",
                "origin": "sun.center",
                "positive_x": "opposition direction",
                "positive_y": "90 degrees counterclockwise",
                "positive_z": "north ecliptic pole",
                "screen_convention": "north ecliptic pole viewed from positive z",
            },
            "entities": [
                {
                    "entity_id": "earth",
                    "anchor": "center",
                    "identity_ref": "earth-v1",
                    "path_id": "earth_orbit",
                },
                {
                    "entity_id": "mars",
                    "anchor": "center",
                    "identity_ref": "mars-v1",
                    "path_id": "mars_orbit",
                },
            ],
            "paths": [
                {
                    "path_id": "earth_orbit",
                    "type": "circle",
                    "center": "sun.center",
                    "radius": 1.0,
                    "plane": "heliocentric_ecliptic",
                },
                {
                    "path_id": "mars_orbit",
                    "type": "circle",
                    "center": "sun.center",
                    "radius": 1.52,
                    "plane": "heliocentric_ecliptic",
                },
            ],
            "relationships": [
                {
                    "relationship_id": "earth_path",
                    "type": "path_membership",
                    "owner": "simulation",
                    "entity_ids": ["earth"],
                }
            ],
            "simulation": {
                "model": "circular-teaching-model",
                "template": "earth-overtake",
                "parameters": {"earth_period_days": 365.256, "mars_period_days": 686.98},
                "renderer_options": {},
            },
        }
    )

    composite = base_shot("01C", "합성", 2.0, "composite")
    composite.update(
        {
            "relationships": [
                {
                    "relationship_id": "sightline",
                    "type": "attached_line",
                    "owner": "deterministic_overlay",
                    "entity_ids": ["earth", "mars"],
                }
            ],
            "base": {
                "mode": "generated",
                "generation": {
                    "mode": "t2v",
                    "prompt_file": "videoPrompt/01C_합성.txt",
                    "inbox_file": "shotFiles/inbox/01C_합성.mp4",
                },
            },
            "overlays": [
                {
                    "overlay_id": "sightline_overlay",
                    "type": "line",
                    "relationship_id": "sightline",
                    "style": {"stroke": "#ffffff", "width": 2},
                    "keyframes": [
                        {"at_seconds": 0.0, "points": [[0.2, 0.6], [0.6, 0.4]]},
                        {"at_seconds": 2.0, "points": [[0.3, 0.6], [0.7, 0.4]]},
                    ],
                }
            ],
        }
    )

    still = base_shot("01D", "고정 이미지", 2.0, "still_motion")
    still.update(
        {
            "dependencies": [{"shot_id": "01C", "artifact": "final_frame"}],
            "still_motion": {
                "source_image": "shotAssets/backgrounds/01D.png",
                "camera_keyframes": [
                    {"at_seconds": 0.0, "center": [0.5, 0.5], "scale": 1.0},
                    {"at_seconds": 2.0, "center": [0.55, 0.5], "scale": 1.1},
                ],
                "layers": [],
            },
        }
    )

    return {
        "schema_version": 1,
        "script_sha256": script_hash,
        "defaults": {
            "width": 1920,
            "height": 1080,
            "fps": 30,
            "preview_interval_seconds": 2.0,
        },
        "style_bible": {
            "visual_mode": "scientific educational visualization",
            "entities": [
                {
                    "entity_id": "earth-v1",
                    "appearance_constraints": ["blue oceans", "white clouds"],
                    "reference_assets": [],
                },
                {
                    "entity_id": "mars-v1",
                    "appearance_constraints": ["rust red surface"],
                    "reference_assets": [],
                },
            ],
            "palette": ["navy", "white", "rust"],
            "lighting": "stable neutral light",
            "excluded_elements": ["logos"],
        },
        "scenes": [
            {
                "scene_id": 1,
                "duration_seconds": 8.0,
                "shots": [generated, simulation, composite, still],
            }
        ],
    }


def make_v2_plan_payload(script_hash: str) -> dict:
    payload = make_plan_payload(script_hash)
    payload["schema_version"] = 2
    payload["scenes"][0]["shots"] = []
    payload["visual_sequences"] = [
        {
            "sequence_id": "SEQ01",
            "scene_ids": [1],
            "primary_route": "local",
            "purpose": "하나의 공유 장면에서 원리를 설명한다",
            "visual_beat_ids": ["B01"],
        }
    ]
    payload["visual_beats"] = [
        {
            "beat_id": "B01",
            "scene_id": 1,
            "start_frame": 0,
            "end_frame": 240,
            "primary_event": "관계선이 누적된다",
            "relationship_owner": "simulation",
        }
    ]
    return payload


@pytest.fixture
def run_with_plan(tmp_path: Path) -> tuple[Path, ScriptArtifact, dict]:
    script = make_script()
    script_path = tmp_path / "script.json"
    script_path.write_text(script.model_dump_json(indent=2) + "\n", encoding="utf-8")
    payload = make_plan_payload(script_sha256(script_path))

    for relative in (
        "shotAssets/starts/01A.png",
        "shotAssets/backgrounds/01D.png",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
    return tmp_path, script, payload


def test_production_plan_parses_all_render_modes(run_with_plan):
    _, _, payload = run_with_plan
    plan = ProductionPlan.model_validate(payload)
    assert [shot.render_mode for shot in plan.scenes[0].shots] == [
        "generated",
        "simulation",
        "composite",
        "still_motion",
    ]


def test_schema_v2_accepts_empty_legacy_shots_and_requires_sequence_coverage():
    plan = ProductionPlan.model_validate(make_v2_plan_payload("0" * 64))
    assert plan.visual_sequences[0].visual_beat_ids == ["B01"]
    broken = make_v2_plan_payload("0" * 64)
    broken["visual_sequences"][0]["scene_ids"] = []
    with pytest.raises(ValidationError):
        ProductionPlan.model_validate(broken)


def test_schema_v1_still_requires_nonempty_shots():
    payload = make_plan_payload("0" * 64)
    payload["scenes"][0]["shots"] = []
    with pytest.raises(ValidationError, match="schema version 1"):
        ProductionPlan.model_validate(payload)


def test_schema_v2_uses_sequences_instead_of_legacy_shots(run_with_plan):
    run_dir, script, _ = run_with_plan
    plan = ProductionPlan.model_validate(
        make_v2_plan_payload(script_sha256(run_dir / "script.json"))
    )

    assert validate_plan_against_script(plan, script, run_dir / "script.json", run_dir) == []


@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    [
        (
            lambda payload: payload["visual_sequences"].append(
                copy.deepcopy(payload["visual_sequences"][0])
            ),
            "duplicate_sequence_id",
        ),
        (
            lambda payload: payload["visual_beats"].append(
                copy.deepcopy(payload["visual_beats"][0])
            ),
            "duplicate_beat_id",
        ),
        (
            lambda payload: payload["visual_sequences"][0].update({"scene_ids": [2]}),
            "sequence_scene_coverage_mismatch",
        ),
        (
            lambda payload: payload["visual_sequences"][0].update({"scene_ids": [1, 3]}),
            "nonconsecutive_sequence_scenes",
        ),
        (
            lambda payload: payload["visual_sequences"][0].update(
                {"visual_beat_ids": ["B99"]}
            ),
            "beat_sequence_membership_mismatch",
        ),
        (
            lambda payload: payload["visual_beats"][0].update({"scene_id": 2}),
            "beat_scene_ownership_mismatch",
        ),
    ],
)
def test_schema_v2_validates_sequence_and_beat_coverage(
    run_with_plan, mutate, expected_code
):
    run_dir, script, _ = run_with_plan
    payload = make_v2_plan_payload(script_sha256(run_dir / "script.json"))
    mutate(payload)
    plan = ProductionPlan.model_validate(payload)

    issues = validate_plan_against_script(plan, script, run_dir / "script.json", run_dir)

    assert expected_code in {issue.code for issue in issues}


def test_production_defaults_accept_dip_to_black_scene_transition(run_with_plan):
    _, _, payload = run_with_plan
    payload["defaults"]["scene_transition"] = {
        "mode": "dip_to_black",
        "duration_seconds": 0.24,
        "fade_seconds": 0.1,
    }

    plan = ProductionPlan.model_validate(payload)

    assert plan.defaults.scene_transition.mode == "dip_to_black"
    assert plan.defaults.scene_transition.duration_seconds == 0.24
    assert plan.defaults.scene_transition.fade_seconds == 0.1


def test_production_defaults_leave_a_longer_pause_between_scenes(run_with_plan):
    _, _, payload = run_with_plan

    plan = ProductionPlan.model_validate(payload)

    assert plan.defaults.scene_transition.mode == "dip_to_black"
    assert plan.defaults.scene_transition.duration_seconds == 0.65
    assert plan.defaults.scene_transition.fade_seconds == 0.15


def test_dip_to_black_rejects_overlapping_fades(run_with_plan):
    _, _, payload = run_with_plan
    payload["defaults"]["scene_transition"] = {
        "mode": "dip_to_black",
        "duration_seconds": 0.24,
        "fade_seconds": 0.13,
    }

    with pytest.raises(ValidationError, match="fade_seconds"):
        ProductionPlan.model_validate(payload)


def test_generated_shot_rejects_a_secondary_event_field(run_with_plan):
    _, _, payload = run_with_plan
    payload["scenes"][0]["shots"][0]["motion_contract"]["secondary_event"] = "collapse"
    with pytest.raises(ValidationError):
        ProductionPlan.model_validate(payload)


def test_exact_relationship_rejects_generated_owner(run_with_plan):
    _, _, payload = run_with_plan
    payload["scenes"][0]["shots"][0]["relationships"] = [
        {
            "relationship_id": "earth_mars_sightline",
            "type": "attached_line",
            "owner": "generated_model",
            "entity_ids": ["earth", "mars"],
        }
    ]
    with pytest.raises(ValidationError, match="exact relationship"):
        ProductionPlan.model_validate(payload)


def test_i2v_requires_a_start_image(run_with_plan):
    _, _, payload = run_with_plan
    del payload["scenes"][0]["shots"][0]["assets"]["start_image"]
    with pytest.raises(ValidationError, match="start_image"):
        ProductionPlan.model_validate(payload)


def test_excluded_elements_reject_negative_commands(run_with_plan):
    _, _, payload = run_with_plan
    payload["scenes"][0]["shots"][0]["excluded_elements"] = ["do not add text"]
    with pytest.raises(ValidationError, match="noun phrases"):
        ProductionPlan.model_validate(payload)


def test_plan_requires_exact_scene_coverage_and_frame_accurate_duration(run_with_plan):
    run_dir, script, payload = run_with_plan
    payload["scenes"][0]["shots"][0]["duration_seconds"] -= 0.2
    payload["scenes"][0]["shots"][0]["end_state"]["at_seconds"] -= 0.2
    plan = ProductionPlan.model_validate(payload)
    issues = validate_plan_against_script(plan, script, run_dir / "script.json", run_dir)
    assert "shot_duration_sum" in {issue.code for issue in issues}


def test_plan_rejects_future_shot_dependency(run_with_plan):
    run_dir, script, payload = run_with_plan
    payload["scenes"][0]["shots"][0]["dependencies"] = [
        {"shot_id": "01D", "artifact": "final_frame"}
    ]
    plan = ProductionPlan.model_validate(payload)
    issues = validate_plan_against_script(plan, script, run_dir / "script.json", run_dir)
    assert "invalid_shot_dependency" in {issue.code for issue in issues}


def test_plan_requires_shot_frame_counts_to_equal_scene_frames(run_with_plan):
    run_dir, script, payload = run_with_plan
    durations = [1.99, 1.99, 1.99, 2.03]
    for shot, duration in zip(payload["scenes"][0]["shots"], durations, strict=True):
        shot["duration_seconds"] = duration
        shot["end_state"]["at_seconds"] = duration
    payload["scenes"][0]["shots"][2]["overlays"][0]["keyframes"][-1][
        "at_seconds"
    ] = 1.99
    payload["scenes"][0]["shots"][3]["still_motion"]["camera_keyframes"][-1][
        "at_seconds"
    ] = 2.03
    plan = ProductionPlan.model_validate(payload)
    issues = validate_plan_against_script(plan, script, run_dir / "script.json", run_dir)
    assert "shot_frame_sum" in {issue.code for issue in issues}


def test_plan_rejects_missing_authoring_asset_but_allows_missing_inbox_clip(run_with_plan):
    run_dir, script, payload = run_with_plan
    (run_dir / "shotAssets/starts/01A.png").unlink()
    plan = ProductionPlan.model_validate(payload)
    issues = validate_plan_against_script(plan, script, run_dir / "script.json", run_dir)
    assert "missing_asset" in {issue.code for issue in issues}
    assert not any("inbox" in issue.message for issue in issues)


def test_schema_and_pydantic_accept_the_same_plan(run_with_plan, tmp_path: Path):
    _, _, payload = run_with_plan
    schema_path = tmp_path / "production-plan.schema.json"
    write_production_schema(schema_path)
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert list(Draft202012Validator(schema).iter_errors(payload)) == []

    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    assert load_production_plan(plan_path).schema_version == 1


def test_schema_enforces_versioned_plan_contract(run_with_plan, tmp_path: Path):
    run_dir, _, payload = run_with_plan
    schema_path = tmp_path / "production-plan.schema.json"
    write_production_schema(schema_path)
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    missing_shots = copy.deepcopy(payload)
    del missing_shots["scenes"][0]["shots"]
    assert list(Draft202012Validator(schema).iter_errors(missing_shots))

    payload["scenes"][0]["shots"] = []
    assert list(Draft202012Validator(schema).iter_errors(payload))

    v2_payload = make_v2_plan_payload(script_sha256(run_dir / "script.json"))
    v2_payload.pop("visual_sequences")
    assert list(Draft202012Validator(schema).iter_errors(v2_payload))


def test_shot_filename_uses_stable_id_and_sanitized_title():
    assert shot_filename("06A", "지구의 추월", ".mp4") == "06A_지구의_추월.mp4"


def test_script_hash_changes_with_exact_file_bytes(tmp_path: Path):
    path = tmp_path / "script.json"
    path.write_bytes(b"{}")
    first = script_sha256(path)
    path.write_bytes(b"{}\n")
    assert script_sha256(path) != first


def test_manifest_rejects_extra_top_level_fields(run_with_plan):
    _, _, payload = run_with_plan
    bad = copy.deepcopy(payload)
    bad["unexpected"] = True
    with pytest.raises(ValidationError):
        ProductionPlan.model_validate(bad)
