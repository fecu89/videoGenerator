from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import Field, TypeAdapter, model_validator

from .models import StrictModel
from .production import script_sha256
from .production_models import (
    CompositeShot,
    GeneratedShot,
    ProductionPlan,
    ProductionShot,
)
from .sequence_models import LocalSequencePlan


VariantId = Literal["balanced", "explain", "dynamic", "cinematic"]
FIXED_VARIANT_IDS: tuple[VariantId, ...] = (
    "balanced",
    "explain",
    "dynamic",
    "cinematic",
)


class VariantBudget(StrictModel):
    max_alternate_shots: int = Field(default=5, ge=0, le=5)
    max_extra_duration_ratio: float = Field(default=0.5, ge=0, le=0.5)
    max_generated_alternates: int = Field(default=3, ge=0, le=3)
    deterministic_workers: int = Field(default=2, ge=1, le=2)


class AlternateShot(StrictModel):
    scene_id: int = Field(ge=1)
    shot: ProductionShot


class VariantSceneRecipe(StrictModel):
    scene_id: int = Field(ge=1)
    shot_ids: list[str] = Field(min_length=1)


class VariantRecipe(StrictModel):
    variant_id: VariantId
    label: str = Field(min_length=1, max_length=40)
    scenes: list[VariantSceneRecipe] = Field(min_length=1)


class VariantPlan(StrictModel):
    schema_version: Literal[1]
    production_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    script_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    budget: VariantBudget = Field(default_factory=VariantBudget)
    alternate_shots: list[AlternateShot] = Field(default_factory=list)
    variants: list[VariantRecipe] = Field(min_length=4, max_length=4)
    default_variant_id: Literal["balanced"] = "balanced"

    @model_validator(mode="after")
    def require_unique_identifiers(self) -> "VariantPlan":
        recipe_ids = [recipe.variant_id for recipe in self.variants]
        if len(recipe_ids) != len(set(recipe_ids)):
            raise ValueError("variant identifiers must be unique")
        alternate_ids = [item.shot.shot_id for item in self.alternate_shots]
        if len(alternate_ids) != len(set(alternate_ids)):
            raise ValueError("alternate shot identifiers must be unique")
        return self


class SequenceVariantOverride(StrictModel):
    sequence_id: str = Field(pattern=r"^SEQ\d{2,}$")
    camera_profile: Literal["base", "wide", "close", "restrained"] = "base"
    layer_timing_profile: Literal["base", "explain", "dynamic"] = "base"
    lighting_profile: Literal["base", "clear", "cinematic"] = "base"
    scale_profile: Literal["base", "emphasis"] = "base"

    def is_base(self) -> bool:
        return all(
            value == "base"
            for value in (
                self.camera_profile,
                self.layer_timing_profile,
                self.lighting_profile,
                self.scale_profile,
            )
        )

    def presentation_fingerprint(self) -> tuple[str, str, str, str]:
        return (
            self.camera_profile,
            self.layer_timing_profile,
            self.lighting_profile,
            self.scale_profile,
        )


class SequenceVariantRecipe(StrictModel):
    variant_id: VariantId
    label: str = Field(min_length=1, max_length=40)
    sequence_ids: list[str] = Field(min_length=1)
    overrides: list[SequenceVariantOverride] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_unique_override_sequences(self) -> "SequenceVariantRecipe":
        sequence_ids = [override.sequence_id for override in self.overrides]
        if len(sequence_ids) != len(set(sequence_ids)):
            raise ValueError("sequence override identifiers must be unique")
        return self

    def normalized_presentation_fingerprint(
        self,
    ) -> tuple[tuple[str, tuple[str, str, str, str]], ...]:
        overrides = {override.sequence_id: override for override in self.overrides}
        base = ("base", "base", "base", "base")
        ordered_ids = [
            *self.sequence_ids,
            *sorted(set(overrides) - set(self.sequence_ids)),
        ]
        return tuple(
            (
                sequence_id,
                overrides[sequence_id].presentation_fingerprint()
                if sequence_id in overrides
                else base,
            )
            for sequence_id in ordered_ids
        )


