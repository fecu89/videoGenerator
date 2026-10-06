from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from .models import ScriptArtifact
from .production import script_sha256, validate_plan_against_script
from .production_models import CompositeShot, GeneratedShot, ProductionPlan
from .production_review import render_run_video_plan, render_video_plan
from .prompt_compiler import (
    compile_prompt,
    expected_prompt_path,
    expected_review_prompt_path,
)
from .storage import scene_filename, scene_narration_text
from .sequence_models import LocalSequencePlan, OnlinePlan
from .sequence_plans import (
    load_local_sequence_plan,
    load_online_plan,
    validate_sequence_plans,
)
from .sequence_prompt_compiler import compile_online_prompt
from .sequence_qa import QaReport
from .sequence_variants import SequenceVariantManifest
from .settings import HarnessSettings, resolve_run_settings, settings_sha256
from .media import preview_timestamps
from .variant_render import VariantManifest
from .variants import (
    FIXED_VARIANT_IDS,
    SequenceVariantPlan,
    VariantPlan,
    load_variant_plan,
    validate_sequence_variant_plan,
    validate_variant_plan,
)


# Compatibility aliases; validation itself receives the resolved settings below.
MIN_SCENE_SECONDS = HarnessSettings().voice.min_scene_seconds
MAX_SCENE_SECONDS = HarnessSettings().voice.max_scene_seconds
DURATION_TOLERANCE_SECONDS = HarnessSettings().qa.duration_tolerance_seconds
NUMBERED_FILE = re.compile(r"^\d+_")


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    scene_id: int | None = None
    shot_id: str | None = None


def read_mp3_duration(path: Path) -> float:
    from mutagen.mp3 import MP3

    return float(MP3(path).info.length)


def _load_script(run_dir: Path) -> tuple[ScriptArtifact | None, list[ValidationIssue]]:
    script_path = run_dir / "script.json"
    if not script_path.is_file():
        return None, [ValidationIssue("missing_script", f"파일이 없습니다: {script_path}")]
    try:
        payload = json.loads(script_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return None, [ValidationIssue("invalid_script", f"script.json을 읽을 수 없습니다: {error}")]

    schema_path = Path(__file__).resolve().parent / "schemas" / "script.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema_errors = sorted(
        Draft202012Validator(
            schema,
            format_checker=FormatChecker(),
        ).iter_errors(payload),
        key=lambda error: list(error.absolute_path),
    )
    if schema_errors:
        issues = []
        for error in schema_errors:
            location = ".".join(str(part) for part in error.absolute_path) or "$"
            issues.append(
                ValidationIssue(
                    "invalid_schema",
                    f"script.json {location}: {error.message}",
                )
            )
        return None, issues

    try:
        return ScriptArtifact.model_validate(payload), []
    except ValidationError as error:
        return None, [ValidationIssue("invalid_script", str(error))]


def _load_production_plan(
    run_dir: Path,
) -> tuple[ProductionPlan | None, list[ValidationIssue]]:
    path = run_dir / "production-plan.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return None, [
            ValidationIssue(
                "invalid_production_plan",
                f"production-plan.json을 읽을 수 없습니다: {error}",
            )
        ]

    schema_path = Path(__file__).resolve().parent / "schemas" / "production-plan.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema_errors = sorted(
        Draft202012Validator(schema).iter_errors(payload),
        key=lambda error: list(error.absolute_path),
    )
    if schema_errors:
        issues = []
        for error in schema_errors:
            location = ".".join(str(part) for part in error.absolute_path) or "$"
            issues.append(
                ValidationIssue(
                    "invalid_production_schema",
                    f"production-plan.json {location}: {error.message}",
                )
            )
        return None, issues
    try:
        return ProductionPlan.model_validate(payload), []
    except ValidationError as error:
        return None, [ValidationIssue("invalid_production_plan", str(error))]


def _load_variant_plan(
    run_dir: Path,
) -> tuple[VariantPlan | None, list[ValidationIssue]]:
    path = run_dir / "variant-plan.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return None, [
            ValidationIssue(
                "invalid_variant_plan",
                f"variant-plan.json을 읽을 수 없습니다: {error}",
            )
        ]
    schema_path = Path(__file__).resolve().parent / "schemas" / "variant-plan.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema_errors = sorted(
        Draft202012Validator(schema).iter_errors(payload),
        key=lambda error: list(error.absolute_path),
    )
    if schema_errors:
        return None, [
            ValidationIssue(
                "invalid_variant_schema",
                (
                    "variant-plan.json "
                    f"{'.'.join(str(part) for part in error.absolute_path) or '$'}: "
                    f"{error.message}"
                ),
            )
            for error in schema_errors
        ]
    try:
        return VariantPlan.model_validate(payload), []
    except ValidationError as error:
        return None, [ValidationIssue("invalid_variant_plan", str(error))]


def _validate_variant_artifacts(
    run_dir: Path,
    production_plan: ProductionPlan,
) -> list[ValidationIssue]:
    variant_plan, issues = _load_variant_plan(run_dir)
    if variant_plan is None:
        return issues
    issues.extend(
        ValidationIssue(
            issue.code,
            issue.message,
            issue.scene_id,
            issue.shot_id,
        )
        for issue in validate_variant_plan(
            variant_plan,
            production_plan,
            run_dir / "production-plan.json",
            run_dir / "script.json",
        )
    )

    expected_outputs = (
        "final.mp4",
        "video-only.mp4",
        "videoFiles/variants/02_explain.mp4",
        "videoFiles/variants/03_dynamic.mp4",
        "videoFiles/variants/04_cinematic.mp4",
        "videoFiles/variants/video-only/02_explain.mp4",
        "videoFiles/variants/video-only/03_dynamic.mp4",
        "videoFiles/variants/video-only/04_cinematic.mp4",
    )
    for relative in expected_outputs:
        path = run_dir / relative
        if not path.is_file() or path.stat().st_size == 0:
            issues.append(
                ValidationIssue(
                    "missing_variant_output",
                    f"변형 영상 출력이 없습니다: {relative}",
                )
            )

    manifest_path = run_dir / "videoFiles/variants/variants.json"
    if not manifest_path.is_file() or manifest_path.stat().st_size == 0:
        issues.append(
            ValidationIssue(
                "missing_variant_manifest",
                f"변형 영상 매니페스트가 없습니다: {manifest_path}",
            )
        )
        return issues
    try:
        manifest = VariantManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
    except (OSError, ValidationError) as error:
        issues.append(
            ValidationIssue(
                "invalid_variant_manifest",
                f"variants.json을 읽을 수 없습니다: {error}",
            )
        )
        return issues
    if manifest.variant_plan_sha256 != script_sha256(run_dir / "variant-plan.json"):
        issues.append(
            ValidationIssue(
                "variant_manifest_hash_mismatch",
                "variants.json이 현재 variant-plan.json과 일치하지 않습니다.",
            )
        )
    return issues


