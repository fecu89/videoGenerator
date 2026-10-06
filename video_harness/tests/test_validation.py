from __future__ import annotations

from video_harness.settings import ArchivedV5HarnessSettings

import copy
import json
from pathlib import Path

import pytest

from video_harness.models import Scene, ScriptArtifact, SelectedTopic, StoryEngine
from video_harness.production import script_sha256
from video_harness.production_models import ProductionPlan
from video_harness.produce_local import LocalProductionReport
from video_harness.pipeline import PipelineArtifact, PipelineReport
from video_harness.prompt_compiler import write_compiled_artifacts
from video_harness.sequence_plans import validate_sequence_plans
from video_harness.sequence_qa import QaReport, SequenceQaResult
from video_harness.sequence_variants import SequenceVariantManifest, SequenceVariantOutput
from video_harness.settings import (
    HarnessSettings,
    LegacyHarnessSettings,
    settings_sha256,
    write_settings_snapshot,
)
from video_harness.storage import RunStore, scene_filename
from video_harness.tests.test_production_models import make_plan_payload, make_script as make_production_script
from video_harness.tests.test_sequence_plans import _local, _online, _production, _script
from video_harness.validation import validate_run
from video_harness.variants import SequenceVariantPlan, VariantPlan


def make_script(scene_count: int = 2, completed: bool = False) -> ScriptArtifact:
    scenes = []
    for scene_id in range(1, scene_count + 1):
        scene = Scene(
            scene_id=scene_id,
            title=f"장면 {scene_id}",
            narration=f"이것은 {scene_id}번 장면의 최종 나레이션입니다.",
            narrative_role="HOOK" if scene_id == 1 else "PAYOFF",
            visual_subject=f"대상 {scene_id}",
        )
        if completed:
            scene.duration_seconds = 6.42
            scene.audio_file = f"audioFiles/{scene_filename(scene, '.mp3')}"
            scene.video_prompt_file = f"videoPrompt/{scene_filename(scene, '.txt')}"
        scenes.append(scene)
    return ScriptArtifact(
        selected_topic=SelectedTopic(title="검증 주제", reason="검증용"),
        story_engine=StoryEngine(
            common_belief="상식",
            contradiction="충돌",
            obvious_answer="예상",
            constraint="제약",
            actual_answer="실제 답",
            mechanism="원리",
            payoff="결말",
        ),
        scenes=scenes,
    )


def prompt_text(scene: Scene) -> str:
    return (
        f"SCENE {scene.scene_id:02d} - {scene.title}\n"
        f"Duration: {scene.duration_seconds:.2f} seconds\n"
        "Intent: 구조의 원인과 결과를 보여준다.\n\n"
        "A standalone, physically accurate cinematic documentary shot.\n\n"
        "Negative constraints: no text, no logos, no impossible physics\n"
    )


def narration_text(scene: Scene) -> str:
    return (
        f"SCENE {scene.scene_id:02d} - {scene.title}\n"
        f"Narration: {scene.narration}\n"
    )


def review_text(script: ScriptArtifact) -> str:
    return "\n".join(
        f"## 씬 {scene.scene_id} — {scene.title.replace('_', ' ')}\n\n"
        f"> {scene.narration}\n"
        for scene in script.scenes
    )


def video_plan_text(script: ScriptArtifact) -> str:
    return "# Video Prompt Production Plan\n\n" + "\n".join(
        f"## SCENE {scene.scene_id:02d} - {scene.title}\n"
        f"Duration: {scene.duration_seconds:.2f} seconds\n"
        "Visual event: 하나의 시각적 사건\n"
        "Cause and effect: 원인과 결과\n"
        "Camera: 고정 카메라\n"
        "Continuity: 공통 다큐멘터리 스타일\n"
        "Negative constraints: no text\n"
        "Status: complete\n"
        for scene in script.scenes
    )


def create_matching_artifacts(store: RunStore, script: ScriptArtifact) -> None:
    for scene in script.scenes:
        (store.root / scene.audio_file).write_bytes(b"fake-mp3")
        (store.audio_dir / scene_filename(scene, ".txt")).write_text(
            narration_text(scene),
            encoding="utf-8",
        )
        store.write_text(
            scene.video_prompt_file,
            prompt_text(scene),
        )
    (store.root / "story-review.md").write_text(
        review_text(script),
        encoding="utf-8",
    )
    (store.root / "video-plan.md").write_text(
        video_plan_text(script),
        encoding="utf-8",
    )
    store.write_script(script)


