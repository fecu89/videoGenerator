from __future__ import annotations

from pathlib import Path

from video_harness.production import script_sha256
from video_harness.production_models import ProductionPlan
from video_harness.production_review import render_video_plan
from video_harness.tests.test_production_models import make_plan_payload, make_script


def make_review_inputs(tmp_path: Path):
    script = make_script()
    script_path = tmp_path / "script.json"
    script_path.write_text(script.model_dump_json(indent=2) + "\n", encoding="utf-8")
    plan = ProductionPlan.model_validate(make_plan_payload(script_sha256(script_path)))
    return plan, script


def test_review_lists_shots_and_modes_in_manifest_order(tmp_path: Path):
    plan, script = make_review_inputs(tmp_path)
    text = render_video_plan(plan, script)
    assert text.index("### SHOT 01A") < text.index("### SHOT 01B")
    assert text.index("### SHOT 01B") < text.index("### SHOT 01C")
    assert "Render mode: simulation" in text
    assert "Relationship owner: deterministic_overlay" in text
    assert "Expected output: shotFiles/01B_시뮬레이션.mp4" in text


def test_review_does_not_copy_narration_into_visual_contract(tmp_path: Path):
    plan, script = make_review_inputs(tmp_path)
    text = render_video_plan(plan, script)
    assert script.scenes[0].narration not in text


def test_review_is_byte_stable(tmp_path: Path):
    plan, script = make_review_inputs(tmp_path)
    assert render_video_plan(plan, script) == render_video_plan(plan, script)


def test_review_contains_machine_owned_contract_fields(tmp_path: Path):
    plan, script = make_review_inputs(tmp_path)
    text = render_video_plan(plan, script)
    for label in (
        "Purpose:",
        "Primary visual event:",
        "Coordinate space:",
        "Start state:",
        "End state:",
        "Camera:",
        "Invariants:",
        "Assets:",
        "Excluded elements:",
    ):
        assert label in text


def test_review_exposes_scene_transition_contract(tmp_path: Path):
    plan, script = make_review_inputs(tmp_path)

    text = render_video_plan(plan, script)

    assert (
        'Scene transition: {"duration_seconds":0.65,"fade_seconds":0.15,'
        '"mode":"dip_to_black"}'
    ) in text


def test_sequence_review_lists_declared_labels_per_beat(tmp_path: Path):
    from video_harness.production_review import render_sequence_video_plan
    from video_harness.tests.test_sequence_plans import _local, _online, _production, _script
    script = _script()
    script_path = tmp_path / "script.json"
    script_path.write_text(script.model_dump_json(indent=2) + "\n", encoding="utf-8")
    production = _production(script_sha256(script_path))
    production_path = tmp_path / "production-plan.json"
    production_path.write_text(production.model_dump_json(indent=2) + "\n", encoding="utf-8")
    production_hash = script_sha256(production_path)
    local = _local(production.script_sha256, production_hash)
    online = _online(production.script_sha256, production_hash)
    beat = local.sequences[0].timeline[0]
    beat.controller_options = {**beat.controller_options, "labels": [{"text": "흑운모", "anchor": "biotite", "side": "top"}]}

    text = render_sequence_video_plan(production, local, online, script, text_policy="keywords")

    assert "On-screen labels: 흑운모 → biotite (top, glow)" in text
    assert "On-screen labels: 없음" in text or text.count("On-screen labels:") == 1
    # Legacy runs keep their byte-exact review so existing approvals stay valid.
    legacy = render_sequence_video_plan(production, local, online, script)
    assert "On-screen labels" not in legacy