def _validate_prompt_header(
    path: Path,
    scene_id: int,
    title: str,
    duration: float,
    narration: str,
) -> list[ValidationIssue]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        return [
            ValidationIssue(
                "invalid_prompt",
                f"프롬프트를 읽을 수 없습니다: {path}: {error}",
                scene_id,
            )
        ]
    lines = text.splitlines()
    expected = [
        f"SCENE {scene_id:02d} - {title}",
        f"Duration: {duration:.2f} seconds",
    ]
    header_matches = (
        len(lines) >= 3
        and lines[:2] == expected
        and lines[2].startswith("Intent: ")
        and bool(lines[2].removeprefix("Intent: ").strip())
    )
    issues = []
    if not header_matches:
        issues.append(
            ValidationIssue(
                "prompt_header_mismatch",
                f"프롬프트 헤더가 script.json과 다릅니다: {path.name}",
                scene_id,
            )
        )
    if "Negative constraints:" not in text:
        issues.append(
            ValidationIssue(
                "prompt_constraints_missing",
                f"Negative constraints가 없습니다: {path.name}",
                scene_id,
            )
        )
    body = "\n".join(lines[3:]).strip() if len(lines) > 3 else ""
    if not body:
        issues.append(
            ValidationIssue(
                "empty_prompt",
                f"영어 영상 프롬프트가 비어 있습니다: {path.name}",
                scene_id,
            )
        )
    if re.search(r"^\s*Narration\s*:", text, re.MULTILINE | re.IGNORECASE) or (
        narration in text
    ):
        issues.append(
            ValidationIssue(
                "narration_in_prompt",
                f"영상 프롬프트에 나레이션이 포함되어 있습니다: {path.name}",
                scene_id,
            )
        )
    return issues


def _validate_shot_prompt(
    path: Path,
    shot: GeneratedShot | CompositeShot,
    scene_id: int,
    narration: str,
    expected_text: str,
) -> list[ValidationIssue]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        return [
            ValidationIssue(
                "invalid_prompt",
                f"프롬프트를 읽을 수 없습니다: {path}: {error}",
                scene_id,
                shot.shot_id,
            )
        ]

    generation = (
        shot.generation
        if isinstance(shot, GeneratedShot)
        else shot.base.generation
    )
    if generation is None:
        return [
            ValidationIssue(
                "invalid_prompt",
                f"생성 계약이 없는 샷에 프롬프트가 연결됐습니다: {shot.shot_id}",
                scene_id,
                shot.shot_id,
            )
        ]

    lines = text.splitlines()
    expected_header = [
        f"SHOT {shot.shot_id} - {shot.title}",
        f"Duration: {shot.duration_seconds:.2f} seconds",
        f"Mode: {generation.mode}",
        "Aspect ratio: 16:9 horizontal landscape",
    ]
    issues: list[ValidationIssue] = []
    if lines[:4] != expected_header:
        issues.append(
            ValidationIssue(
                "prompt_header_mismatch",
                f"샷 프롬프트 헤더가 production-plan.json과 다릅니다: {path.name}",
                scene_id,
                shot.shot_id,
            )
        )
    for section in ("Keep unchanged:", "Excluded elements:"):
        if not any(line.startswith(section) and line.removeprefix(section).strip() for line in lines):
            issues.append(
                ValidationIssue(
                    "prompt_constraints_missing",
                    f"{section} 섹션이 없습니다: {path.name}",
                    scene_id,
                    shot.shot_id,
                )
            )
    if re.search(r"^\s*Narration\s*:", text, re.MULTILINE | re.IGNORECASE) or narration in text:
        issues.append(
            ValidationIssue(
                "narration_in_prompt",
                f"영상 프롬프트에 나레이션이 포함되어 있습니다: {path.name}",
                scene_id,
                shot.shot_id,
            )
        )
    if text != expected_text:
        issues.append(
            ValidationIssue(
                "prompt_compilation_mismatch",
                f"샷 프롬프트가 production-plan.json 컴파일 결과와 다릅니다: {path.name}",
                scene_id,
                shot.shot_id,
            )
        )
    return issues


def _validate_story_review(
    run_dir: Path,
    script: ScriptArtifact,
) -> list[ValidationIssue]:
    path = run_dir / "story-review.md"
    if not path.is_file():
        return [ValidationIssue("missing_story_review", f"파일이 없습니다: {path}")]
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        return [
            ValidationIssue(
                "story_review_mismatch",
                f"검수본을 읽을 수 없습니다: {path}: {error}",
            )
        ]

    issues = []
    for scene in script.scenes:
        titles = {scene.title, scene.title.replace("_", " ")}
        if scene.narration not in text or not any(title in text for title in titles):
            issues.append(
                ValidationIssue(
                    "story_review_mismatch",
                    f"검수본에 씬 {scene.scene_id}의 제목 또는 전체 대본이 없습니다.",
                    scene.scene_id,
                )
            )
    return issues


def _validate_video_plan(
    run_dir: Path,
    script: ScriptArtifact,
) -> list[ValidationIssue]:
    path = run_dir / "video-plan.md"
    if not path.is_file():
        return [ValidationIssue("missing_video_plan", f"파일이 없습니다: {path}")]
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        return [
            ValidationIssue(
                "video_plan_mismatch",
                f"영상 계획을 읽을 수 없습니다: {path}: {error}",
            )
        ]

    issues = []
    for scene in script.scenes:
        header = f"## SCENE {scene.scene_id:02d} - {scene.title}"
        matches = list(re.finditer(rf"^{re.escape(header)}$", text, re.MULTILINE))
        section_matches = len(matches) == 1
        section = ""
        if section_matches:
            section_start = matches[0].end()
            next_header = re.search(r"^## SCENE ", text[section_start:], re.MULTILINE)
            section_end = (
                section_start + next_header.start()
                if next_header is not None
                else len(text)
            )
            section = text[section_start:section_end]

        duration_matches = (
            scene.duration_seconds is not None
            and re.search(
                rf"^Duration: {scene.duration_seconds:.2f} seconds$",
                section,
                re.MULTILINE,
            )
            is not None
        )
        fields_match = all(
            re.search(rf"^{re.escape(prefix)}\s*\S.*$", section, re.MULTILINE)
            is not None
            for prefix in (
                "Visual event:",
                "Cause and effect:",
                "Camera:",
                "Continuity:",
                "Negative constraints:",
            )
        )
        status_matches = (
            re.search(r"^Status: complete$", section, re.MULTILINE) is not None
        )
        if not (section_matches and duration_matches and fields_match and status_matches):
            issues.append(
                ValidationIssue(
                    "video_plan_mismatch",
                    f"영상 계획의 씬 {scene.scene_id} 섹션이 script.json과 다르거나 미완료입니다.",
                    scene.scene_id,
                )
            )
    return issues