class SequenceVariantPlan(StrictModel):
    schema_version: Literal[2]
    production_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    local_sequence_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    script_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    variants: list[SequenceVariantRecipe] = Field(min_length=4, max_length=4)
    default_variant_id: Literal["balanced"] = "balanced"

    @model_validator(mode="after")
    def require_unique_identifiers(self) -> "SequenceVariantPlan":
        recipe_ids = [recipe.variant_id for recipe in self.variants]
        if len(recipe_ids) != len(set(recipe_ids)):
            raise ValueError("variant identifiers must be unique")
        fingerprints: dict[
            tuple[tuple[str, tuple[str, str, str, str]], ...], str
        ] = {}
        for recipe in self.variants:
            effective = [
                override for override in recipe.overrides if not override.is_base()
            ]
            if recipe.variant_id == "balanced" and effective:
                raise ValueError("balanced recipe cannot contain a non-base override")
            if recipe.variant_id != "balanced" and not effective:
                raise ValueError(
                    f"variant {recipe.variant_id} requires an effective non-base override"
                )
            fingerprint = recipe.normalized_presentation_fingerprint()
            duplicate = fingerprints.get(fingerprint)
            if duplicate is not None:
                raise ValueError(
                    f"variant {recipe.variant_id} has a duplicate presentation fingerprint with {duplicate}"
                )
            fingerprints[fingerprint] = recipe.variant_id
        return self


@dataclass(frozen=True)
class VariantIssue:
    code: str
    message: str
    variant_id: str | None = None
    scene_id: int | None = None
    shot_id: str | None = None


VariantPlanArtifact = VariantPlan | SequenceVariantPlan
_VARIANT_PLAN_ADAPTER = TypeAdapter(VariantPlanArtifact)


def load_variant_plan(path: Path) -> VariantPlanArtifact:
    return _VARIANT_PLAN_ADAPTER.validate_json(path.read_text(encoding="utf-8"))


def write_variant_schema(path: Path) -> None:
    schema = _VARIANT_PLAN_ADAPTER.json_schema(mode="validation")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _base_shots(plan: ProductionPlan) -> dict[str, tuple[int, ProductionShot]]:
    return {
        shot.shot_id: (scene.scene_id, shot)
        for scene in plan.scenes
        for shot in scene.shots
    }


def _alternate_shots(plan: VariantPlan) -> dict[str, tuple[int, ProductionShot]]:
    return {
        item.shot.shot_id: (item.scene_id, item.shot)
        for item in plan.alternate_shots
    }


def all_variant_shots(plan: VariantPlan) -> list[ProductionShot]:
    return [item.shot for item in plan.alternate_shots]


def recipe_shots_by_scene(
    variant_plan: VariantPlan,
    production_plan: ProductionPlan,
    recipe: VariantRecipe,
) -> dict[int, list[ProductionShot]]:
    known = {**_base_shots(production_plan), **_alternate_shots(variant_plan)}
    return {
        scene.scene_id: [known[shot_id][1] for shot_id in scene.shot_ids]
        for scene in recipe.scenes
    }


def _is_generated(shot: ProductionShot) -> bool:
    return isinstance(shot, GeneratedShot) or (
        isinstance(shot, CompositeShot) and shot.base.mode == "generated"
    )


