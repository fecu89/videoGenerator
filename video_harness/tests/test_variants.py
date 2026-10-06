from __future__ import annotations

import copy
import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest

from video_harness.production import script_sha256
from video_harness.production_models import ProductionPlan
from video_harness.tests.test_production_models import make_plan_payload, make_script
from video_harness.variants import (
    SequenceVariantPlan,
    VariantPlan,
    load_variant_plan,
    validate_sequence_variant_plan,
    validate_variant_plan,
    write_variant_schema,
)


def _variant_payload(run_dir: Path) -> tuple[ProductionPlan, dict]:
    script = make_script()
    script_path = run_dir / "script.json"
    script_path.write_text(script.model_dump_json(indent=2) + "\n", encoding="utf-8")
    production = ProductionPlan.model_validate(make_plan_payload(script_sha256(script_path)))
    production_path = run_dir / "production-plan.json"
    production_path.write_text(production.model_dump_json(indent=2) + "\n", encoding="utf-8")

    base = production.model_dump(mode="json")["scenes"][0]["shots"]
    explain = copy.deepcopy(base[1])
    explain["shot_id"] = "01E"
    explain["title"] = "설명 대안"
    dynamic = copy.deepcopy(base[3])
    dynamic["shot_id"] = "01F"
    dynamic["title"] = "동적 대안"
    dynamic["dependencies"] = []

    payload = {
        "schema_version": 1,
        "production_plan_sha256": script_sha256(production_path),
        "script_sha256": script_sha256(script_path),
        "budget": {
            "max_alternate_shots": 5,
            "max_extra_duration_ratio": 0.5,
            "max_generated_alternates": 3,
            "deterministic_workers": 2,
        },
        "alternate_shots": [
            {"scene_id": 1, "shot": explain},
            {"scene_id": 1, "shot": dynamic},
        ],
        "variants": [
            {
                "variant_id": "balanced",
                "label": "Balanced",
                "scenes": [{"scene_id": 1, "shot_ids": ["01A", "01B", "01C", "01D"]}],
            },
            {
                "variant_id": "explain",
                "label": "Explain",
                "scenes": [{"scene_id": 1, "shot_ids": ["01A", "01E", "01C", "01D"]}],
            },
            {
                "variant_id": "dynamic",
                "label": "Dynamic",
                "scenes": [{"scene_id": 1, "shot_ids": ["01A", "01B", "01C", "01F"]}],
            },
            {
                "variant_id": "cinematic",
                "label": "Cinematic",
                "scenes": [{"scene_id": 1, "shot_ids": ["01A", "01E", "01C", "01F"]}],
            },
        ],
        "default_variant_id": "balanced",
    }
    return production, payload


def _issues(run_dir: Path, production: ProductionPlan, payload: dict) -> set[str]:
    plan = VariantPlan.model_validate(payload)
    return {
        issue.code
        for issue in validate_variant_plan(
            plan,
            production,
            run_dir / "production-plan.json",
            run_dir / "script.json",
        )
    }


def test_valid_variant_plan_has_four_distinct_recipes_within_budget(tmp_path: Path):
    production, payload = _variant_payload(tmp_path)

    assert _issues(tmp_path, production, payload) == set()


def test_variant_plan_rejects_stale_hashes(tmp_path: Path):
    production, payload = _variant_payload(tmp_path)
    payload["production_plan_sha256"] = "0" * 64
    payload["script_sha256"] = "1" * 64

    assert _issues(tmp_path, production, payload) == {
        "variant_production_hash_mismatch",
        "variant_script_hash_mismatch",
    }


def test_variant_plan_rejects_duplicate_recipe_timeline(tmp_path: Path):
    production, payload = _variant_payload(tmp_path)
    payload["variants"][3]["scenes"] = copy.deepcopy(payload["variants"][1]["scenes"])

    assert "duplicate_variant_timeline" in _issues(tmp_path, production, payload)


def test_variant_plan_rejects_unknown_shot_and_wrong_scene_frames(tmp_path: Path):
    production, payload = _variant_payload(tmp_path)
    payload["variants"][1]["scenes"][0]["shot_ids"] = ["01A", "01E", "99Z"]

    issues = _issues(tmp_path, production, payload)

    assert "unknown_variant_shot" in issues
    assert "variant_scene_frame_sum" in issues