def _validate_production_artifacts(
    run_dir: Path,
    script: ScriptArtifact,
    plan: ProductionPlan,
) -> list[ValidationIssue]:
    issues = [
        ValidationIssue(
            issue.code,
            issue.message,
            issue.scene_id,
            issue.shot_id,
        )
        for issue in validate_plan_against_script(
            plan,
            script,
            run_dir / "script.json",
            run_dir,
        )
    ]

    review_path = run_dir / "video-plan.md"
    if not review_path.is_file():
        issues.append(ValidationIssue("missing_video_plan", f"파일이 없습니다: {review_path}"))
    else:
        try:
            review_text = review_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            issues.append(
                ValidationIssue(
                    "video_plan_mismatch",
                    f"영상 계획을 읽을 수 없습니다: {review_path}: {error}",
                )
            )
        else:
            if review_text != render_video_plan(plan, script):
                issues.append(
                    ValidationIssue(
                        "video_plan_mismatch",
                        "video-plan.md가 production-plan.json에서 생성한 검토본과 다릅니다.",
                    )
                )

    script_by_id = {scene.scene_id: scene for scene in script.scenes}
    for production_scene in plan.scenes:
        script_scene = script_by_id.get(production_scene.scene_id)
        if script_scene is None:
            continue
        for shot in production_scene.shots:
            relative = expected_prompt_path(shot)
            if relative is None:
                continue
            path = run_dir / relative
            if not path.is_file() or path.stat().st_size == 0:
                issues.append(
                    ValidationIssue(
                        "missing_prompt",
                        f"샷 {shot.shot_id} 영상 프롬프트가 없습니다: {path.name}",
                        production_scene.scene_id,
                        shot.shot_id,
                    )
                )
                continue
            if isinstance(shot, (GeneratedShot, CompositeShot)):
                mirror_relative = expected_review_prompt_path(script_scene, shot)
                mirror_path = run_dir / str(mirror_relative)
                if not mirror_path.is_file() or mirror_path.stat().st_size == 0:
                    issues.append(
                        ValidationIssue(
                            "missing_prompt_mirror",
                            f"샷 {shot.shot_id} videoFiles 프롬프트 복사본이 없습니다: "
                            f"{mirror_relative}",
                            production_scene.scene_id,
                            shot.shot_id,
                        )
                    )
                elif mirror_path.read_bytes() != path.read_bytes():
                    issues.append(
                        ValidationIssue(
                            "prompt_mirror_mismatch",
                            f"샷 {shot.shot_id} 프롬프트 복사본 내용이 다릅니다: "
                            f"{mirror_relative}",
                            production_scene.scene_id,
                            shot.shot_id,
                        )
                    )
                issues.extend(
                    _validate_shot_prompt(
                        path,
                        shot,
                        production_scene.scene_id,
                        script_scene.narration,
                        compile_prompt(shot, plan.style_bible),
                    )
                )
    return issues


def _required_file(
    run_dir: Path,
    relative: str,
    code: str,
    label: str,
) -> tuple[Path | None, list[ValidationIssue]]:
    if "\\" in relative:
        return None, [ValidationIssue(code, f"{label} 경로가 안전하지 않습니다: {relative}")]
    declared = Path(relative)
    if declared.is_absolute() or ".." in declared.parts:
        return None, [ValidationIssue(code, f"{label} 경로가 안전하지 않습니다: {relative}")]
    root = run_dir.resolve()
    lexical = run_dir / declared
    current = run_dir
    for part in declared.parts:
        current = current / part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            continue
        if current.is_symlink():
            return None, [ValidationIssue(code, f"{label} 경로에 심볼릭 링크가 있습니다: {relative}")]
        if current != lexical and not current.is_dir():
            return None, [ValidationIssue(code, f"{label} 상위 경로가 디렉터리가 아닙니다: {relative}")]
    resolved = lexical.resolve(strict=False)
    if resolved != root and root not in resolved.parents:
        return None, [ValidationIssue(code, f"{label} 경로가 실행 폴더를 벗어납니다: {relative}")]
    if not lexical.is_file() or lexical.stat().st_size == 0:
        return None, [ValidationIssue(code, f"{label} 파일이 없습니다: {relative}")]
    return lexical, []


def _load_v2_execution_plans(
    run_dir: Path,
) -> tuple[
    LocalSequencePlan | None,
    OnlinePlan | None,
    SequenceVariantPlan | None,
    list[ValidationIssue],
]:
    issues: list[ValidationIssue] = []
    try:
        local = load_local_sequence_plan(run_dir / "local-sequence-plan.json")
    except (OSError, ValueError) as error:
        local = None
        issues.append(ValidationIssue("invalid_local_sequence_plan", str(error)))
    try:
        online = load_online_plan(run_dir / "online-plan.json")
    except (OSError, ValueError) as error:
        online = None
        issues.append(ValidationIssue("invalid_online_plan", str(error)))
    try:
        loaded_variant = load_variant_plan(run_dir / "variant-plan.json")
    except (OSError, ValueError) as error:
        variant = None
        issues.append(ValidationIssue("invalid_sequence_variant_plan", str(error)))
    else:
        if isinstance(loaded_variant, SequenceVariantPlan):
            variant = loaded_variant
        else:
            variant = None
            issues.append(
                ValidationIssue(
                    "invalid_sequence_variant_plan",
                    "schema-v2 실행에는 schema-v2 variant-plan.json이 필요합니다.",
                )
            )
    return local, online, variant, issues


def _validate_qa_artifact(
    run_dir: Path,
    relative: str,
    *,
    quality: str,
    production_hash: str,
    local_hash: str,
    expected_sequence_ids: list[str],
    settings: HarnessSettings,
) -> tuple[QaReport | None, list[ValidationIssue]]:
    path, issues = _required_file(run_dir, relative, "missing_qa_report", f"{quality} QA")
    if path is None:
        return None, issues
    try:
        report = QaReport.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return None, [ValidationIssue("invalid_qa_report", f"{relative}: {error}")]
    if report.quality != quality:
        issues.append(ValidationIssue("qa_quality_mismatch", f"{relative} quality가 다릅니다."))
    if report.status != "passed":
        issues.append(ValidationIssue("qa_not_passed", f"{relative} QA가 통과하지 않았습니다."))
    if (
        report.production_plan_sha256 != production_hash
        or report.local_sequence_plan_sha256 != local_hash
    ):
        issues.append(ValidationIssue("qa_plan_hash_mismatch", f"{relative} 계획 해시가 다릅니다."))
    if report.settings_sha256 != settings_sha256(settings):
        issues.append(
            ValidationIssue(
                "qa_settings_hash_mismatch",
                f"{relative} 설정 해시가 run-settings.json과 다릅니다.",
            )
        )
    if report.preview_interval_seconds != settings.render.preview_interval_seconds:
        issues.append(
            ValidationIssue(
                "qa_preview_cadence_mismatch",
                f"{relative} 프리뷰 간격이 현재 설정과 다릅니다.",
            )
        )
    if report.contact_sheet_columns != settings.render.contact_sheet_columns:
        issues.append(
            ValidationIssue(
                "qa_contact_sheet_columns_mismatch",
                f"{relative} contact sheet 열 수가 현재 설정과 다릅니다.",
            )
        )
    if [item.sequence_id for item in report.sequence_results] != expected_sequence_ids:
        issues.append(ValidationIssue("qa_sequence_order_mismatch", f"{relative} 시퀀스 순서가 다릅니다."))
    return report, issues


