from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from video_harness.models import ScriptArtifact
from video_harness.production import script_sha256
from video_harness.production_models import (
    CompositeShot,
    GeneratedShot,
    ProductionPlan,
    StyleBible,
)
from video_harness.prompt_compiler import (
    PromptArtifactManifest,
    compile_prompt,
    expected_prompt_path,
    write_compiled_artifacts,
)
from video_harness.sequence_models import LocalSequencePlan, OnlinePlan
from video_harness.sequence_prompt_compiler import compile_online_prompt
from video_harness.tests.test_production_models import make_plan_payload, make_script
from video_harness.tests.test_sequence_plans import _local, _online, _production, _script
from video_harness.variants import VariantPlan


def make_prompt_inputs(tmp_path: Path) -> tuple[dict, ProductionPlan, ScriptArtifact]:
    script = make_script()
    script_path = tmp_path / "script.json"
    script_path.write_text(script.model_dump_json(indent=2) + "\n", encoding="utf-8")
    payload = make_plan_payload(script_sha256(script_path))
    plan = ProductionPlan.model_validate(payload)
    return payload, plan, script


def generated_for_mode(payload: dict, mode: str) -> GeneratedShot:
    shot = copy.deepcopy(payload["scenes"][0]["shots"][0])
    shot["generation"]["mode"] = mode
    if mode == "t2v":
        shot["assets"] = {}
    if mode == "first_last":
        shot["assets"]["end_image"] = "shotAssets/ends/01A.png"
    return GeneratedShot.model_validate(shot)