def validate_variant_plan(
    plan: VariantPlan,
    production_plan: ProductionPlan,
    production_path: Path,
    script_path: Path,
) -> list[VariantIssue]:
    issues: list[VariantIssue] = []
    if plan.production_plan_sha256 != script_sha256(production_path):
        issues.append(
            VariantIssue(
                "variant_production_hash_mismatch",
                "variant-plan.json production_plan_sha256 does not match production-plan.json",
            )
        )
    if plan.script_sha256 != script_sha256(script_path):
        issues.append(
            VariantIssue(
                "variant_script_hash_mismatch",
                "variant-plan.json script_sha256 does not match script.json",
            )
        )

    recipe_ids = [recipe.variant_id for recipe in plan.variants]
    if recipe_ids != list(FIXED_VARIANT_IDS):
        issues.append(
            VariantIssue(
                "variant_recipe_order",
                f"variant recipes must be ordered as {list(FIXED_VARIANT_IDS)}",
            )
        )

    base = _base_shots(production_plan)
    alternates = _alternate_shots(plan)
    collisions = sorted(set(base) & set(alternates))
    for shot_id in collisions:
        issues.append(
            VariantIssue(
                "alternate_shot_id_collision",
                f"alternate shot ID collides with a base shot: {shot_id}",
                shot_id=shot_id,
            )
        )

    scene_ids = [scene.scene_id for scene in production_plan.scenes]
    known_scene_ids = set(scene_ids)
    for item in plan.alternate_shots:
        if item.scene_id not in known_scene_ids:
            issues.append(
                VariantIssue(
                    "unknown_alternate_scene",
                    f"alternate shot {item.shot.shot_id} references unknown scene {item.scene_id}",
                    scene_id=item.scene_id,
                    shot_id=item.shot.shot_id,
                )
            )

    if len(plan.alternate_shots) > plan.budget.max_alternate_shots:
        issues.append(
            VariantIssue(
                "alternate_shot_budget_exceeded",
                f"alternate shots {len(plan.alternate_shots)} exceed budget {plan.budget.max_alternate_shots}",
            )
        )
    base_duration = sum(
        shot.duration_seconds
        for scene in production_plan.scenes
        for shot in scene.shots
    )
    alternate_duration = sum(item.shot.duration_seconds for item in plan.alternate_shots)
    allowed_duration = base_duration * plan.budget.max_extra_duration_ratio
    if alternate_duration > allowed_duration + 1e-9:
        issues.append(
            VariantIssue(
                "alternate_duration_budget_exceeded",
                f"alternate duration {alternate_duration:.3f}s exceeds budget {allowed_duration:.3f}s",
            )
        )
    generated_count = sum(_is_generated(item.shot) for item in plan.alternate_shots)
    if generated_count > plan.budget.max_generated_alternates:
        issues.append(
            VariantIssue(
                "generated_alternate_budget_exceeded",
                f"generated alternates {generated_count} exceed budget {plan.budget.max_generated_alternates}",
            )
        )

    known = {**base, **alternates}
    production_by_id = {scene.scene_id: scene for scene in production_plan.scenes}
    timeline_fingerprints: dict[tuple[tuple[int, tuple[str, ...]], ...], str] = {}
    for recipe in plan.variants:
        recipe_scene_ids = [scene.scene_id for scene in recipe.scenes]
        if recipe_scene_ids != scene_ids:
            issues.append(
                VariantIssue(
                    "variant_scene_coverage_mismatch",
                    f"variant {recipe.variant_id} scenes {recipe_scene_ids} do not match {scene_ids}",
                    variant_id=recipe.variant_id,
                )
            )

        fingerprint = tuple(
            (scene.scene_id, tuple(scene.shot_ids)) for scene in recipe.scenes
        )
        duplicate = timeline_fingerprints.get(fingerprint)
        if duplicate is not None:
            issues.append(
                VariantIssue(
                    "duplicate_variant_timeline",
                    f"variant {recipe.variant_id} duplicates {duplicate}",
                    variant_id=recipe.variant_id,
                )
            )
        else:
            timeline_fingerprints[fingerprint] = recipe.variant_id

        for scene_recipe in recipe.scenes:
            production_scene = production_by_id.get(scene_recipe.scene_id)
            if production_scene is None:
                continue
            frame_sum = 0
            for shot_id in scene_recipe.shot_ids:
                known_shot = known.get(shot_id)
                if known_shot is None:
                    issues.append(
                        VariantIssue(
                            "unknown_variant_shot",
                            f"variant {recipe.variant_id} references unknown shot {shot_id}",
                            variant_id=recipe.variant_id,
                            scene_id=scene_recipe.scene_id,
                            shot_id=shot_id,
                        )
                    )
                    continue
                owner_scene_id, shot = known_shot
                if owner_scene_id != scene_recipe.scene_id:
                    issues.append(
                        VariantIssue(
                            "variant_shot_scene_mismatch",
                            f"shot {shot_id} belongs to scene {owner_scene_id}",
                            variant_id=recipe.variant_id,
                            scene_id=scene_recipe.scene_id,
                            shot_id=shot_id,
                        )
                    )
                frame_sum += round(shot.duration_seconds * production_plan.defaults.fps)
            expected_frames = round(
                production_scene.duration_seconds * production_plan.defaults.fps
            )
            if frame_sum != expected_frames:
                issues.append(
                    VariantIssue(
                        "variant_scene_frame_sum",
                        f"variant {recipe.variant_id} scene {scene_recipe.scene_id} has {frame_sum} frames, expected {expected_frames}",
                        variant_id=recipe.variant_id,
                        scene_id=scene_recipe.scene_id,
                    )
                )

    balanced = next(
        (recipe for recipe in plan.variants if recipe.variant_id == "balanced"),
        None,
    )
    if balanced is not None:
        balanced_timeline = {
            scene.scene_id: scene.shot_ids for scene in balanced.scenes
        }
        base_timeline = {
            scene.scene_id: [shot.shot_id for shot in scene.shots]
            for scene in production_plan.scenes
        }
        if balanced_timeline != base_timeline:
            issues.append(
                VariantIssue(
                    "balanced_timeline_mismatch",
                    "balanced recipe must exactly match production-plan.json",
                    variant_id="balanced",
                )
            )
    return issues