def _validate_sequence_variant_manifest(
    run_dir: Path,
    *,
    local: LocalSequencePlan,
    variant_plan: SequenceVariantPlan,
    production_hash: str,
    local_hash: str,
    variant_hash: str,
    script_hash: str,
    variant_mode: str,
) -> list[ValidationIssue]:
    relative = "videoFiles/variants/variants.json"
    path, issues = _required_file(
        run_dir, relative, "missing_variant_manifest", "sequence variant manifest"
    )
    if path is None:
        return issues
    try:
        manifest = SequenceVariantManifest.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as error:
        return [ValidationIssue("invalid_variant_manifest", str(error))]
    if (
        manifest.production_plan_sha256 != production_hash
        or manifest.local_sequence_plan_sha256 != local_hash
        or manifest.variant_plan_sha256 != variant_hash
        or manifest.script_sha256 != script_hash
    ):
        issues.append(
            ValidationIssue(
                "variant_manifest_hash_mismatch",
                "sequence variants.json 계획 해시가 현재 입력과 다릅니다.",
            )
        )
    expected_variant_ids = (
        list(FIXED_VARIANT_IDS) if variant_mode == "four" else ["balanced"]
    )
    if [item.variant_id for item in manifest.variants] != expected_variant_ids:
        issues.append(
            ValidationIssue(
                "variant_manifest_order_mismatch",
                "sequence variants.json 레시피 순서가 다릅니다.",
            )
        )
    sequence_ids = [sequence.sequence_id for sequence in local.sequences]
    if list(manifest.state_cache_sha256) != sequence_ids:
        issues.append(
            ValidationIssue(
                "variant_state_cache_keys_mismatch",
                "variants.json state-cache 키가 로컬 시퀀스 순서와 다릅니다.",
            )
        )
    for sequence_id in sequence_ids:
        cache, cache_issues = _required_file(
            run_dir,
            f"videoFiles/sequences/state-cache/{sequence_id}.json",
            "missing_state_cache",
            f"{sequence_id} state cache",
        )
        issues.extend(cache_issues)
        declared = manifest.state_cache_sha256.get(sequence_id)
        if cache is not None and declared != script_sha256(cache):
            issues.append(
                ValidationIssue(
                    "variant_state_cache_hash_mismatch",
                    f"{sequence_id} canonical state-cache 해시가 다릅니다.",
                )
            )
    fixed_paths = {
        "balanced": ("final.mp4", "video-only.mp4"),
        "explain": (
            "videoFiles/variants/02_explain.mp4",
            "videoFiles/variants/video-only/02_explain.mp4",
        ),
        "dynamic": (
            "videoFiles/variants/03_dynamic.mp4",
            "videoFiles/variants/video-only/03_dynamic.mp4",
        ),
        "cinematic": (
            "videoFiles/variants/04_cinematic.mp4",
            "videoFiles/variants/video-only/04_cinematic.mp4",
        ),
    }
    recipes = {recipe.variant_id: recipe for recipe in variant_plan.variants}
    all_media_paths: list[str] = []
    for output in manifest.variants:
        expected_paths = fixed_paths.get(output.variant_id)
        if expected_paths != (output.final_file, output.original_file):
            issues.append(
                ValidationIssue(
                    "variant_output_path_mismatch",
                    f"{output.variant_id} 공개 미디어 경로가 고정 매핑과 다릅니다.",
                )
            )
        all_media_paths.extend((output.final_file, output.original_file))
        recipe = recipes.get(output.variant_id)
        if recipe is not None:
            rendered_set = {
                override.sequence_id
                for override in recipe.overrides
                if not override.is_base()
            }
            expected_rendered = [
                sequence_id for sequence_id in sequence_ids if sequence_id in rendered_set
            ]
            expected_reused = [
                sequence_id for sequence_id in sequence_ids if sequence_id not in rendered_set
            ]
            if (
                output.rendered_sequence_ids != expected_rendered
                or output.reused_sequence_ids != expected_reused
                or set(output.rendered_sequence_ids) & set(output.reused_sequence_ids)
            ):
                issues.append(
                    ValidationIssue(
                        "variant_sequence_partition_mismatch",
                        f"{output.variant_id} rendered/reused 시퀀스 분할이 계획과 다릅니다.",
                    )
                )
        for relative_path, declared_hash in (
            (output.final_file, output.final_sha256),
            (output.original_file, output.original_sha256),
        ):
            media, media_issues = _required_file(
                run_dir,
                relative_path,
                "missing_variant_output",
                f"{output.variant_id} variant",
            )
            issues.extend(media_issues)
            if media is not None and script_sha256(media) != declared_hash:
                issues.append(
                    ValidationIssue(
                        "variant_output_hash_mismatch",
                        f"{relative_path} 해시가 variants.json과 다릅니다.",
                    )
                )
    if len(all_media_paths) != len(set(all_media_paths)):
        issues.append(
            ValidationIssue(
                "variant_output_path_collision",
                "variant 공개 미디어 경로는 모두 고유해야 합니다.",
            )
        )
    return issues