@pytest.fixture
def v2_inputs(tmp_path: Path) -> tuple[
    Path,
    ProductionPlan,
    LocalSequencePlan,
    OnlinePlan,
    ScriptArtifact,
]:
    script = _script()
    script_path = tmp_path / "script.json"
    script_path.write_text(script.model_dump_json(indent=2) + "\n", encoding="utf-8")
    production = _production(script_sha256(script_path))
    production_path = tmp_path / "production-plan.json"
    production_path.write_text(
        production.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    production_hash = script_sha256(production_path)
    return (
        tmp_path,
        production,
        _local(production.script_sha256, production_hash),
        _online(production.script_sha256, production_hash),
        script,
    )


def test_t2v_prompt_contains_composition_event_and_positive_invariants(tmp_path: Path):
    payload, plan, _ = make_prompt_inputs(tmp_path)
    shot = generated_for_mode(payload, "t2v")
    text = compile_prompt(shot, plan.style_bible)
    assert "Mode: t2v" in text
    assert "Composition:" in text
    assert "Primary visual event:" in text
    assert "Keep unchanged:" in text
    assert "Excluded elements:" in text


def test_i2v_prompt_does_not_redescribe_reference_appearance(tmp_path: Path):
    payload, plan, _ = make_prompt_inputs(tmp_path)
    shot = generated_for_mode(payload, "i2v")
    text = compile_prompt(shot, plan.style_bible)
    assert "Use the supplied start frame as the exact appearance reference." in text
    assert "Appearance description:" not in text


def test_first_last_prompt_describes_only_transition(tmp_path: Path):
    payload, plan, _ = make_prompt_inputs(tmp_path)
    shot = generated_for_mode(payload, "first_last")
    text = compile_prompt(shot, plan.style_bible)
    assert "Preserve both supplied boundary frames." in text
    assert "Transition:" in text
    assert "Composition:" not in text


def test_non_generated_shot_has_no_prompt(tmp_path: Path):
    _, plan, _ = make_prompt_inputs(tmp_path)
    assert expected_prompt_path(plan.scenes[0].shots[1]) is None
    assert expected_prompt_path(plan.scenes[0].shots[3]) is None


def test_composite_compiles_only_the_generated_base(tmp_path: Path):
    _, plan, _ = make_prompt_inputs(tmp_path)
    shot = plan.scenes[0].shots[2]
    assert isinstance(shot, CompositeShot)
    text = compile_prompt(shot, plan.style_bible)
    assert "Overlay-safe composition:" in text
    assert "sightline_overlay" not in text
    assert expected_prompt_path(shot) == "videoPrompt/01C_합성.txt"


def test_prompt_rejects_multiple_primary_events(tmp_path: Path):
    payload, plan, _ = make_prompt_inputs(tmp_path)
    shot = generated_for_mode(payload, "t2v")
    shot.motion_contract.primary_event = "worker walks; wall collapses"
    with pytest.raises(ValueError, match="one primary event"):
        compile_prompt(shot, plan.style_bible)


def test_write_compiled_artifacts_writes_only_expected_prompts(tmp_path: Path):
    payload, plan, script = make_prompt_inputs(tmp_path)
    for relative in (
        "shotAssets/starts/01A.png",
        "shotAssets/backgrounds/01D.png",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
    paths = write_compiled_artifacts(tmp_path, plan, script)
    assert "video-plan.md" in paths.generated
    prompt_paths = sorted((tmp_path / "videoPrompt").glob("*.txt"))
    assert [path.name for path in prompt_paths] == ["01A_생성.txt", "01C_합성.txt"]
    review_prompt_dir = tmp_path / "videoFiles/prompts/01_혼합_장면"
    review_prompt_paths = sorted(review_prompt_dir.glob("*.txt"))
    assert [path.name for path in review_prompt_paths] == [
        "01A_생성.txt",
        "01C_합성.txt",
    ]
    for canonical in prompt_paths:
        mirror = review_prompt_dir / canonical.name
        assert mirror.read_bytes() == canonical.read_bytes()


def test_write_compiled_artifacts_includes_alternate_generated_prompts(tmp_path: Path):
    payload, plan, script = make_prompt_inputs(tmp_path)
    alternate = copy.deepcopy(payload["scenes"][0]["shots"][0])
    alternate["shot_id"] = "01E"
    alternate["title"] = "생성 대안"
    alternate["generation"]["prompt_file"] = "videoPrompt/01E_생성_대안.txt"
    alternate["generation"]["inbox_file"] = "shotFiles/inbox/01E_생성_대안.mp4"
    base_timeline = ["01A", "01B", "01C", "01D"]
    variant_timeline = ["01E", "01B", "01C", "01D"]
    variant_plan = VariantPlan.model_validate(
        {
            "schema_version": 1,
            "production_plan_sha256": "0" * 64,
            "script_sha256": "0" * 64,
            "alternate_shots": [{"scene_id": 1, "shot": alternate}],
            "variants": [
                {"variant_id": "balanced", "label": "Balanced", "scenes": [{"scene_id": 1, "shot_ids": base_timeline}]},
                {"variant_id": "explain", "label": "Explain", "scenes": [{"scene_id": 1, "shot_ids": variant_timeline}]},
                {"variant_id": "dynamic", "label": "Dynamic", "scenes": [{"scene_id": 1, "shot_ids": base_timeline}]},
                {"variant_id": "cinematic", "label": "Cinematic", "scenes": [{"scene_id": 1, "shot_ids": variant_timeline}]},
            ],
        }
    )

    write_compiled_artifacts(tmp_path, plan, script, variant_plan=variant_plan)

    canonical = tmp_path / "videoPrompt/01E_생성_대안.txt"
    mirror = tmp_path / "videoFiles/prompts/01_혼합_장면/01E_생성_대안.txt"
    assert canonical.is_file()
    assert mirror.read_bytes() == canonical.read_bytes()


def test_v2_compiler_writes_local_and_every_online_prompt_without_legacy_root(
    v2_inputs,
):
    run_dir, production, local, online, script = v2_inputs

    written = write_compiled_artifacts(
        run_dir,
        production,
        script,
        local_plan=local,
        online_plan=online,
    )

    assert isinstance(written, PromptArtifactManifest)
    assert "videoFiles/prompts/local/SEQ01.md" in written.generated
    for shot in online.shots:
        assert shot.prompt_file in written.generated
        assert shot.metadata_file in written.generated
    assert written.planned_references == [
        shot.reference_video_file
        for shot in online.shots
        if shot.reference_video_file is not None
    ]
    assert (run_dir / "videoFiles/prompts/local/SEQ01.md").is_file()
    assert not (run_dir / "videoPrompt").exists()


def test_prompt_manifest_preserves_legacy_path_membership_and_iteration(v2_inputs):
    run_dir, production, local, online, script = v2_inputs

    written = write_compiled_artifacts(
        run_dir,
        production,
        script,
        local_plan=local,
        online_plan=online,
    )

    expected = run_dir / "video-plan.md"
    assert expected in written
    assert expected in list(written)


def test_v2_metadata_retains_complete_online_shot_and_plan_hashes(v2_inputs):
    run_dir, production, local, online, script = v2_inputs

    write_compiled_artifacts(
        run_dir,
        production,
        script,
        local_plan=local,
        online_plan=online,
    )

    shot = online.shots[0]
    metadata = json.loads((run_dir / shot.metadata_file).read_text(encoding="utf-8"))
    assert metadata == {
        **shot.model_dump(mode="json"),
        "script_sha256": online.script_sha256,
        "production_plan_sha256": online.production_plan_sha256,
    }


def test_v2_review_lists_common_local_and_online_plan_facts(v2_inputs):
    run_dir, production, local, online, script = v2_inputs

    write_compiled_artifacts(
        run_dir,
        production,
        script,
        local_plan=local,
        online_plan=online,
    )

    review = (run_dir / "video-plan.md").read_text(encoding="utf-8")
    for literal in (
        "SEQ01",
        "B01",
        "grow-orbit",
        "ON-B01",
        "v2v",
        "videoFiles/onlineReferences/ON-B01.mp4",
    ):
        assert literal in review


def test_v2_review_opens_with_a_scene_by_scene_visual_generation_script(v2_inputs):
    run_dir, production, local, online, script = v2_inputs

    write_compiled_artifacts(
        run_dir,
        production,
        script,
        local_plan=local,
        online_plan=online,
    )

    review = (run_dir / "video-plan.md").read_text(encoding="utf-8")
    scene_one = review.index("## Scene 01 — 궤도")
    scene_two = review.index("## Scene 02 — 시선")
    technical_appendix = review.index("## Technical Appendix")
    assert scene_one < scene_two < technical_appendix
    for literal in (
        "Narration: 첫 장면은 궤도 관계를 보여줍니다.",
        "### Shot 1 — B01",
        "Sequence time: 0.00s–4.00s (4.00s)",
        "Visual direction: 궤도 관계를 만든다",
        "Framing: controller grow-orbit; patch targets [\"geometry\",\"camera\"]",
        "Camera movement: controller grow-orbit owns the camera change",
        "Online alternative: ON-B01 (v2v, local_reference)",
        "Science invariants: [\"궤도 관계가 정확하다\"]",
    ):
        assert literal in review


def test_v2_v2v_prompt_locks_science_motion(v2_inputs):
    _, production, _, online, _ = v2_inputs

    text = compile_online_prompt(online.shots[0], production)

    assert "Preserve the reference video's exact positions" in text
    assert "Do not alter direction, speed, occlusion, projection, or camera timing" in text
    assert "Allowed visual changes:" in text


def test_v2_dispatch_requires_both_execution_plans(v2_inputs):
    run_dir, production, local, _, script = v2_inputs

    with pytest.raises(ValueError, match="requires local and online plans"):
        write_compiled_artifacts(run_dir, production, script, local_plan=local)

    assert not (run_dir / "video-plan.md").exists()
    assert not (run_dir / "videoPrompt").exists()


def test_v2_rejects_prompt_metadata_equality_without_partial_writes(v2_inputs):
    run_dir, production, local, online, script = v2_inputs
    online.shots[0].metadata_file = online.shots[0].prompt_file
    review_path = run_dir / "video-plan.md"
    review_path.write_text("existing review\n", encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate artifact destination"):
        write_compiled_artifacts(
            run_dir,
            production,
            script,
            local_plan=local,
            online_plan=online,
        )

    assert review_path.read_text(encoding="utf-8") == "existing review\n"
    assert not (run_dir / "videoFiles/prompts/local/SEQ01.md").exists()
    assert not (run_dir / online.shots[0].prompt_file).exists()
    assert not (run_dir / online.shots[1].prompt_file).exists()


def test_v2_rejects_cross_shot_destination_collision_without_writes(v2_inputs):
    run_dir, production, local, online, script = v2_inputs
    online.shots[1].prompt_file = online.shots[0].metadata_file

    with pytest.raises(ValueError, match="duplicate artifact destination"):
        write_compiled_artifacts(
            run_dir,
            production,
            script,
            local_plan=local,
            online_plan=online,
        )

    assert not (run_dir / "video-plan.md").exists()
    assert not (run_dir / "videoFiles/prompts/local/SEQ01.md").exists()
    for shot in online.shots:
        assert not (run_dir / shot.prompt_file).exists()
        assert not (run_dir / shot.metadata_file).exists()


def test_v2_rejects_symlink_escape_before_changing_any_artifact(v2_inputs):
    run_dir, production, local, online, script = v2_inputs
    outside = run_dir.parent / "outside-prompts"
    outside.mkdir()
    online_root = run_dir / "videoFiles/prompts/online"
    online_root.parent.mkdir(parents=True)
    online_root.symlink_to(outside, target_is_directory=True)
    review_path = run_dir / "video-plan.md"
    review_path.write_text("existing review\n", encoding="utf-8")

    with pytest.raises(ValueError, match="escapes run directory"):
        write_compiled_artifacts(
            run_dir,
            production,
            script,
            local_plan=local,
            online_plan=online,
        )

    assert review_path.read_text(encoding="utf-8") == "existing review\n"
    assert not (run_dir / "videoFiles/prompts/local/SEQ01.md").exists()
    assert list(outside.rglob("*")) == []


def test_exclusions_are_deduplicated_in_stable_order(tmp_path: Path):
    payload, plan, _ = make_prompt_inputs(tmp_path)
    shot = generated_for_mode(payload, "t2v")
    style_payload = plan.style_bible.model_dump(mode="json")
    style_payload["excluded_elements"] = ["watermarks", "logos"]
    style = StyleBible.model_validate(style_payload)
    line = next(
        item for item in compile_prompt(shot, style).splitlines() if item.startswith("Excluded elements:")
    )
    assert line == "Excluded elements: watermarks, logos, subtitles"