def validate_sequence_variant_plan(
    plan: SequenceVariantPlan,
    production_plan: ProductionPlan,
    local_plan: LocalSequencePlan,
    *,
    production_path: Path,
    local_path: Path,
    script_path: Path,
) -> list[VariantIssue]:
    issues: list[VariantIssue] = []
    for declared, path, code, label in (
        (
            plan.production_plan_sha256,
            production_path,
            "variant_production_hash_mismatch",
            "production-plan.json",
        ),
        (
            plan.local_sequence_plan_sha256,
            local_path,
            "variant_local_sequence_hash_mismatch",
            "local-sequence-plan.json",
        ),
        (
            plan.script_sha256,
            script_path,
            "variant_script_hash_mismatch",
            "script.json",
        ),
    ):
        if declared != script_sha256(path):
            issues.append(
                VariantIssue(
                    code,
                    f"variant-plan.json hash does not match {label}",
                )
            )

    recipe_ids = [recipe.variant_id for recipe in plan.variants]
    if recipe_ids != list(FIXED_VARIANT_IDS):
        issues.append(
            VariantIssue(
                "variant_recipe_order",
                f"variant recipes must be ordered as {list(FIXED_VARIANT_IDS)}",
            )
        )

    sequence_ids = [sequence.sequence_id for sequence in local_plan.sequences]
    known_ids = set(sequence_ids)
    fingerprints: dict[
        tuple[tuple[str, tuple[str, str, str, str]], ...], str
    ] = {}
    for recipe in plan.variants:
        if recipe.sequence_ids != sequence_ids:
            issues.append(
                VariantIssue(
                    "variant_sequence_order_mismatch",
                    f"variant {recipe.variant_id} sequences {recipe.sequence_ids} do not match {sequence_ids}",
                    variant_id=recipe.variant_id,
                )
            )
        for override in recipe.overrides:
            if override.sequence_id not in known_ids:
                issues.append(
                    VariantIssue(
                        "unknown_variant_sequence_override",
                        f"variant {recipe.variant_id} overrides unknown sequence {override.sequence_id}",
                        variant_id=recipe.variant_id,
                    )
                )

        effective = [
            override for override in recipe.overrides if not override.is_base()
        ]
        if recipe.variant_id != "balanced" and not effective:
            issues.append(
                VariantIssue(
                    "missing_sequence_variant_override",
                    f"variant {recipe.variant_id} requires an effective non-base override",
                    variant_id=recipe.variant_id,
                )
            )
        fingerprint = recipe.normalized_presentation_fingerprint()
        duplicate = fingerprints.get(fingerprint)
        if duplicate is not None:
            issues.append(
                VariantIssue(
                    "duplicate_sequence_variant_presentation",
                    f"variant {recipe.variant_id} duplicates {duplicate}",
                    variant_id=recipe.variant_id,
                )
            )
        else:
            fingerprints[fingerprint] = recipe.variant_id

    balanced = next(
        (recipe for recipe in plan.variants if recipe.variant_id == "balanced"),
        None,
    )
    if balanced is not None and any(
        not override.is_base() for override in balanced.overrides
    ):
        issues.append(
            VariantIssue(
                "balanced_sequence_override",
                "balanced recipe cannot change the base presentation",
                variant_id="balanced",
            )
        )
    return issues