def _validate_local_production_report(
    run_dir: Path,
    *,
    production_hash: str,
    local_hash: str,
    online_hash: str,
    script_hash: str,
    expected_references: list[str],
    variant_mode: str,
) -> list[ValidationIssue]:
    path, issues = _required_file(
        run_dir,
        "local-production-report.json",
        "missing_local_production_report",
        "local production report",
    )
    if path is None:
        return issues
    try:
        from .produce_local import LocalProductionReport

        report = LocalProductionReport.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return [ValidationIssue("invalid_local_production_report", str(error))]
    if report.status != "complete" or report.quality != "final":
        issues.append(
            ValidationIssue(
                "local_report_incomplete",
                "local production report가 완료된 final 실행이 아닙니다.",
            )
        )
    if (
        report.production_plan_sha256 != production_hash
        or report.local_sequence_plan_sha256 != local_hash
        or report.online_plan_sha256 != online_hash
        or report.script_sha256 != script_hash
    ):
        issues.append(
            ValidationIssue(
                "local_report_hash_mismatch",
                "local production report 계획 해시가 현재 입력과 다릅니다.",
            )
        )
    expected_variant_files = ["final.mp4"]
    if variant_mode == "four":
        expected_variant_files.extend(
            [
                "videoFiles/variants/02_explain.mp4",
                "videoFiles/variants/03_dynamic.mp4",
                "videoFiles/variants/04_cinematic.mp4",
            ]
        )
    expected_paths = {
        "draft_qa_file": "videoFiles/sequences/draft/qa-report.json",
        "final_qa_file": "qa-report.json",
        "final_file": "final.mp4",
        "final_original_file": "video-only.mp4",
    }
    for field, expected in expected_paths.items():
        if getattr(report, field) != expected:
            issues.append(
                ValidationIssue(
                    "local_report_path_mismatch",
                    f"local production report {field} 경로가 다릅니다.",
                )
            )
    if report.reference_files != expected_references:
        issues.append(
            ValidationIssue(
                "local_report_reference_mismatch",
                "local production report 참조 영상 목록이 다릅니다.",
            )
        )
    if report.variant_files != expected_variant_files:
        issues.append(
            ValidationIssue(
                "local_report_variant_mismatch",
                "local production report 변형 영상 목록이 다릅니다.",
            )
        )
    for relative in [
        report.draft_qa_file,
        report.final_qa_file,
        report.final_file,
        report.final_original_file,
        *report.reference_files,
        *report.variant_files,
    ]:
        if relative is None:
            continue
        _, path_issues = _required_file(
            run_dir, relative, "local_report_missing_artifact", "reported artifact"
        )
        issues.extend(path_issues)
    return issues


def _validate_pipeline_report(
    run_dir: Path,
    *,
    settings: HarnessSettings,
) -> list[ValidationIssue]:
    """Validate an optional settings-aware orchestration report."""
    path = run_dir / "pipeline-report.json"
    if not path.exists():
        return []
    if not path.is_file() or path.stat().st_size == 0:
        return [ValidationIssue("invalid_pipeline_report", "pipeline-report.json을 읽을 수 없습니다.")]
    try:
        from .pipeline import PipelineReport

        report = PipelineReport.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return [ValidationIssue("invalid_pipeline_report", str(error))]

    issues: list[ValidationIssue] = []
    expected_hashes = {
        "settings_sha256": settings_sha256(settings),
        "script_sha256": script_sha256(run_dir / "script.json"),
        "production_plan_sha256": script_sha256(run_dir / "production-plan.json"),
        "local_sequence_plan_sha256": script_sha256(run_dir / "local-sequence-plan.json"),
        "online_plan_sha256": script_sha256(run_dir / "online-plan.json"),
    }
    if any(getattr(report, field) != expected for field, expected in expected_hashes.items()):
        issues.append(ValidationIssue("pipeline_report_hash_mismatch", "pipeline-report.json 입력 또는 설정 해시가 현재 실행과 다릅니다."))
    if report.output_mode != settings.pipeline.output_mode or report.variant_mode != settings.pipeline.variant_mode:
        issues.append(ValidationIssue("pipeline_report_mode_mismatch", "pipeline-report.json 모드가 현재 run-settings.json과 다릅니다."))

    paths = [artifact.path for artifact in report.artifacts]
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        issues.append(ValidationIssue("pipeline_report_artifact_order", "pipeline-report.json 산출물 경로는 고유한 정렬 목록이어야 합니다."))
    for artifact in report.artifacts:
        declared, artifact_issues = _required_file(
            run_dir, artifact.path, "pipeline_report_missing_artifact", "pipeline reported artifact"
        )
        if artifact.state in {"generated", "reused"}:
            issues.extend(artifact_issues)
        elif artifact.state == "skipped":
            if declared is not None:
                issues.append(ValidationIssue("pipeline_report_skipped_artifact", f"skipped 산출물이 공개 경로에 존재합니다: {artifact.path}"))
            elif artifact_issues and "안전하지" in artifact_issues[0].message:
                issues.extend(artifact_issues)
        elif artifact_issues and "안전하지" in artifact_issues[0].message:
            # Planned output may not exist, but it must still be a safe run-relative path.
            issues.extend(artifact_issues)
    return issues


def _expected_v2_owned_files(
    script: ScriptArtifact,
    local: LocalSequencePlan,
    online: OnlinePlan,
    *,
    preview_interval_seconds: float,
    compile_prompts: bool,
    create_references: bool,
    include_video: bool,
    variant_mode: str,
) -> set[str]:
    expected: set[str] = set()
    if compile_prompts:
        expected.add("video-plan.md")
        expected.update(
            f"videoFiles/prompts/local/{sequence.sequence_id}.md"
            for sequence in local.sequences
        )
        for shot in online.shots:
            expected.update((shot.prompt_file, shot.metadata_file))
    if create_references:
        expected.update(
            shot.reference_video_file
            for shot in online.shots
            if shot.reference_video_file is not None
        )
    if not include_video:
        return expected
    expected.update(
        {
            "videoFiles/sequences/draft/qa-report.json",
            "videoFiles/previews/half-second/contact-sheet.png",
            "videoFiles/variants/variants.json",
        }
    )
    script_by_id = {scene.scene_id: scene for scene in script.scenes}
    for sequence in local.sequences:
        expected.add(f"videoFiles/sequences/state-cache/{sequence.sequence_id}.json")
        for quality in ("draft", "final"):
            prefix = f"videoFiles/sequences/{quality}/{sequence.sequence_id}"
            if (sequence.renderer or local.renderer) == "blender":
                expected.add(f"{prefix}.blend")
            expected.update(
                {
                    f"{prefix}.mp4",
                    f"{prefix}-narrated.mp4",
                    f"{prefix}-frame-report.json",
                    f"{prefix}-render-record.json",
                }
            )
        for span in sequence.scene_spans:
            name = scene_filename(script_by_id[span.scene_id], ".mp4")
            expected.update(
                {
                    f"videoFiles/draft/original/{name}",
                    f"videoFiles/draft/{name}",
                    f"videoFiles/original/{name}",
                    f"videoFiles/{name}",
                }
            )
        expected.update(
            f"videoFiles/previews/half-second/{sequence.sequence_id}/{round(timestamp * 1000):06d}ms.png"
            for timestamp in preview_timestamps(
                sequence.duration_frames / local.defaults.fps,
                preview_interval_seconds,
            )
        )
    variant_paths = [
        ("final.mp4", "video-only.mp4"),
        (
            "videoFiles/variants/02_explain.mp4",
            "videoFiles/variants/video-only/02_explain.mp4",
        ),
        (
            "videoFiles/variants/03_dynamic.mp4",
            "videoFiles/variants/video-only/03_dynamic.mp4",
        ),
        (
            "videoFiles/variants/04_cinematic.mp4",
            "videoFiles/variants/video-only/04_cinematic.mp4",
        ),
    ]
    if variant_mode == "balanced_only":
        variant_paths = variant_paths[:1]
    for final_file, original_file in variant_paths:
        if final_file.startswith("videoFiles/"):
            expected.add(final_file)
        if original_file.startswith("videoFiles/"):
            expected.add(original_file)
    return expected