def test_variant_plan_requires_balanced_recipe_to_match_base(tmp_path: Path):
    production, payload = _variant_payload(tmp_path)
    payload["variants"][0]["scenes"][0]["shot_ids"] = ["01A", "01E", "01C", "01D"]

    assert "balanced_timeline_mismatch" in _issues(tmp_path, production, payload)


def test_variant_plan_rejects_default_budget_overflow(tmp_path: Path):
    production, payload = _variant_payload(tmp_path)
    third = copy.deepcopy(payload["alternate_shots"][0])
    third["shot"]["shot_id"] = "01G"
    third["shot"]["title"] = "예산 초과"
    payload["alternate_shots"].append(third)

    assert "alternate_duration_budget_exceeded" in _issues(tmp_path, production, payload)


def test_variant_schema_and_pydantic_accept_the_same_payload(tmp_path: Path):
    _, payload = _variant_payload(tmp_path)
    schema_path = tmp_path / "variant-plan.schema.json"
    write_variant_schema(schema_path)
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    assert list(Draft202012Validator(schema).iter_errors(payload)) == []

    plan_path = tmp_path / "variant-plan.json"
    plan_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    assert load_variant_plan(plan_path).default_variant_id == "balanced"


def _sequence_variant_payload(
    run_dir: Path,
    production: ProductionPlan,
) -> dict:
    local_path = run_dir / "local-sequence-plan.json"
    local_payload = {
        "schema_version": 1,
        "script_sha256": script_sha256(run_dir / "script.json"),
        "production_plan_sha256": script_sha256(run_dir / "production-plan.json"),
        "defaults": {"width": 1920, "height": 1080, "fps": 30},
        "simulation_config_file": "simulation.json",
        "sequences": [
            {
                "sequence_id": "SEQ01",
                "scene_ids": [1],
                "duration_frames": 360,
                "render_mode": "simulation",
                "scene_graph": "shared-science-scene",
                "scene_spans": [
                    {
                        "scene_id": 1,
                        "start_frame": 0,
                        "end_frame": 360,
                        "audio_start_frame": 0,
                        "audio_end_frame": 360,
                        "tail_silence_frames": 0,
                    }
                ],
                "timeline": [
                    {
                        "beat_id": "B01",
                        "start_frame": 0,
                        "end_frame": 360,
                        "simulation_time_start": 0.0,
                        "simulation_time_end": 1.0,
                        "controller": "show-same-direction-arrows",
                        "patch_targets": ["geometry", "layers"],
                    }
                ],
            }
        ],
    }
    local_path.write_text(json.dumps(local_payload), encoding="utf-8")
    return {
        "schema_version": 2,
        "production_plan_sha256": script_sha256(run_dir / "production-plan.json"),
        "local_sequence_plan_sha256": script_sha256(local_path),
        "script_sha256": script_sha256(run_dir / "script.json"),
        "variants": [
            {
                "variant_id": "balanced",
                "label": "Balanced",
                "sequence_ids": ["SEQ01"],
            },
            {
                "variant_id": "explain",
                "label": "Explain",
                "sequence_ids": ["SEQ01"],
                "overrides": [
                    {
                        "sequence_id": "SEQ01",
                        "layer_timing_profile": "explain",
                        "lighting_profile": "clear",
                    }
                ],
            },
            {
                "variant_id": "dynamic",
                "label": "Dynamic",
                "sequence_ids": ["SEQ01"],
                "overrides": [
                    {
                        "sequence_id": "SEQ01",
                        "camera_profile": "close",
                        "layer_timing_profile": "dynamic",
                        "scale_profile": "emphasis",
                    }
                ],
            },
            {
                "variant_id": "cinematic",
                "label": "Cinematic",
                "sequence_ids": ["SEQ01"],
                "overrides": [
                    {
                        "sequence_id": "SEQ01",
                        "camera_profile": "restrained",
                        "lighting_profile": "cinematic",
                    }
                ],
            },
        ],
    }


def test_v2_loader_and_schema_preserve_the_discriminated_v1_contract(tmp_path: Path):
    production, v1_payload = _variant_payload(tmp_path)
    v2_payload = _sequence_variant_payload(tmp_path, production)
    schema_path = tmp_path / "variant-plan.schema.json"
    write_variant_schema(schema_path)
    validator = Draft202012Validator(
        json.loads(schema_path.read_text(encoding="utf-8"))
    )

    assert list(validator.iter_errors(v1_payload)) == []
    assert list(validator.iter_errors(v2_payload)) == []
    assert list(validator.iter_errors({**v2_payload, "schema_version": 3}))

    plan_path = tmp_path / "variant-plan.json"
    plan_path.write_text(json.dumps(v2_payload), encoding="utf-8")
    assert isinstance(load_variant_plan(plan_path), SequenceVariantPlan)