def create_manifest_run(tmp_path: Path) -> tuple[RunStore, ScriptArtifact, ProductionPlan]:
    root = tmp_path / "manifest-run"
    root.mkdir()
    store = RunStore(root)
    store.audio_dir.mkdir()
    store.video_prompt_dir.mkdir()
    store.ensure_production_directories()

    script = make_production_script()
    store.write_script(script)
    payload = make_plan_payload(script_sha256(root / "script.json"))
    plan = ProductionPlan.model_validate(payload)
    store.write_model("production-plan.json", plan)

    for relative in (
        "shotAssets/starts/01A.png",
        "shotAssets/backgrounds/01D.png",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")

    scene = script.scenes[0]
    (store.audio_dir / scene_filename(scene, ".mp3")).write_bytes(b"fake-mp3")
    (store.audio_dir / scene_filename(scene, ".txt")).write_text(
        narration_text(scene),
        encoding="utf-8",
    )
    (root / "story-review.md").write_text(review_text(script), encoding="utf-8")
    write_compiled_artifacts(root, plan, script)
    return store, script, plan


def add_variant_plan(store: RunStore, plan: ProductionPlan) -> VariantPlan:
    shots = [shot.model_dump(mode="json") for shot in plan.scenes[0].shots]
    explain = copy.deepcopy(shots[1])
    explain["shot_id"] = "01E"
    explain["title"] = "설명 대안"
    dynamic = copy.deepcopy(shots[3])
    dynamic["shot_id"] = "01F"
    dynamic["title"] = "동적 대안"
    dynamic["dependencies"] = []
    variant_plan = VariantPlan.model_validate(
        {
            "schema_version": 1,
            "production_plan_sha256": script_sha256(store.root / "production-plan.json"),
            "script_sha256": script_sha256(store.root / "script.json"),
            "alternate_shots": [
                {"scene_id": 1, "shot": explain},
                {"scene_id": 1, "shot": dynamic},
            ],
            "variants": [
                {"variant_id": "balanced", "label": "Balanced", "scenes": [{"scene_id": 1, "shot_ids": ["01A", "01B", "01C", "01D"]}]},
                {"variant_id": "explain", "label": "Explain", "scenes": [{"scene_id": 1, "shot_ids": ["01A", "01E", "01C", "01D"]}]},
                {"variant_id": "dynamic", "label": "Dynamic", "scenes": [{"scene_id": 1, "shot_ids": ["01A", "01B", "01C", "01F"]}]},
                {"variant_id": "cinematic", "label": "Cinematic", "scenes": [{"scene_id": 1, "shot_ids": ["01A", "01E", "01C", "01F"]}]},
            ],
        }
    )
    store.write_model("variant-plan.json", variant_plan)
    return variant_plan


def test_validator_reports_missing_audio_and_prompt(tmp_path):
    store = RunStore.create(tmp_path, "누락 테스트", input_kind="topic")
    script = make_script(scene_count=1, completed=True)
    (store.root / "story-review.md").write_text(review_text(script), encoding="utf-8")
    (store.root / "video-plan.md").write_text(
        video_plan_text(script),
        encoding="utf-8",
    )
    store.write_script(script)

    issues = validate_run(store.root, duration_reader=lambda _: 6.0)

    assert {issue.code for issue in issues} == {
        "missing_audio",
        "missing_narration",
        "missing_prompt",
    }


def test_validator_accepts_complete_matching_run(tmp_path):
    store = RunStore.create(tmp_path, "완료 테스트", input_kind="topic")
    script = make_script(completed=True)
    create_matching_artifacts(store, script)

    issues = validate_run(store.root, duration_reader=lambda _: 6.42)

    assert issues == []


def test_validation_uses_run_snapshot_duration_contract(tmp_path):
    store = RunStore.create(tmp_path, "설정 길이 테스트", input_kind="topic")
    script = make_script(scene_count=1, completed=True)
    script.scenes[0].duration_seconds = 4.5
    create_matching_artifacts(store, script)
    write_settings_snapshot(
        store.root,
        HarnessSettings(voice={"min_scene_seconds": 4.0, "max_scene_seconds": 9.0}),
    )

    issues = validate_run(store.root, duration_reader=lambda _: 4.5)

    assert "invalid_duration" not in {issue.code for issue in issues}


def test_validation_accepts_existing_audio_with_schema_v1_voice_settings(tmp_path):
    store = RunStore.create(tmp_path, "legacy 설정 테스트", input_kind="topic")
    script = make_script(scene_count=1, completed=True)
    create_matching_artifacts(store, script)
    write_settings_snapshot(
        store.root,
        LegacyHarnessSettings(
            voice={
                "model": "gpt-4o-mini-tts",
                "voice": "coral",
                "instructions": "legacy",
                "min_scene_seconds": 5.5,
                "max_scene_seconds": 8.0,
                "workers": 2,
                "retry_attempts": 4,
                "retry_min_wait_seconds": 1.0,
                "retry_max_wait_seconds": 8.0,
            }
        ),
    )

    issues = validate_run(store.root, duration_reader=lambda _: 6.42)

    assert issues == []


def test_validation_uses_run_snapshot_metadata_tolerance(tmp_path):
    store = RunStore.create(tmp_path, "설정 허용오차 테스트", input_kind="topic")
    script = make_script(scene_count=1, completed=True)
    script.scenes[0].duration_seconds = 6.42
    create_matching_artifacts(store, script)
    write_settings_snapshot(
        store.root,
        HarnessSettings(qa={"duration_tolerance_seconds": 0.1}),
    )

    issues = validate_run(store.root, duration_reader=lambda _: 6.5)

    assert "duration_metadata_mismatch" not in {issue.code for issue in issues}


def test_validator_reports_extra_numbered_files(tmp_path):
    store = RunStore.create(tmp_path, "여분 테스트", input_kind="topic")
    script = make_script(completed=True)
    create_matching_artifacts(store, script)
    (store.audio_dir / "99_extra.mp3").write_bytes(b"extra")
    (store.audio_dir / "99_extra.txt").write_text("extra", encoding="utf-8")
    (store.video_prompt_dir / "99_extra.txt").write_text("extra", encoding="utf-8")

    issues = validate_run(store.root, duration_reader=lambda _: 6.42)
    codes = {issue.code for issue in issues}

    assert "extra_audio" in codes
    assert "extra_narration" in codes
    assert "extra_prompt" in codes


def test_validator_reports_duration_and_prompt_header_mismatch(tmp_path):
    store = RunStore.create(tmp_path, "불일치 테스트", input_kind="topic")
    script = make_script(scene_count=1, completed=True)
    create_matching_artifacts(store, script)
    prompt_path = store.root / script.scenes[0].video_prompt_file
    prompt_path.write_text(
        prompt_text(script.scenes[0]).replace("Intent:", "Purpose:"),
        encoding="utf-8",
    )

    issues = validate_run(
        store.root,
        duration_reader=lambda _: 14.2,
        settings=HarnessSettings(),
    )
    codes = {issue.code for issue in issues}

    assert "invalid_duration" in codes
    assert "duration_metadata_mismatch" in codes
    assert "prompt_header_mismatch" in codes


def test_validator_rejects_narration_inside_video_prompt(tmp_path):
    store = RunStore.create(tmp_path, "영상 대본 포함 테스트", input_kind="topic")
    script = make_script(scene_count=1, completed=True)
    create_matching_artifacts(store, script)
    prompt_path = store.root / script.scenes[0].video_prompt_file
    prompt_path.write_text(
        prompt_text(script.scenes[0])
        + f"Narration: {script.scenes[0].narration}\n",
        encoding="utf-8",
    )

    codes = {
        issue.code
        for issue in validate_run(store.root, duration_reader=lambda _: 6.42)
    }

    assert "narration_in_prompt" in codes


def test_validator_reports_narration_text_that_differs_from_script(tmp_path):
    store = RunStore.create(tmp_path, "대본 불일치 테스트", input_kind="topic")
    script = make_script(scene_count=1, completed=True)
    create_matching_artifacts(store, script)
    (store.audio_dir / "01_장면_1.txt").write_text(
        "SCENE 01 - 장면 1\nNarration: 다른 대본\n",
        encoding="utf-8",
    )

    codes = {
        issue.code
        for issue in validate_run(store.root, duration_reader=lambda _: 6.42)
    }

    assert "narration_mismatch" in codes


def test_validator_reports_story_review_that_omits_narration(tmp_path):
    store = RunStore.create(tmp_path, "검수본 불일치 테스트", input_kind="topic")
    script = make_script(scene_count=1, completed=True)
    create_matching_artifacts(store, script)
    (store.root / "story-review.md").write_text(
        "## 씬 1 — 장면 1\n\n> 다른 대본\n",
        encoding="utf-8",
    )

    codes = {
        issue.code
        for issue in validate_run(store.root, duration_reader=lambda _: 6.42)
    }

    assert "story_review_mismatch" in codes


def test_validator_reports_incomplete_video_plan(tmp_path):
    store = RunStore.create(tmp_path, "영상 계획 불일치 테스트", input_kind="topic")
    script = make_script(scene_count=1, completed=True)
    create_matching_artifacts(store, script)
    (store.root / "video-plan.md").write_text(
        video_plan_text(script).replace("Status: complete", "Status: assigned"),
        encoding="utf-8",
    )

    codes = {
        issue.code
        for issue in validate_run(store.root, duration_reader=lambda _: 6.42)
    }

    assert "video_plan_mismatch" in codes


def test_manifest_run_requires_prompts_only_for_generated_work(tmp_path):
    store, _, _ = create_manifest_run(tmp_path)
    issues = validate_run(store.root, duration_reader=lambda _: 8.0)
    assert issues == []


def test_manifest_run_allows_archived_legacy_prompt_for_simulation_shot(tmp_path):
    store, _, _ = create_manifest_run(tmp_path)
    (store.video_prompt_dir / "01_혼합_장면.txt").write_text(
        "archived legacy prompt",
        encoding="utf-8",
    )
    issues = validate_run(store.root, duration_reader=lambda _: 8.0)
    assert "missing_prompt" not in {issue.code for issue in issues}
    assert "extra_prompt" not in {issue.code for issue in issues}


def test_manifest_run_reports_only_missing_generated_shot_prompt(tmp_path):
    store, _, _ = create_manifest_run(tmp_path)
    (store.video_prompt_dir / "01A_생성.txt").unlink()
    issues = validate_run(store.root, duration_reader=lambda _: 8.0)
    missing = [issue for issue in issues if issue.code == "missing_prompt"]
    assert len(missing) == 1
    assert "01A" in missing[0].message


def test_manifest_run_reports_missing_video_files_prompt_mirror(tmp_path):
    store, _, _ = create_manifest_run(tmp_path)
    mirror = store.root / "videoFiles/prompts/01_혼합_장면/01A_생성.txt"
    mirror.unlink()

    issues = validate_run(store.root, duration_reader=lambda _: 8.0)

    missing = [issue for issue in issues if issue.code == "missing_prompt_mirror"]
    assert len(missing) == 1
    assert "01A" in missing[0].message


def test_manifest_run_reports_changed_video_files_prompt_mirror(tmp_path):
    store, _, _ = create_manifest_run(tmp_path)
    mirror = store.root / "videoFiles/prompts/01_혼합_장면/01A_생성.txt"
    mirror.write_text("changed mirror", encoding="utf-8")

    issues = validate_run(store.root, duration_reader=lambda _: 8.0)

    mismatches = [issue for issue in issues if issue.code == "prompt_mirror_mismatch"]
    assert len(mismatches) == 1
    assert "01A" in mismatches[0].message


def test_manifest_review_must_equal_compiled_review(tmp_path):
    store, _, _ = create_manifest_run(tmp_path)
    (store.root / "video-plan.md").write_text("hand edited", encoding="utf-8")
    issues = validate_run(store.root, duration_reader=lambda _: 8.0)
    assert "video_plan_mismatch" in {issue.code for issue in issues}


def test_manifest_hash_must_match_current_script_bytes(tmp_path):
    store, script, _ = create_manifest_run(tmp_path)
    script.selected_topic.reason = "changed after plan approval"
    store.write_script(script)
    issues = validate_run(store.root, duration_reader=lambda _: 8.0)
    assert "script_hash_mismatch" in {issue.code for issue in issues}


def test_manifest_prompt_rejects_narration_text(tmp_path):
    store, script, _ = create_manifest_run(tmp_path)
    path = store.video_prompt_dir / "01A_생성.txt"
    path.write_text(
        path.read_text(encoding="utf-8") + f"\nNarration: {script.scenes[0].narration}\n",
        encoding="utf-8",
    )
    issues = validate_run(store.root, duration_reader=lambda _: 8.0)
    assert "narration_in_prompt" in {issue.code for issue in issues}


def test_variant_run_reports_missing_variant_outputs(tmp_path):
    store, _, plan = create_manifest_run(tmp_path)
    add_variant_plan(store, plan)

    codes = {
        issue.code
        for issue in validate_run(store.root, duration_reader=lambda _: 8.0)
    }

    assert "missing_variant_manifest" in codes
    assert "missing_variant_output" in codes


def test_variant_run_rejects_stale_variant_hash(tmp_path):
    store, _, plan = create_manifest_run(tmp_path)
    variant_plan = add_variant_plan(store, plan)
    variant_plan.script_sha256 = "0" * 64
    store.write_model("variant-plan.json", variant_plan)

    codes = {
        issue.code
        for issue in validate_run(store.root, duration_reader=lambda _: 8.0)
    }

    assert "variant_script_hash_mismatch" in codes


def create_v2_validation_run(tmp_path: Path) -> tuple[Path, object, object, object]:
    run_dir = tmp_path / "v2-validation"
    (run_dir / "audioFiles").mkdir(parents=True)
    # Pin settings before compiling a review that includes pacing guidance.
    write_settings_snapshot(run_dir, HarnessSettings())
    script = _script()
    for scene in script.scenes:
        scene.duration_seconds = 6.0
    script_path = run_dir / "script.json"
    script_path.write_text(script.model_dump_json(indent=2) + "\n", encoding="utf-8")
    production = _production(script_sha256(script_path))
    for scene in production.scenes:
        scene.duration_seconds = 6.0
    production.visual_beats[0].end_frame = 180
    production.visual_beats[1].start_frame = 180
    production.visual_beats[1].end_frame = 360
    production_path = run_dir / "production-plan.json"
    production_path.write_text(production.model_dump_json(indent=2) + "\n", encoding="utf-8")
    production_hash = script_sha256(production_path)
    local = _local(script_sha256(script_path), production_hash)
    local.sequences[0].duration_frames = 360
    local.sequences[0].scene_spans[0].end_frame = 180
    local.sequences[0].scene_spans[0].audio_end_frame = 180
    local.sequences[0].scene_spans[1].start_frame = 180
    local.sequences[0].scene_spans[1].end_frame = 360
    local.sequences[0].scene_spans[1].audio_start_frame = 180
    local.sequences[0].scene_spans[1].audio_end_frame = 360
    local.sequences[0].timeline[0].end_frame = 180
    local.sequences[0].timeline[0].simulation_time_end = 6.0
    local.sequences[0].timeline[1].start_frame = 180
    local.sequences[0].timeline[1].end_frame = 360
    local.sequences[0].timeline[1].simulation_time_start = 6.0
    local.sequences[0].timeline[1].simulation_time_end = 12.0
    online = _online(script_sha256(script_path), production_hash)
    for index, shot in enumerate(online.shots):
        shot.source_start_frame = index * 180
        shot.source_end_frame = (index + 1) * 180
        shot.duration_seconds = 6.0
    (run_dir / "local-sequence-plan.json").write_text(
        local.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    (run_dir / "online-plan.json").write_text(
        online.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    variant = SequenceVariantPlan.model_validate(
        {
            "schema_version": 2,
            "production_plan_sha256": production_hash,
            "local_sequence_plan_sha256": script_sha256(run_dir / "local-sequence-plan.json"),
            "script_sha256": script_sha256(script_path),
            "variants": [
                {"variant_id": "balanced", "label": "Balanced", "sequence_ids": ["SEQ01"]},
                {"variant_id": "explain", "label": "Explain", "sequence_ids": ["SEQ01"], "overrides": [{"sequence_id": "SEQ01", "layer_timing_profile": "explain"}]},
                {"variant_id": "dynamic", "label": "Dynamic", "sequence_ids": ["SEQ01"], "overrides": [{"sequence_id": "SEQ01", "camera_profile": "close"}]},
                {"variant_id": "cinematic", "label": "Cinematic", "sequence_ids": ["SEQ01"], "overrides": [{"sequence_id": "SEQ01", "lighting_profile": "cinematic"}]},
            ],
        }
    )
    (run_dir / "variant-plan.json").write_text(
        variant.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    for scene in script.scenes:
        (run_dir / scene.audio_file).write_bytes(b"audio")
        (run_dir / "audioFiles" / scene_filename(scene, ".txt")).write_text(
            narration_text(scene), encoding="utf-8"
        )
    (run_dir / "story-review.md").write_text(review_text(script), encoding="utf-8")
    write_compiled_artifacts(
        run_dir,
        production,
        script,
        local_plan=local,
        online_plan=online,
    )
    assert validate_sequence_plans(
        production,
        local,
        online,
        script,
        script_path=script_path,
        production_path=production_path,
    ) == []
    return run_dir, production, local, online


def materialize_v2_final_artifacts(run_dir: Path, production, local, online) -> None:
    settings = HarnessSettings()
    write_settings_snapshot(run_dir, settings)
    required = [
        "final.mp4",
        "video-only.mp4",
        "final-draft.mp4",
        "video-only-draft.mp4",
        "videoFiles/sequences/final/SEQ01.mp4",
        "videoFiles/sequences/final/SEQ01-narrated.mp4",
        "videoFiles/sequences/draft/SEQ01.mp4",
        "videoFiles/sequences/draft/SEQ01-narrated.mp4",
        "videoFiles/sequences/final/SEQ01-frame-report.json",
        "videoFiles/sequences/final/SEQ01-render-record.json",
        "videoFiles/sequences/draft/SEQ01-frame-report.json",
        "videoFiles/sequences/draft/SEQ01-render-record.json",
        "videoFiles/sequences/state-cache/SEQ01.json",
        "videoFiles/original/01_궤도.mp4",
        "videoFiles/01_궤도.mp4",
        "videoFiles/original/02_시선.mp4",
        "videoFiles/02_시선.mp4",
        "videoFiles/draft/original/01_궤도.mp4",
        "videoFiles/draft/01_궤도.mp4",
        "videoFiles/draft/original/02_시선.mp4",
        "videoFiles/draft/02_시선.mp4",
        "videoFiles/previews/half-second/contact-sheet.png",
        "videoFiles/onlineReferences/ON-B01.mp4",
        "videoFiles/onlineReferences/ON-B02.mp4",
        "videoFiles/variants/02_explain.mp4",
        "videoFiles/variants/03_dynamic.mp4",
        "videoFiles/variants/04_cinematic.mp4",
        "videoFiles/variants/video-only/02_explain.mp4",
        "videoFiles/variants/video-only/03_dynamic.mp4",
        "videoFiles/variants/video-only/04_cinematic.mp4",
    ]
    for relative in required:
        path = run_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(relative.encode())
    preview_files = []
    for milliseconds in range(0, 12_000, 500):
        relative = f"videoFiles/previews/half-second/SEQ01/{milliseconds:06d}ms.png"
        path = run_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"png")
        preview_files.append(relative)
    qa_result = SequenceQaResult(
        sequence_id="SEQ01",
        media_valid=True,
        state_valid=True,
        black_frames=[],
        undeclared_freeze_ranges=[],
        preview_files=preview_files,
        issues=[],
    )
    qa_payload = dict(
        status="passed",
        settings_sha256=settings_sha256(settings),
        production_plan_sha256=script_sha256(run_dir / "production-plan.json"),
        local_sequence_plan_sha256=script_sha256(run_dir / "local-sequence-plan.json"),
        sequence_results=[qa_result],
        contact_sheet_file="videoFiles/previews/half-second/contact-sheet.png",
        issue_codes=[],
        issues=[],
    )
    draft_qa = QaReport(quality="draft", **qa_payload)
    final_qa = QaReport(quality="final", **qa_payload)
    draft_path = run_dir / "videoFiles/sequences/draft/qa-report.json"
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    draft_path.write_text(draft_qa.model_dump_json(indent=2) + "\n", encoding="utf-8")
    (run_dir / "qa-report.json").write_text(
        final_qa.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    variant_outputs = []
    names = {
        "balanced": ("final.mp4", "video-only.mp4"),
        "explain": ("videoFiles/variants/02_explain.mp4", "videoFiles/variants/video-only/02_explain.mp4"),
        "dynamic": ("videoFiles/variants/03_dynamic.mp4", "videoFiles/variants/video-only/03_dynamic.mp4"),
        "cinematic": ("videoFiles/variants/04_cinematic.mp4", "videoFiles/variants/video-only/04_cinematic.mp4"),
    }
    for variant_id, (final_file, original_file) in names.items():
        variant_outputs.append(
            SequenceVariantOutput(
                variant_id=variant_id,
                final_file=final_file,
                original_file=original_file,
                rendered_sequence_ids=[] if variant_id == "balanced" else ["SEQ01"],
                reused_sequence_ids=["SEQ01"] if variant_id == "balanced" else [],
                final_sha256=script_sha256(run_dir / final_file),
                original_sha256=script_sha256(run_dir / original_file),
                qa_status="passed",
            )
        )
    manifest = SequenceVariantManifest(
        production_plan_sha256=script_sha256(run_dir / "production-plan.json"),
        local_sequence_plan_sha256=script_sha256(run_dir / "local-sequence-plan.json"),
        variant_plan_sha256=script_sha256(run_dir / "variant-plan.json"),
        script_sha256=script_sha256(run_dir / "script.json"),
        state_cache_sha256={
            "SEQ01": script_sha256(
                run_dir / "videoFiles/sequences/state-cache/SEQ01.json"
            )
        },
        variants=variant_outputs,
    )
    manifest_path = run_dir / "videoFiles/variants/variants.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    report = LocalProductionReport(
        quality="final",
        script_sha256=script_sha256(run_dir / "script.json"),
        production_plan_sha256=script_sha256(run_dir / "production-plan.json"),
        local_sequence_plan_sha256=script_sha256(run_dir / "local-sequence-plan.json"),
        online_plan_sha256=script_sha256(run_dir / "online-plan.json"),
        draft_qa_file="videoFiles/sequences/draft/qa-report.json",
        final_qa_file="qa-report.json",
        final_file="final.mp4",
        final_original_file="video-only.mp4",
        reference_files=[shot.reference_video_file for shot in online.shots],
        variant_files=[item.final_file for item in variant_outputs],
    )
    (run_dir / "local-production-report.json").write_text(
        report.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )


def test_v2_validation_rejects_pipeline_report_hash_and_missing_generated_claims(tmp_path: Path):
    """A pipeline report must bind to these inputs and cannot claim absent output."""
    run_dir, production, local, online = create_v2_validation_run(tmp_path)
    materialize_v2_final_artifacts(run_dir, production, local, online)
    settings = HarnessSettings()
    write_settings_snapshot(run_dir, settings)
    report = PipelineReport(
        quality="final",
        output_mode="all",
        variant_mode="four",
        settings_sha256=settings_sha256(settings),
        script_sha256=script_sha256(run_dir / "script.json"),
        production_plan_sha256=script_sha256(run_dir / "production-plan.json"),
        local_sequence_plan_sha256=script_sha256(run_dir / "local-sequence-plan.json"),
        online_plan_sha256=script_sha256(run_dir / "online-plan.json"),
        artifacts=[
            PipelineArtifact(path="final.mp4", state="generated"),
            PipelineArtifact(path="future-reference.mp4", state="planned"),
            PipelineArtifact(path="missing-public-output.mp4", state="generated"),
        ],
    )
    (run_dir / "pipeline-report.json").write_text(
        report.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )

    codes = {issue.code for issue in validate_run(run_dir, duration_reader=lambda _: 6.0)}

    assert "pipeline_report_missing_artifact" in codes

    payload = json.loads((run_dir / "pipeline-report.json").read_text(encoding="utf-8"))
    payload["script_sha256"] = "0" * 64
    (run_dir / "pipeline-report.json").write_text(json.dumps(payload), encoding="utf-8")
    codes = {issue.code for issue in validate_run(run_dir, duration_reader=lambda _: 6.0)}

    assert "pipeline_report_hash_mismatch" in codes


def test_v1_validation_ignores_local_report_keyword(tmp_path: Path):
    store = RunStore.create(tmp_path, "legacy", input_kind="topic")
    script = make_script(completed=True)
    create_matching_artifacts(store, script)

    assert validate_run(
        store.root, duration_reader=lambda _: 6.42, require_local_report=False
    ) == validate_run(store.root, duration_reader=lambda _: 6.42)


def test_v2_validation_requires_sequence_artifacts_without_creating_root_prompts(tmp_path: Path):
    run_dir, _, _, _ = create_v2_validation_run(tmp_path)

    codes = {
        issue.code
        for issue in validate_run(run_dir, duration_reader=lambda _: 6.0)
    }

    assert "missing_sequence_master" in codes
    assert "missing_local_production_report" in codes
    assert "missing_prompt" not in codes
    assert not (run_dir / "videoPrompt").exists()


def test_v2_validation_requires_exact_half_second_preview_set(tmp_path: Path):
    run_dir, production, local, online = create_v2_validation_run(tmp_path)
    materialize_v2_final_artifacts(run_dir, production, local, online)
    missing = run_dir / "videoFiles/previews/half-second/SEQ01/000500ms.png"
    missing.unlink()
    extra = run_dir / "videoFiles/previews/half-second/SEQ01/000750ms.png"
    extra.write_bytes(b"extra")

    codes = {
        issue.code
        for issue in validate_run(run_dir, duration_reader=lambda _: 6.0)
    }

    assert "missing_half_second_preview" in codes
    assert "unexpected_half_second_preview" in codes


def test_v2_validation_derives_preview_manifest_from_snapshot_cadence(tmp_path: Path):
    run_dir, production, local, online = create_v2_validation_run(tmp_path)
    materialize_v2_final_artifacts(run_dir, production, local, online)
    settings = ArchivedV5HarnessSettings(render={"preview_interval_seconds": 1.0})
    write_settings_snapshot(run_dir, settings)
    for path in (run_dir / "videoFiles/previews/half-second/SEQ01").glob("*.png"):
        if int(path.stem.removesuffix("ms")) % 1000:
            path.unlink()
    preview_files = [
        f"videoFiles/previews/half-second/SEQ01/{milliseconds:06d}ms.png"
        for milliseconds in range(0, 12_000, 1000)
    ]
    for relative in (
        "videoFiles/sequences/draft/qa-report.json",
        "qa-report.json",
    ):
        path = run_dir / relative
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["settings_sha256"] = settings_sha256(settings)
        payload["preview_interval_seconds"] = 1.0
        payload["contact_sheet_columns"] = 8
        payload["sequence_results"][0]["preview_files"] = preview_files
        path.write_text(json.dumps(payload), encoding="utf-8")

    assert validate_run(run_dir, duration_reader=lambda _: 6.0) == []


def test_v2_validation_rejects_qa_report_with_wrong_snapshot_hash(tmp_path: Path):
    run_dir, production, local, online = create_v2_validation_run(tmp_path)
    materialize_v2_final_artifacts(run_dir, production, local, online)
    write_settings_snapshot(run_dir, HarnessSettings())
    report_path = run_dir / "qa-report.json"
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["settings_sha256"] = "0" * 64
    report_path.write_text(json.dumps(payload), encoding="utf-8")

    codes = {issue.code for issue in validate_run(run_dir, duration_reader=lambda _: 6.0)}

    assert "qa_settings_hash_mismatch" in codes


def test_v2_validation_accepts_complete_schema_v2_artifact_set(tmp_path: Path):
    run_dir, production, local, online = create_v2_validation_run(tmp_path)
    materialize_v2_final_artifacts(run_dir, production, local, online)

    assert validate_run(run_dir, duration_reader=lambda _: 6.0) == []


def test_v2_validation_can_validate_artifacts_before_report_publication(tmp_path: Path):
    run_dir, production, local, online = create_v2_validation_run(tmp_path)
    materialize_v2_final_artifacts(run_dir, production, local, online)
    (run_dir / "local-production-report.json").unlink()

    codes = {
        issue.code
        for issue in validate_run(
            run_dir,
            duration_reader=lambda _: 6.0,
            require_local_report=False,
        )
    }

    assert "missing_local_production_report" not in codes


def test_v2_video_only_validation_allows_absent_prompt_and_reference_artifacts(
    tmp_path: Path,
):
    run_dir, production, local, online = create_v2_validation_run(tmp_path)
    materialize_v2_final_artifacts(run_dir, production, local, online)
    (run_dir / "video-plan.md").unlink()
    for path in (run_dir / "videoFiles/prompts").rglob("*"):
        if path.is_file():
            path.unlink()
    for shot in online.shots:
        if shot.reference_video_file:
            (run_dir / shot.reference_video_file).unlink()

    codes = {
        issue.code
        for issue in validate_run(
            run_dir,
            duration_reader=lambda _: 6.0,
            settings=HarnessSettings(pipeline={"output_mode": "video_only"}),
        )
    }

    assert "missing_video_plan" not in codes
    assert "missing_local_prompt" not in codes
    assert "missing_online_prompt" not in codes
    assert "missing_online_metadata" not in codes
    assert "missing_online_reference" not in codes


def test_v2_prompts_only_validation_does_not_require_video_publication(tmp_path: Path):
    run_dir, _, _, _ = create_v2_validation_run(tmp_path)

    codes = {
        issue.code
        for issue in validate_run(
            run_dir,
            duration_reader=lambda _: 6.0,
            settings=HarnessSettings(pipeline={"output_mode": "prompts_only"}),
        )
    }

    assert "missing_sequence_master" not in codes
    assert "missing_final_output" not in codes
    assert "missing_local_production_report" not in codes


def test_v2_validation_rejects_stale_local_production_report_hash(tmp_path: Path):
    run_dir, production, local, online = create_v2_validation_run(tmp_path)
    materialize_v2_final_artifacts(run_dir, production, local, online)
    path = run_dir / "local-production-report.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["online_plan_sha256"] = "f" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")

    codes = {
        issue.code
        for issue in validate_run(run_dir, duration_reader=lambda _: 6.0)
    }

    assert "local_report_hash_mismatch" in codes


def test_v2_validation_authenticates_state_cache_bytes(tmp_path: Path):
    run_dir, production, local, online = create_v2_validation_run(tmp_path)
    materialize_v2_final_artifacts(run_dir, production, local, online)
    cache = run_dir / "videoFiles/sequences/state-cache/SEQ01.json"
    cache.write_bytes(b"tampered-cache")

    codes = {issue.code for issue in validate_run(run_dir, duration_reader=lambda _: 6.0)}

    assert "variant_state_cache_hash_mismatch" in codes


@pytest.mark.parametrize("mutation", ["missing", "extra"])
def test_v2_validation_requires_exact_state_cache_keys(
    tmp_path: Path, mutation: str
):
    run_dir, production, local, online = create_v2_validation_run(tmp_path)
    materialize_v2_final_artifacts(run_dir, production, local, online)
    path = run_dir / "videoFiles/variants/variants.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if mutation == "missing":
        payload["state_cache_sha256"].pop("SEQ01")
    else:
        payload["state_cache_sha256"]["STALE"] = "0" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")

    codes = {issue.code for issue in validate_run(run_dir, duration_reader=lambda _: 6.0)}

    assert "variant_state_cache_keys_mismatch" in codes


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("final_file", "videoFiles/variants/02_explain.mp4"),
        ("original_file", "videoFiles/variants/video-only/02_explain.mp4"),
    ],
)
def test_v2_validation_rejects_wrong_fixed_variant_media_mapping(
    tmp_path: Path, field: str, replacement: str
):
    run_dir, production, local, online = create_v2_validation_run(tmp_path)
    materialize_v2_final_artifacts(run_dir, production, local, online)
    path = run_dir / "videoFiles/variants/variants.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["variants"][0][field] = replacement
    hash_field = "final_sha256" if field == "final_file" else "original_sha256"
    payload["variants"][0][hash_field] = script_sha256(run_dir / replacement)
    path.write_text(json.dumps(payload), encoding="utf-8")

    codes = {issue.code for issue in validate_run(run_dir, duration_reader=lambda _: 6.0)}

    assert "variant_output_path_mismatch" in codes
    assert "variant_output_path_collision" in codes


