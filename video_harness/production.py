from __future__ import annotations

import hashlib
import json
import string
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .models import ScriptArtifact
from .production_models import (
    CompositeShot,
    GeneratedShot,
    ProductionPlan,
    ProductionShot,
    StillMotionContract,
    StillMotionShot,
)


@dataclass(frozen=True)
class ProductionIssue:
    code: str
    message: str
    scene_id: int | None = None
    shot_id: str | None = None


def script_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_production_plan(path: Path) -> ProductionPlan:
    return ProductionPlan.model_validate_json(path.read_text(encoding="utf-8"))


def write_production_schema(path: Path) -> None:
    schema = ProductionPlan.model_json_schema(mode="validation")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["allOf"] = [
        {
            "if": {"properties": {"schema_version": {"const": 1}}},
            "then": {
                "properties": {
                    "visual_sequences": {"maxItems": 0},
                    "visual_beats": {"maxItems": 0},
                    "scenes": {
                        "items": {
                            "required": ["shots"],
                            "properties": {"shots": {"minItems": 1}}
                        }
                    },
                }
            },
        },
        {
            "if": {"properties": {"schema_version": {"const": 2}}},
            "then": {
                "required": ["visual_sequences", "visual_beats"],
                "properties": {
                    "visual_sequences": {"minItems": 1},
                    "visual_beats": {"minItems": 1},
                },
            },
        },
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _safe_run_path(run_dir: Path, relative: str) -> Path | None:
    relative_path = Path(relative)
    if relative_path.is_absolute():
        return None
    resolved_run = run_dir.resolve()
    candidate = (resolved_run / relative_path).resolve()
    if candidate != resolved_run and resolved_run not in candidate.parents:
        return None
    return candidate


def _still_asset_paths(contract: StillMotionContract) -> Iterable[str]:
    yield contract.source_image
    for layer in contract.layers:
        yield layer.source_image
        if layer.mask:
            yield layer.mask


def _authoring_asset_paths(shot: ProductionShot) -> Iterable[str]:
    for value in (
        shot.assets.start_image,
        shot.assets.end_image,
        shot.assets.background,
        shot.assets.mask,
    ):
        if value:
            yield value
    yield from shot.assets.reference_images
    if isinstance(shot, StillMotionShot):
        yield from _still_asset_paths(shot.still_motion)
    if isinstance(shot, CompositeShot) and shot.base.still_motion is not None:
        yield from _still_asset_paths(shot.base.still_motion)


def _generation_contracts(shot: ProductionShot):
    if isinstance(shot, GeneratedShot):
        yield shot.generation
    if isinstance(shot, CompositeShot) and shot.base.generation is not None:
        yield shot.base.generation


def _validate_visual_sequence_contract(
    plan: ProductionPlan, script_ids: list[int]
) -> list[ProductionIssue]:
    issues: list[ProductionIssue] = []
    sequence_ids = [sequence.sequence_id for sequence in plan.visual_sequences]
    if len(sequence_ids) != len(set(sequence_ids)):
        issues.append(
            ProductionIssue(
                "duplicate_sequence_id",
                "visual sequence IDs must be unique",
            )
        )

    beat_ids = [beat.beat_id for beat in plan.visual_beats]
    if len(beat_ids) != len(set(beat_ids)):
        issues.append(ProductionIssue("duplicate_beat_id", "visual beat IDs must be unique"))

    sequence_scene_ids = [
        scene_id
        for sequence in plan.visual_sequences
        for scene_id in sequence.scene_ids
    ]
    if sequence_scene_ids != script_ids:
        issues.append(
            ProductionIssue(
                "sequence_scene_coverage_mismatch",
                (
                    "visual sequence scene IDs "
                    f"{sequence_scene_ids} do not match script scene IDs {script_ids}"
                ),
            )
        )

    sequence_beat_ids = [
        beat_id
        for sequence in plan.visual_sequences
        for beat_id in sequence.visual_beat_ids
    ]
    if sorted(sequence_beat_ids) != sorted(beat_ids):
        issues.append(
            ProductionIssue(
                "beat_sequence_membership_mismatch",
                "each visual beat must belong to exactly one visual sequence",
            )
        )

    beats_by_id = {beat.beat_id: beat for beat in plan.visual_beats}
    for sequence in plan.visual_sequences:
        expected_scene_ids = list(
            range(sequence.scene_ids[0], sequence.scene_ids[-1] + 1)
        )
        if sequence.scene_ids != expected_scene_ids:
            issues.append(
                ProductionIssue(
                    "nonconsecutive_sequence_scenes",
                    (
                        f"visual sequence {sequence.sequence_id} scene IDs "
                        "must be ordered and consecutive"
                    ),
                )
            )
        for beat_id in sequence.visual_beat_ids:
            beat = beats_by_id.get(beat_id)
            if beat is not None and beat.scene_id not in sequence.scene_ids:
                issues.append(
                    ProductionIssue(
                        "beat_scene_ownership_mismatch",
                        (
                            f"visual beat {beat_id} scene {beat.scene_id} is not in "
                            f"visual sequence {sequence.sequence_id}"
                        ),
                        beat.scene_id,
                    )
                )

    return issues


def validate_plan_against_script(
    plan: ProductionPlan,
    script: ScriptArtifact,
    script_path: Path,
    run_dir: Path,
) -> list[ProductionIssue]:
    issues: list[ProductionIssue] = []
    if plan.script_sha256 != script_sha256(script_path):
        issues.append(
            ProductionIssue(
                "script_hash_mismatch",
                "production-plan.json script_sha256 does not match script.json",
            )
        )

    script_ids = [scene.scene_id for scene in script.scenes]
    production_ids = [scene.scene_id for scene in plan.scenes]
    if production_ids != script_ids:
        issues.append(
            ProductionIssue(
                "scene_coverage_mismatch",
                f"production scene IDs {production_ids} do not match script scene IDs {script_ids}",
            )
        )

    if plan.schema_version == 2:
        issues.extend(_validate_visual_sequence_contract(plan, script_ids))

    script_by_id = {scene.scene_id: scene for scene in script.scenes}
    style_entity_ids = {entity.entity_id for entity in plan.style_bible.entities}
    seen_shots: set[str] = set()

    for production_scene in plan.scenes:
        script_scene = script_by_id.get(production_scene.scene_id)
        if script_scene is not None:
            if script_scene.duration_seconds is None:
                issues.append(
                    ProductionIssue(
                        "scene_duration_missing",
                        f"script scene {production_scene.scene_id} has no measured duration",
                        production_scene.scene_id,
                    )
                )
            elif abs(script_scene.duration_seconds - production_scene.duration_seconds) > 0.05:
                issues.append(
                    ProductionIssue(
                        "scene_duration_mismatch",
                        (
                            f"scene {production_scene.scene_id} production duration "
                            f"{production_scene.duration_seconds:.3f}s does not match script "
                            f"{script_scene.duration_seconds:.3f}s"
                        ),
                        production_scene.scene_id,
                    )
                )

        if plan.schema_version == 2:
            continue

        expected_ids = [
            f"{production_scene.scene_id:02d}{string.ascii_uppercase[index]}"
            for index in range(len(production_scene.shots))
        ]
        actual_ids = [shot.shot_id for shot in production_scene.shots]
        if len(production_scene.shots) > len(string.ascii_uppercase) or actual_ids != expected_ids:
            issues.append(
                ProductionIssue(
                    "shot_order_mismatch",
                    f"scene {production_scene.scene_id} shot IDs must be sequential: {expected_ids}",
                    production_scene.scene_id,
                )
            )

        duration_sum = sum(shot.duration_seconds for shot in production_scene.shots)
        if abs(duration_sum - production_scene.duration_seconds) > 1 / plan.defaults.fps:
            issues.append(
                ProductionIssue(
                    "shot_duration_sum",
                    (
                        f"scene {production_scene.scene_id} shot durations total "
                        f"{duration_sum:.3f}s, expected {production_scene.duration_seconds:.3f}s"
                    ),
                    production_scene.scene_id,
                )
            )
        shot_frame_sum = sum(
            round(shot.duration_seconds * plan.defaults.fps)
            for shot in production_scene.shots
        )
        scene_frame_count = round(
            production_scene.duration_seconds * plan.defaults.fps
        )
        if shot_frame_sum != scene_frame_count:
            issues.append(
                ProductionIssue(
                    "shot_frame_sum",
                    (
                        f"scene {production_scene.scene_id} shot frames total "
                        f"{shot_frame_sum}, expected {scene_frame_count}"
                    ),
                    production_scene.scene_id,
                )
            )

        for shot in production_scene.shots:
            for dependency in shot.dependencies:
                if dependency.shot_id not in seen_shots:
                    issues.append(
                        ProductionIssue(
                            "invalid_shot_dependency",
                            (
                                f"shot {shot.shot_id} dependency {dependency.shot_id} "
                                "must reference an earlier shot"
                            ),
                            production_scene.scene_id,
                            shot.shot_id,
                        )
                    )

            for entity in shot.entities:
                if entity.identity_ref and entity.identity_ref not in style_entity_ids:
                    issues.append(
                        ProductionIssue(
                            "unknown_style_entity",
                            f"shot {shot.shot_id} references unknown style entity {entity.identity_ref}",
                            production_scene.scene_id,
                            shot.shot_id,
                        )
                    )

            for relative in _authoring_asset_paths(shot):
                candidate = _safe_run_path(run_dir, relative)
                if candidate is None:
                    issues.append(
                        ProductionIssue(
                            "unsafe_asset_path",
                            f"shot {shot.shot_id} asset escapes run directory: {relative}",
                            production_scene.scene_id,
                            shot.shot_id,
                        )
                    )
                elif not relative.startswith("shotAssets/"):
                    issues.append(
                        ProductionIssue(
                            "invalid_asset_root",
                            f"shot {shot.shot_id} asset must be under shotAssets/: {relative}",
                            production_scene.scene_id,
                            shot.shot_id,
                        )
                    )
                elif not candidate.is_file():
                    issues.append(
                        ProductionIssue(
                            "missing_asset",
                            f"shot {shot.shot_id} authoring asset is missing: {relative}",
                            production_scene.scene_id,
                            shot.shot_id,
                        )
                    )

            for generation in _generation_contracts(shot):
                for relative, root, code in (
                    (generation.prompt_file, "videoPrompt/", "invalid_prompt_path"),
                    (generation.inbox_file, "shotFiles/inbox/", "invalid_inbox_path"),
                ):
                    candidate = _safe_run_path(run_dir, relative)
                    if candidate is None or not relative.startswith(root):
                        issues.append(
                            ProductionIssue(
                                code,
                                f"shot {shot.shot_id} path must stay under {root}: {relative}",
                                production_scene.scene_id,
                                shot.shot_id,
                            )
                        )
            seen_shots.add(shot.shot_id)

    return issues