def test_v2_variants_keep_exact_sequence_order_and_plan_hashes(tmp_path: Path):
    production, _ = _variant_payload(tmp_path)
    payload = _sequence_variant_payload(tmp_path, production)
    plan = SequenceVariantPlan.model_validate(payload)
    from video_harness.sequence_plans import load_local_sequence_plan

    local = load_local_sequence_plan(tmp_path / "local-sequence-plan.json")

    assert validate_sequence_variant_plan(
        plan,
        production,
        local,
        production_path=tmp_path / "production-plan.json",
        local_path=tmp_path / "local-sequence-plan.json",
        script_path=tmp_path / "script.json",
    ) == []
    assert [recipe.variant_id for recipe in plan.variants] == [
        "balanced",
        "explain",
        "dynamic",
        "cinematic",
    ]


def test_v2_validation_rejects_reordered_sequences_and_stale_hashes(tmp_path: Path):
    production, _ = _variant_payload(tmp_path)
    payload = _sequence_variant_payload(tmp_path, production)
    payload["local_sequence_plan_sha256"] = "0" * 64
    payload["variants"][1]["sequence_ids"] = ["SEQ99"]
    plan = SequenceVariantPlan.model_validate(payload)
    from video_harness.sequence_plans import load_local_sequence_plan

    issues = validate_sequence_variant_plan(
        plan,
        production,
        load_local_sequence_plan(tmp_path / "local-sequence-plan.json"),
        production_path=tmp_path / "production-plan.json",
        local_path=tmp_path / "local-sequence-plan.json",
        script_path=tmp_path / "script.json",
    )

    assert {issue.code for issue in issues} == {
        "variant_local_sequence_hash_mismatch",
        "variant_sequence_order_mismatch",
    }


def test_v2_override_model_forbids_physics_and_timeline_fields(tmp_path: Path):
    production, _ = _variant_payload(tmp_path)
    payload = _sequence_variant_payload(tmp_path, production)
    payload["variants"][1]["overrides"][0]["simulation_time_start"] = 10

    with pytest.raises(ValueError, match="simulation_time_start"):
        SequenceVariantPlan.model_validate(payload)


@pytest.mark.parametrize("override", [None, {"sequence_id": "SEQ01"}])
def test_v2_model_requires_an_effective_non_base_override(
    tmp_path: Path,
    override: dict | None,
):
    production, _ = _variant_payload(tmp_path)
    payload = _sequence_variant_payload(tmp_path, production)
    payload["variants"][1]["overrides"] = [] if override is None else [override]

    with pytest.raises(ValueError, match="effective non-base override"):
        SequenceVariantPlan.model_validate(payload)


def test_v2_model_rejects_duplicate_normalized_presentation_recipes(tmp_path: Path):
    production, _ = _variant_payload(tmp_path)
    payload = _sequence_variant_payload(tmp_path, production)
    payload["variants"][3]["overrides"] = copy.deepcopy(
        payload["variants"][1]["overrides"]
    )

    with pytest.raises(ValueError, match="duplicate presentation fingerprint"):
        SequenceVariantPlan.model_validate(payload)


def test_v2_model_rejects_non_base_balanced_override(tmp_path: Path):
    production, _ = _variant_payload(tmp_path)
    payload = _sequence_variant_payload(tmp_path, production)
    payload["variants"][0]["overrides"] = [
        {"sequence_id": "SEQ01", "camera_profile": "wide"}
    ]

    with pytest.raises(ValueError, match="balanced recipe"):
        SequenceVariantPlan.model_validate(payload)


def test_v2_schema_remains_structural_while_semantic_model_rejects_base_duplicate(
    tmp_path: Path,
):
    production, _ = _variant_payload(tmp_path)
    payload = _sequence_variant_payload(tmp_path, production)
    payload["variants"][1]["overrides"] = [{"sequence_id": "SEQ01"}]
    schema_path = tmp_path / "variant-plan.schema.json"
    write_variant_schema(schema_path)
    validator = Draft202012Validator(
        json.loads(schema_path.read_text(encoding="utf-8"))
    )

    assert list(validator.iter_errors(payload)) == []
    with pytest.raises(ValueError, match="effective non-base override"):
        SequenceVariantPlan.model_validate(payload)