def test_v2_validation_authenticates_variant_media_hashes(tmp_path: Path):
    run_dir, production, local, online = create_v2_validation_run(tmp_path)
    materialize_v2_final_artifacts(run_dir, production, local, online)
    (run_dir / "videoFiles/variants/03_dynamic.mp4").write_bytes(b"tampered")

    codes = {issue.code for issue in validate_run(run_dir, duration_reader=lambda _: 6.0)}

    assert "variant_output_hash_mismatch" in codes


def test_v2_validation_rejects_invalid_rendered_reused_partition(tmp_path: Path):
    run_dir, production, local, online = create_v2_validation_run(tmp_path)
    materialize_v2_final_artifacts(run_dir, production, local, online)
    path = run_dir / "videoFiles/variants/variants.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["variants"][1]["rendered_sequence_ids"] = []
    payload["variants"][1]["reused_sequence_ids"] = ["SEQ01"]
    path.write_text(json.dumps(payload), encoding="utf-8")

    codes = {issue.code for issue in validate_run(run_dir, duration_reader=lambda _: 6.0)}

    assert "variant_sequence_partition_mismatch" in codes


@pytest.mark.parametrize(
    "relative",
    [
        "videoFiles/sequences/final/STALE.mp4",
        "videoFiles/sequences/final/STALE-frame-report.json",
        "videoFiles/sequences/state-cache/STALE.json",
        "videoFiles/previews/half-second/STALE/000000ms.png",
        "videoFiles/original/99_stale.mp4",
        "videoFiles/99_stale.mp4",
        "videoFiles/onlineReferences/STALE.mp4",
    ],
)
def test_v2_validation_rejects_extra_typed_owned_artifacts(
    tmp_path: Path, relative: str
):
    run_dir, production, local, online = create_v2_validation_run(tmp_path)
    materialize_v2_final_artifacts(run_dir, production, local, online)
    extra = run_dir / relative
    extra.parent.mkdir(parents=True, exist_ok=True)
    extra.write_bytes(b"stale")

    codes = {issue.code for issue in validate_run(run_dir, duration_reader=lambda _: 6.0)}

    assert "unexpected_v2_artifact" in codes