def _validate_no_extra_v2_owned_artifacts(
    run_dir: Path,
    script: ScriptArtifact,
    local: LocalSequencePlan,
    online: OnlinePlan,
    *,
    settings: HarnessSettings,
    compile_prompts: bool,
    create_references: bool,
    include_video: bool,
) -> list[ValidationIssue]:
    expected = _expected_v2_owned_files(
        script,
        local,
        online,
        preview_interval_seconds=settings.render.preview_interval_seconds,
        compile_prompts=compile_prompts,
        create_references=create_references,
        include_video=include_video,
        variant_mode=settings.pipeline.variant_mode,
    )
    roots: list[str] = []
    if compile_prompts:
        roots.extend(("videoFiles/prompts/local", "videoFiles/prompts/online"))
    if include_video:
        roots.extend(
            (
                "videoFiles/sequences",
                "videoFiles/draft",
                "videoFiles/original",
                "videoFiles/previews/half-second",
                "videoFiles/variants",
            )
        )
    if create_references:
        roots.append("videoFiles/onlineReferences")
    actual: set[str] = set()
    issues: list[ValidationIssue] = []
    for relative_root in roots:
        root = run_dir / relative_root
        if not root.exists():
            continue
        if root.is_symlink() or not root.is_dir():
            issues.append(
                ValidationIssue(
                    "unsafe_v2_artifact_root",
                    f"v2 산출물 루트가 일반 디렉터리가 아닙니다: {relative_root}",
                )
            )
            continue
        for path in root.rglob("*"):
            if path.is_symlink():
                issues.append(
                    ValidationIssue(
                        "unsafe_v2_artifact_path",
                        f"v2 산출물에 심볼릭 링크가 있습니다: {path.relative_to(run_dir)}",
                    )
                )
            elif path.is_file():
                actual.add(path.relative_to(run_dir).as_posix())
    video_root = run_dir / "videoFiles"
    if include_video and video_root.is_dir():
        actual.update(
            path.relative_to(run_dir).as_posix()
            for path in video_root.glob("[0-9][0-9]_*.mp4")
            if path.is_file() and not path.is_symlink()
        )
    for relative in sorted(actual - expected):
        issues.append(
            ValidationIssue(
                "unexpected_v2_artifact",
                f"현재 계획에 없는 v2 산출물이 있습니다: {relative}",
            )
        )
    preview_root = run_dir / "videoFiles/previews/half-second"
    if include_video and preview_root.is_dir():
        expected_directories = {sequence.sequence_id for sequence in local.sequences}
        for path in preview_root.iterdir():
            if path.is_dir() and path.name not in expected_directories:
                issues.append(
                    ValidationIssue(
                        "unexpected_v2_artifact",
                        f"현재 계획에 없는 preview 디렉터리가 있습니다: {path.name}",
                    )
                )
    return issues


