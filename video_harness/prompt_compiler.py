from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

from .models import ScriptArtifact
from .production_models import (
    CompositeShot,
    GeneratedShot,
    GenerationContract,
    ProductionPlan,
    ProductionShot,
    StyleBible,
)
from .production_review import render_video_plan
from .sequence_prompt_compiler import (
    PromptArtifactManifest,
    write_sequence_prompt_artifacts,
)
from .storage import atomic_write, scene_filename, shot_filename

if TYPE_CHECKING:
    from .sequence_models import LocalSequencePlan, OnlinePlan
    from .variants import VariantPlan


MULTIPLE_EVENT_SEPARATOR = re.compile(r"[;\n]")


def _generation_contract(shot: GeneratedShot | CompositeShot) -> GenerationContract:
    if isinstance(shot, GeneratedShot):
        return shot.generation
    if shot.base.mode != "generated" or shot.base.generation is None:
        raise ValueError(f"shot {shot.shot_id} has no generated base")
    return shot.base.generation


def expected_prompt_path(shot: ProductionShot) -> str | None:
    if isinstance(shot, GeneratedShot):
        return shot.generation.prompt_file
    if (
        isinstance(shot, CompositeShot)
        and shot.base.mode == "generated"
        and shot.base.generation is not None
    ):
        return shot.base.generation.prompt_file
    return None


def expected_review_prompt_path(scene, shot: ProductionShot) -> str | None:
    if expected_prompt_path(shot) is None:
        return None
    scene_directory = Path(scene_filename(scene, ".mp4")).stem
    filename = shot_filename(shot.shot_id, shot.title, ".txt")
    return f"videoFiles/prompts/{scene_directory}/{filename}"


def _compact_json(value: object) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json", exclude_none=True)
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _stable_unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def compile_prompt(
    shot: GeneratedShot | CompositeShot,
    style: StyleBible,
) -> str:
    generation = _generation_contract(shot)
    primary_event = shot.motion_contract.primary_event.strip()
    if MULTIPLE_EVENT_SEPARATOR.search(primary_event):
        raise ValueError(
            f"shot {shot.shot_id} must contain one primary event without event separators"
        )

    lines = [
        f"SHOT {shot.shot_id} - {shot.title}",
        f"Duration: {shot.duration_seconds:.2f} seconds",
        f"Mode: {generation.mode}",
        "Aspect ratio: 16:9 horizontal landscape",
        "",
    ]

    if generation.mode == "t2v":
        composition = {
            "purpose": shot.purpose,
            "entities": [item.model_dump(mode="json", exclude_none=True) for item in shot.entities],
            "initial_state": shot.start_state.model_dump(mode="json", exclude_none=True),
        }
        lines.append(f"Composition: {_compact_json(composition)}")
    elif generation.mode == "i2v":
        lines.append("Reference usage: Use the supplied start frame as the exact appearance reference.")
    else:
        lines.append("Reference usage: Preserve both supplied boundary frames.")

    lines.append(f"Camera: {_compact_json(shot.camera)}")
    if isinstance(shot, CompositeShot):
        lines.append(
            "Overlay-safe composition: Keep the declared normalized overlay region clear "
            "and preserve stable subject anchors for deterministic post-compositing."
        )

    if generation.mode == "first_last":
        lines.append(f"Transition: {primary_event}")
    else:
        lines.append(f"Primary visual event: {primary_event}")
    lines.append(f"End state: {_compact_json(shot.end_state)}")
    lines.append(f"Keep unchanged: {'; '.join(shot.invariants)}")

    style_parts = [style.visual_mode, style.lighting]
    if style.palette:
        style_parts.append(f"palette: {', '.join(style.palette)}")
    referenced_identities = {
        entity.identity_ref for entity in shot.entities if entity.identity_ref is not None
    }
    for entity in style.entities:
        if entity.entity_id in referenced_identities:
            style_parts.append(
                f"{entity.entity_id}: {', '.join(entity.appearance_constraints)}"
            )
    lines.append(f"Style continuity: {'; '.join(style_parts)}")

    exclusions = _stable_unique(style.excluded_elements + shot.excluded_elements)
    lines.append(f"Excluded elements: {', '.join(exclusions)}")
    return "\n".join(lines).rstrip() + "\n"


def _write_v1_compiled_artifacts(
    run_dir: Path,
    plan: ProductionPlan,
    script: ScriptArtifact,
    variant_plan: VariantPlan | None = None,
) -> PromptArtifactManifest:
    run_dir = run_dir.resolve()
    written: list[Path] = []
    review_path = run_dir / "video-plan.md"
    atomic_write(review_path, render_video_plan(plan, script))
    written.append(review_path)
    script_by_id = {scene.scene_id: scene for scene in script.scenes}

    shot_groups = [
        (scene.scene_id, scene.shots)
        for scene in plan.scenes
    ]
    if variant_plan is not None:
        shot_groups.extend(
            (item.scene_id, [item.shot]) for item in variant_plan.alternate_shots
        )

    for scene_id, shots in shot_groups:
        script_scene = script_by_id[scene_id]
        for shot in shots:
            relative = expected_prompt_path(shot)
            if relative is None:
                continue
            if not isinstance(shot, (GeneratedShot, CompositeShot)):
                raise TypeError(f"unsupported prompt shot: {shot.shot_id}")
            destination = (run_dir / relative).resolve()
            if run_dir not in destination.parents:
                raise ValueError(f"prompt path escapes run directory: {relative}")
            content = compile_prompt(shot, plan.style_bible)
            atomic_write(destination, content)
            written.append(destination)
            mirror_relative = expected_review_prompt_path(script_scene, shot)
            if mirror_relative is None:
                raise TypeError(f"missing review prompt path: {shot.shot_id}")
            mirror = (run_dir / mirror_relative).resolve()
            if run_dir not in mirror.parents:
                raise ValueError(f"prompt mirror path escapes run directory: {mirror_relative}")
            atomic_write(mirror, content)
            written.append(mirror)
    return PromptArtifactManifest(
        generated=[path.relative_to(run_dir).as_posix() for path in written],
        planned_references=[],
        _artifact_root=run_dir,
    )


def write_compiled_artifacts(
    run_dir: Path,
    plan: ProductionPlan,
    script: ScriptArtifact,
    variant_plan: VariantPlan | None = None,
    *,
    local_plan: LocalSequencePlan | None = None,
    online_plan: OnlinePlan | None = None,
) -> PromptArtifactManifest:
    if plan.schema_version == 1:
        return _write_v1_compiled_artifacts(run_dir, plan, script, variant_plan)
    if local_plan is None or online_plan is None:
        raise ValueError("schema version 2 requires local and online plans")
    return write_sequence_prompt_artifacts(
        run_dir,
        plan,
        local_plan,
        online_plan,
        script,
    )