def test_v2_validation_allows_documented_internal_workspaces(tmp_path: Path):
    run_dir, production, local, online = create_v2_validation_run(tmp_path)
    materialize_v2_final_artifacts(run_dir, production, local, online)
    for relative in (
        ".render-cache/sequences/final/SEQ01/frame-000000.png",
        ".sequence-variants/.transaction-diagnostic/failure.txt",
        ".local-final-diagnostic/failure.txt",
    ):
        path = run_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"diagnostic")

    assert validate_run(run_dir, duration_reader=lambda _: 6.0) == []


def test_v2_owned_artifacts_allow_blender_sources_only_for_blender_plans(tmp_path):
    from video_harness.validation import _validate_no_extra_v2_owned_artifacts
    from video_harness.settings import HarnessSettings
    run_dir, production, local, online = create_v2_validation_run(tmp_path)
    script = ScriptArtifact.model_validate_json((run_dir / 'script.json').read_text())
    for quality in ('draft', 'final'):
        path = run_dir / f'videoFiles/sequences/{quality}/SEQ01.blend'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'BLENDER')
    kwargs = dict(settings=HarnessSettings(), compile_prompts=True,
                  create_references=True, include_video=True)
    issues = _validate_no_extra_v2_owned_artifacts(
        run_dir, script, local.model_copy(update={'renderer': 'blender'}), online, **kwargs)
    assert not issues
    legacy = _validate_no_extra_v2_owned_artifacts(run_dir, script, local, online, **kwargs)
    assert len([i for i in legacy if i.code == 'unexpected_v2_artifact']) == 2
    mixed = local.model_copy(update={'sequences':[
        sequence.model_copy(update={'renderer':'blender' if sequence.sequence_id=='SEQ01' else 'threejs'})
        for sequence in local.sequences]})
    assert not _validate_no_extra_v2_owned_artifacts(run_dir, script, mixed, online, **kwargs)


@pytest.fixture(autouse=True)
def isolate_editorial_gate_dependency(monkeypatch):
    """These subsystem tests use synthetic plans; real gate entrypoints are covered
    without mocks in test_creative_gates.py. Keep this dependency module-scoped.
    """
    monkeypatch.setattr("video_harness.creative_gates.validate_creative_run", lambda *args, **kwargs: [])
