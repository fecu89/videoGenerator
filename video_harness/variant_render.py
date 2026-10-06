from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field

from .media import (
    OutputSpec,
    capture_previews,
    concat_videos,
    mux_audio,
    probe_media,
    validate_media,
)
from .models import Scene, StrictModel
from .production import script_sha256
from .production_models import ProductionPlan
from .shot_backends import ShotContext
from .storage import RunStore, atomic_write, scene_filename
from .variants import VariantPlan, VariantRecipe, recipe_shots_by_scene


class VariantOutput(StrictModel):
    variant_id: Literal["balanced", "explain", "dynamic", "cinematic"]
    label: str
    scene_timelines: dict[str, list[str]]
    final_file: str
    original_file: str
    final_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    original_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reused_balanced_scene_count: int = Field(ge=0)
    preview_files: list[str]
    validation_status: Literal["complete"] = "complete"


class VariantManifest(StrictModel):
    schema_version: Literal[1] = 1
    quality: Literal["draft", "final"]
    production_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    variant_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    script_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    unique_shot_count: int = Field(gt=0)
    shared_audio_files: list[str]
    variants: list[VariantOutput] = Field(min_length=4, max_length=4)


def _variant_root(run_dir: Path, quality: str) -> Path:
    root = run_dir / "videoFiles/variants"
    return root if quality == "final" else root / "draft"


def _transition_values(plan: ProductionPlan) -> tuple[float, float, float]:
    transition = plan.defaults.scene_transition
    if transition.mode != "dip_to_black":
        return 0.0, 0.0, 0.0
    frames = max(4, round(transition.duration_seconds * plan.defaults.fps))
    return (
        transition.duration_seconds,
        transition.fade_seconds,
        frames / plan.defaults.fps,
    )


def _paths_duration(paths: list[Path], *, require_audio: bool) -> float:
    return sum(
        probe_media(path, require_audio=require_audio).duration_seconds
        for path in paths
    )


def _variant_filenames(recipe: VariantRecipe) -> tuple[str, str]:
    number = {
        "explain": "02",
        "dynamic": "03",
        "cinematic": "04",
    }[recipe.variant_id]
    filename = f"{number}_{recipe.variant_id}.mp4"
    return filename, f"video-only/{filename}"


def assemble_variants(
    *,
    run_dir: Path,
    quality: Literal["draft", "final"],
    production_plan: ProductionPlan,
    variant_plan: VariantPlan,
    context: ShotContext,
    script_by_id: dict[int, Scene],
    balanced_scene_dir: Path,
    balanced_original_dir: Path,
    balanced_final: Path,
    balanced_original_final: Path,
    force: bool,
) -> VariantManifest:
    run_dir = run_dir.resolve()
    store = RunStore.open(run_dir)
    root = _variant_root(run_dir, quality)
    root.mkdir(parents=True, exist_ok=True)
    transition_seconds, transition_fade_seconds, transition_actual = (
        _transition_values(production_plan)
    )
    transition_total = max(0, len(production_plan.scenes) - 1) * transition_actual
    base_timelines = {
        scene.scene_id: [shot.shot_id for shot in scene.shots]
        for scene in production_plan.scenes
    }
    outputs: list[VariantOutput] = []

    for recipe in variant_plan.variants:
        recipe_timelines = {
            scene.scene_id: list(scene.shot_ids) for scene in recipe.scenes
        }
        if recipe.variant_id == "balanced":
            final_path = balanced_final
            original_final = balanced_original_final
            reused_count = len(production_plan.scenes)
        else:
            selected = recipe_shots_by_scene(
                variant_plan,
                production_plan,
                recipe,
            )
            scene_dir = root / "scenes" / recipe.variant_id
            original_dir = scene_dir / "original"
            narrated_paths: list[Path] = []
            original_paths: list[Path] = []
            reused_count = 0
            for production_scene in production_plan.scenes:
                script_scene = script_by_id[production_scene.scene_id]
                if recipe_timelines[production_scene.scene_id] == base_timelines[production_scene.scene_id]:
                    original = balanced_original_dir / scene_filename(script_scene, ".mp4")
                    narrated = balanced_scene_dir / scene_filename(script_scene, ".mp4")
                    reused_count += 1
                else:
                    original = original_dir / scene_filename(script_scene, ".mp4")
                    narrated = scene_dir / scene_filename(script_scene, ".mp4")
                    spec = OutputSpec(
                        width=production_plan.defaults.width,
                        height=production_plan.defaults.height,
                        fps=production_plan.defaults.fps,
                        duration_seconds=production_scene.duration_seconds,
                    )
                    if force or not original.is_file():
                        info = concat_videos(
                            [context.output_path(shot) for shot in selected[production_scene.scene_id]],
                            original,
                            expected_duration=production_scene.duration_seconds,
                            require_audio=False,
                        )
                        validate_media(info, spec, require_audio=False)
                    else:
                        validate_media(probe_media(original), spec, require_audio=False)
                    audio = store.path(script_scene.audio_file or "")
                    if force or not narrated.is_file():
                        mux_audio(original, audio, narrated, spec)
                    else:
                        validate_media(
                            probe_media(narrated, require_audio=True),
                            spec,
                            require_audio=True,
                        )
                original_paths.append(original)
                narrated_paths.append(narrated)

            filename, original_relative = _variant_filenames(recipe)
            final_path = root / filename
            original_final = root / original_relative
            original_duration = _paths_duration(
                original_paths,
                require_audio=False,
            ) + transition_total
            narrated_duration = _paths_duration(
                narrated_paths,
                require_audio=True,
            ) + transition_total
            if force or not original_final.is_file():
                concat_videos(
                    original_paths,
                    original_final,
                    expected_duration=original_duration,
                    require_audio=False,
                    transition_seconds=transition_seconds,
                    transition_fade_seconds=transition_fade_seconds,
                )
            if force or not final_path.is_file():
                concat_videos(
                    narrated_paths,
                    final_path,
                    expected_duration=narrated_duration,
                    require_audio=True,
                    transition_seconds=transition_seconds,
                    transition_fade_seconds=transition_fade_seconds,
                )

        preview_paths = capture_previews(
            final_path,
            root / "previews" / recipe.variant_id,
            4.0,
        )
        outputs.append(
            VariantOutput(
                variant_id=recipe.variant_id,
                label=recipe.label,
                scene_timelines={
                    str(scene_id): shot_ids
                    for scene_id, shot_ids in recipe_timelines.items()
                },
                final_file=final_path.relative_to(run_dir).as_posix(),
                original_file=original_final.relative_to(run_dir).as_posix(),
                final_sha256=script_sha256(final_path),
                original_sha256=script_sha256(original_final),
                reused_balanced_scene_count=reused_count,
                preview_files=[
                    path.relative_to(run_dir).as_posix() for path in preview_paths
                ],
            )
        )

    manifest = VariantManifest(
        quality=quality,
        production_plan_sha256=script_sha256(run_dir / "production-plan.json"),
        variant_plan_sha256=script_sha256(run_dir / "variant-plan.json"),
        script_sha256=script_sha256(run_dir / "script.json"),
        unique_shot_count=len(
            {
                shot.shot_id
                for scene in production_plan.scenes
                for shot in scene.shots
            }
            | {item.shot.shot_id for item in variant_plan.alternate_shots}
        ),
        shared_audio_files=[
            script_by_id[scene.scene_id].audio_file or ""
            for scene in production_plan.scenes
        ],
        variants=outputs,
    )
    atomic_write(root / "variants.json", manifest.model_dump_json(indent=2) + "\n")
    return manifest