def _validate_v2_artifacts(
    run_dir: Path,
    script: ScriptArtifact,
    production: ProductionPlan,
    *,
    require_local_report: bool,
    settings: HarnessSettings,
) -> list[ValidationIssue]:
    compile_prompts = settings.pipeline.output_mode != "video_only"
    include_video = settings.pipeline.output_mode != "prompts_only"
    create_references = settings.pipeline.output_mode == "all"
    issues = [
        ValidationIssue(item.code, item.message, item.scene_id, item.shot_id)
        for item in validate_plan_against_script(
            production, script, run_dir / "script.json", run_dir
        )
    ]
    local, online, variant, load_issues = _load_v2_execution_plans(run_dir)
    issues.extend(load_issues)
    if local is None or online is None or variant is None:
        return issues
    issues.extend(
        ValidationIssue(item.code, item.message, item.scene_id)
        for item in validate_sequence_plans(
            production,
            local,
            online,
            script,
            script_path=run_dir / "script.json",
            production_path=run_dir / "production-plan.json",
        )
    )
    issues.extend(
        ValidationIssue(item.code, item.message, item.scene_id, item.shot_id)
        for item in validate_sequence_variant_plan(
            variant,
            production,
            local,
            production_path=run_dir / "production-plan.json",
            local_path=run_dir / "local-sequence-plan.json",
            script_path=run_dir / "script.json",
        )
    )

    review = None
    if compile_prompts:
        review, review_issues = _required_file(
            run_dir, "video-plan.md", "missing_video_plan", "sequence video plan"
        )
        issues.extend(review_issues)
    if review is not None:
        try:
            actual_review = review.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            issues.append(ValidationIssue("video_plan_mismatch", str(error)))
        else:
            if actual_review != render_run_video_plan(run_dir, production, local, online, script):
                issues.append(
                    ValidationIssue(
                        "video_plan_mismatch",
                        "video-plan.md가 세 계획에서 컴파일한 검토본과 다릅니다.",
                    )
                )

    if compile_prompts:
        for sequence in local.sequences:
            _, prompt_issues = _required_file(
                run_dir,
                f"videoFiles/prompts/local/{sequence.sequence_id}.md",
                "missing_local_prompt",
                f"local sequence {sequence.sequence_id} prompt",
            )
            issues.extend(prompt_issues)
        for shot in online.shots:
            prompt, prompt_issues = _required_file(
                run_dir, shot.prompt_file, "missing_online_prompt", shot.online_shot_id
            )
            metadata, metadata_issues = _required_file(
                run_dir, shot.metadata_file, "missing_online_metadata", shot.online_shot_id
            )
            issues.extend(prompt_issues)
            issues.extend(metadata_issues)
            if prompt is not None and prompt.read_text(encoding="utf-8") != compile_online_prompt(
                shot, production
            ):
                issues.append(
                    ValidationIssue(
                        "online_prompt_mismatch",
                        f"{shot.online_shot_id} 프롬프트가 현재 계획과 다릅니다.",
                    )
                )
            if metadata is not None:
                try:
                    payload = json.loads(metadata.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as error:
                    issues.append(ValidationIssue("invalid_online_metadata", str(error)))
                else:
                    expected = {
                        **shot.model_dump(mode="json"),
                        "script_sha256": online.script_sha256,
                        "production_plan_sha256": online.production_plan_sha256,
                    }
                    if payload != expected:
                        issues.append(
                            ValidationIssue(
                                "online_metadata_mismatch",
                                f"{shot.online_shot_id} 메타데이터가 현재 계획과 다릅니다.",
                            )
                        )

    if not include_video:
        issues.extend(
            _validate_no_extra_v2_owned_artifacts(
                run_dir,
                script,
                local,
                online,
                settings=settings,
                compile_prompts=compile_prompts,
                create_references=create_references,
                include_video=False,
            )
        )
        return issues

    script_by_id = {scene.scene_id: scene for scene in script.scenes}
    for sequence in local.sequences:
        for quality in ("draft", "final"):
            for suffix, code, label in (
                (".mp4", "missing_sequence_master", "sequence master"),
                ("-narrated.mp4", "missing_sequence_master", "narrated sequence master"),
                ("-frame-report.json", "missing_state_report", "state report"),
                ("-render-record.json", "missing_render_record", "render record"),
            ):
                _, file_issues = _required_file(
                    run_dir,
                    f"videoFiles/sequences/{quality}/{sequence.sequence_id}{suffix}",
                    code,
                    f"{quality} {label}",
                )
                issues.extend(file_issues)
        _, file_issues = _required_file(
            run_dir,
            f"videoFiles/sequences/state-cache/{sequence.sequence_id}.json",
            "missing_state_cache",
            "state cache",
        )
        issues.extend(file_issues)
        for span in sequence.scene_spans:
            scene = script_by_id[span.scene_id]
            name = scene_filename(scene, ".mp4")
            for relative in (
                f"videoFiles/draft/original/{name}",
                f"videoFiles/draft/{name}",
                f"videoFiles/original/{name}",
                f"videoFiles/{name}",
            ):
                _, slice_issues = _required_file(
                    run_dir, relative, "missing_scene_slice", f"scene {span.scene_id} slice"
                )
                issues.extend(slice_issues)

    for relative, code, label in (
        ("final-draft.mp4", "missing_draft_output", "narrated draft"),
        ("video-only-draft.mp4", "missing_draft_output", "silent draft"),
        ("final.mp4", "missing_final_output", "narrated final"),
        ("video-only.mp4", "missing_final_output", "silent final"),
        ("videoFiles/previews/half-second/contact-sheet.png", "missing_contact_sheet", "contact sheet"),
    ):
        _, file_issues = _required_file(run_dir, relative, code, label)
        issues.extend(file_issues)
    from .localize import expected_language_outputs
    for relative in sorted(expected_language_outputs(settings)):
        _, file_issues = _required_file(run_dir, relative, "missing_localized_output", f"localized output {relative}")
        issues.extend(file_issues)

    production_hash = script_sha256(run_dir / "production-plan.json")
    local_hash = script_sha256(run_dir / "local-sequence-plan.json")
    online_hash = script_sha256(run_dir / "online-plan.json")
    variant_hash = script_sha256(run_dir / "variant-plan.json")
    script_hash = script_sha256(run_dir / "script.json")
    sequence_ids = [sequence.sequence_id for sequence in local.sequences]
    draft_qa, draft_issues = _validate_qa_artifact(
        run_dir,
        "videoFiles/sequences/draft/qa-report.json",
        quality="draft",
        production_hash=production_hash,
        local_hash=local_hash,
        expected_sequence_ids=sequence_ids,
        settings=settings,
    )
    final_qa, final_issues = _validate_qa_artifact(
        run_dir,
        "qa-report.json",
        quality="final",
        production_hash=production_hash,
        local_hash=local_hash,
        expected_sequence_ids=sequence_ids,
        settings=settings,
    )
    issues.extend(draft_issues)
    issues.extend(final_issues)

    for sequence in local.sequences:
        directory = run_dir / "videoFiles/previews/half-second" / sequence.sequence_id
        expected_names = {
            f"{round(timestamp * 1000):06d}ms.png"
            for timestamp in preview_timestamps(
                sequence.duration_frames / local.defaults.fps,
                settings.render.preview_interval_seconds,
            )
        }
        actual_names = (
            {path.name for path in directory.glob("*.png")} if directory.is_dir() else set()
        )
        for name in sorted(expected_names - actual_names):
            issues.append(
                ValidationIssue(
                    "missing_half_second_preview",
                    f"0.5초 프리뷰가 없습니다: {sequence.sequence_id}/{name}",
                )
            )
        for name in sorted(actual_names - expected_names):
            issues.append(
                ValidationIssue(
                    "unexpected_half_second_preview",
                    f"예상하지 않은 프리뷰가 있습니다: {sequence.sequence_id}/{name}",
                )
            )
        expected_relative = [
            f"videoFiles/previews/half-second/{sequence.sequence_id}/{name}"
            for name in sorted(expected_names)
        ]
        for qa in (final_qa,):
            if qa is None:
                continue
            result = next(
                (item for item in qa.sequence_results if item.sequence_id == sequence.sequence_id),
                None,
            )
            if result is not None and result.preview_files != expected_relative:
                issues.append(
                    ValidationIssue(
                        "qa_preview_manifest_mismatch",
                        f"{qa.quality} QA 프리뷰 목록이 정확한 0.5초 경로와 다릅니다.",
                    )
                )

    expected_references = [
        shot.reference_video_file
        for shot in online.shots
        if create_references and shot.reference_video_file is not None
    ]
    for relative in expected_references:
        _, reference_issues = _required_file(
            run_dir, relative, "missing_online_reference", "V2V reference"
        )
        issues.extend(reference_issues)

    issues.extend(
        _validate_sequence_variant_manifest(
            run_dir,
            local=local,
            variant_plan=variant,
            production_hash=production_hash,
            local_hash=local_hash,
            variant_hash=variant_hash,
            script_hash=script_hash,
            variant_mode=settings.pipeline.variant_mode,
        )
    )
    issues.extend(
        _validate_no_extra_v2_owned_artifacts(
            run_dir,
            script,
            local,
            online,
            settings=settings,
            compile_prompts=compile_prompts,
            create_references=create_references,
            include_video=True,
        )
    )
    if require_local_report:
        issues.extend(
            _validate_local_production_report(
                run_dir,
                production_hash=production_hash,
                local_hash=local_hash,
                online_hash=online_hash,
                script_hash=script_hash,
                expected_references=expected_references,
                variant_mode=settings.pipeline.variant_mode,
            )
        )
    return issues


def validate_run(
    run_dir: Path,
    duration_reader: Callable[[Path], float] = read_mp3_duration,
    *,
    require_local_report: bool = True,
    require_pipeline_report: bool = True,
    settings: HarnessSettings | None = None,
) -> list[ValidationIssue]:
    run_dir = run_dir.resolve()
    settings = settings or resolve_run_settings(run_dir)
    script, issues = _load_script(run_dir)
    if script is None:
        return issues

    audio_dir = run_dir / "audioFiles"
    prompt_dir = run_dir / "videoPrompt"
    expected_audio: set[str] = set()
    expected_narrations: set[str] = set()
    expected_prompts: set[str] = set()

    production_path = run_dir / "production-plan.json"
    production_plan: ProductionPlan | None = None
    manifest_mode = production_path.is_file()

    issues.extend(_validate_story_review(run_dir, script))
    from .creative_gates import validate_creative_run
    issues.extend(ValidationIssue('creative_gate_failed', error) for error in validate_creative_run(run_dir, settings.pipeline.output_mode))
    if manifest_mode:
        production_plan, production_issues = _load_production_plan(run_dir)
        issues.extend(production_issues)
        if production_plan is not None:
            if production_plan.schema_version == 2:
                issues.extend(
                    _validate_v2_artifacts(
                        run_dir,
                        script,
                        production_plan,
                        require_local_report=require_local_report,
                        settings=settings,
                    )
                )
            else:
                issues.extend(_validate_production_artifacts(run_dir, script, production_plan))
                if (run_dir / "variant-plan.json").is_file():
                    issues.extend(_validate_variant_artifacts(run_dir, production_plan))
    else:
        issues.extend(_validate_video_plan(run_dir, script))

    for scene in script.scenes:
        expected_audio_name = scene_filename(scene, ".mp3")
        expected_narration_name = scene_filename(scene, ".txt")
        expected_prompt_name = scene_filename(scene, ".txt")
        expected_audio.add(expected_audio_name)
        expected_narrations.add(expected_narration_name)
        expected_prompts.add(expected_prompt_name)
        expected_audio_relative = f"audioFiles/{expected_audio_name}"
        expected_prompt_relative = f"videoPrompt/{expected_prompt_name}"

        if scene.audio_file and scene.audio_file != expected_audio_relative:
            issues.append(
                ValidationIssue(
                    "audio_path_mismatch",
                    f"audio_file은 {expected_audio_relative}이어야 합니다.",
                    scene.scene_id,
                )
            )
        audio_path = audio_dir / expected_audio_name
        measured_duration = None
        if not audio_path.is_file() or audio_path.stat().st_size == 0:
            issues.append(
                ValidationIssue(
                    "missing_audio",
                    f"음성 파일이 없습니다: {audio_path.name}",
                    scene.scene_id,
                )
            )
        else:
            try:
                measured_duration = float(duration_reader(audio_path))
            except Exception as error:
                issues.append(
                    ValidationIssue(
                        "invalid_audio",
                        f"음성 길이를 읽을 수 없습니다: {audio_path.name}: {error}",
                        scene.scene_id,
                    )
                )
            if measured_duration is not None:
                if not (
                    settings.voice.min_scene_seconds
                    <= measured_duration
                    <= settings.voice.max_scene_seconds
                ):
                    issues.append(
                        ValidationIssue(
                            "invalid_duration",
                            f"{audio_path.name}: {measured_duration:.3f}초",
                            scene.scene_id,
                        )
                    )
                if scene.duration_seconds is None:
                    issues.append(
                        ValidationIssue(
                            "duration_metadata_missing",
                            f"duration_seconds가 없습니다: 씬 {scene.scene_id}",
                            scene.scene_id,
                        )
                    )
                elif (
                    abs(scene.duration_seconds - measured_duration)
                    > settings.qa.duration_tolerance_seconds
                ):
                    issues.append(
                        ValidationIssue(
                            "duration_metadata_mismatch",
                            (
                                f"씬 {scene.scene_id}: script.json {scene.duration_seconds:.3f}초, "
                                f"실제 {measured_duration:.3f}초"
                            ),
                            scene.scene_id,
                        )
                    )

        narration_path = audio_dir / expected_narration_name
        if not narration_path.is_file() or narration_path.stat().st_size == 0:
            issues.append(
                ValidationIssue(
                    "missing_narration",
                    f"대본 텍스트가 없습니다: {narration_path.name}",
                    scene.scene_id,
                )
            )
        else:
            try:
                narration = narration_path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as error:
                issues.append(
                    ValidationIssue(
                        "narration_mismatch",
                        f"대본 텍스트를 읽을 수 없습니다: {narration_path.name}: {error}",
                        scene.scene_id,
                    )
                )
            else:
                if narration != scene_narration_text(scene):
                    issues.append(
                        ValidationIssue(
                            "narration_mismatch",
                            f"대본 텍스트가 script.json과 다릅니다: {narration_path.name}",
                            scene.scene_id,
                        )
                    )

        if not manifest_mode:
            if scene.video_prompt_file and scene.video_prompt_file != expected_prompt_relative:
                issues.append(
                    ValidationIssue(
                        "prompt_path_mismatch",
                        f"video_prompt_file은 {expected_prompt_relative}이어야 합니다.",
                        scene.scene_id,
                    )
                )
            prompt_path = prompt_dir / expected_prompt_name
            if not prompt_path.is_file() or prompt_path.stat().st_size == 0:
                issues.append(
                    ValidationIssue(
                        "missing_prompt",
                        f"영상 프롬프트가 없습니다: {prompt_path.name}",
                        scene.scene_id,
                    )
                )
            elif scene.duration_seconds is not None:
                issues.extend(
                    _validate_prompt_header(
                        prompt_path,
                        scene.scene_id,
                        scene.title,
                        scene.duration_seconds,
                        scene.narration,
                    )
                )

    actual_audio = {
        path.name
        for path in audio_dir.glob("*.mp3")
        if NUMBERED_FILE.match(path.name)
    }
    actual_narrations = {
        path.name
        for path in audio_dir.glob("*.txt")
        if NUMBERED_FILE.match(path.name)
    }
    actual_prompts = {
        path.name
        for path in prompt_dir.glob("*.txt")
        if NUMBERED_FILE.match(path.name)
    }
    for name in sorted(actual_audio - expected_audio):
        issues.append(ValidationIssue("extra_audio", f"여분 음성 파일: {name}"))
    for name in sorted(actual_narrations - expected_narrations):
        issues.append(ValidationIssue("extra_narration", f"여분 대본 텍스트: {name}"))
    if not manifest_mode:
        for name in sorted(actual_prompts - expected_prompts):
            issues.append(ValidationIssue("extra_prompt", f"여분 프롬프트 파일: {name}"))
    if (
        require_pipeline_report
        and manifest_mode
        and production_plan is not None
        and production_plan.schema_version == 2
    ):
        issues.extend(_validate_pipeline_report(run_dir, settings=settings))
    return issues


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="영상 실행 폴더의 대본, 음성, 영상 프롬프트를 검증합니다."
    )
    parser.add_argument("run_directory", type=Path, help="runs 아래의 실행 폴더")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    issues = validate_run(args.run_directory)
    if issues:
        for issue in issues:
            scene = f" SCENE {issue.scene_id:02d}" if issue.scene_id else ""
            shot = f" SHOT {issue.shot_id}" if issue.shot_id else ""
            print(f"[{issue.code}]{scene}{shot} {issue.message}")
        print(f"검증 실패: {len(issues)}개 문제")
        return 1
    print("검증 완료: 대본, 음성, 영상 제작 산출물이 현재 계획과 일치합니다.")
    return 0
