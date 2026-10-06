from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from .models import ScriptArtifact
from .production_models import ProductionPlan
from .production_review import render_run_video_plan
from .sequence_models import LocalSequence, LocalSequencePlan, OnlinePlan, OnlineShot
from .storage import atomic_write


@dataclass(frozen=True)
class _Artifact:
    destination: Path
    content: str
    owner: str


@dataclass(frozen=True)
class PromptArtifactManifest:
    """Prompt artifacts materialized by compilation and V2V paths kept planned."""

    generated: list[str]
    planned_references: list[str]
    _artifact_root: Path | None = field(default=None, repr=False, compare=False)

    def __iter__(self) -> Iterator[Path]:
        """Yield generated paths as the legacy compiler return value did."""
        root = self._artifact_root
        for relative in self.generated:
            yield (root / relative) if root is not None else Path(relative)

    def __contains__(self, value: object) -> bool:
        if isinstance(value, Path):
            return any(value == generated for generated in self)
        return value in self.generated

    def __len__(self) -> int:
        return len(self.generated)


def compile_online_prompt(shot: OnlineShot, plan: ProductionPlan) -> str:
    lines = [
        f"ONLINE SHOT {shot.online_shot_id}",
        f"Duration: {shot.duration_seconds:.2f} seconds",
        f"Mode: {shot.preferred_mode}",
        "Aspect ratio: 16:9 horizontal landscape",
        f"Primary visual event: {shot.primary_event}",
    ]
    if shot.preferred_mode == "v2v":
        lines.extend(
            [
                "Reference authority: Preserve the reference video's exact positions, trajectories, and frame timing.",
                "Motion lock: Do not alter direction, speed, occlusion, projection, or camera timing.",
                f"Allowed visual changes: {'; '.join(shot.allowed_changes)}",
            ]
        )
    elif shot.preferred_mode == "i2v":
        lines.append(
            "Reference usage: Use the supplied start frame as the exact appearance reference."
        )
    elif shot.preferred_mode == "first_last":
        lines.append("Reference usage: Preserve both supplied boundary frames.")
    lines.append(f"Keep unchanged: {'; '.join(shot.invariants)}")
    style = plan.style_bible
    style_parts = [style.visual_mode, style.lighting]
    if style.palette:
        style_parts.append(f"palette: {', '.join(style.palette)}")
    lines.append(f"Style continuity: {'; '.join(style_parts)}")
    excluded = list(dict.fromkeys(style.excluded_elements + shot.excluded_elements))
    lines.append(f"Excluded elements: {', '.join(excluded)}")
    return "\n".join(lines).rstrip() + "\n"


def _compile_local_sequence_document(
    sequence: LocalSequence,
    plan: ProductionPlan,
) -> str:
    common = next(
        item for item in plan.visual_sequences if item.sequence_id == sequence.sequence_id
    )
    lines = [
        f"# LOCAL SEQUENCE {sequence.sequence_id}",
        "",
        f"Purpose: {common.purpose}",
        f"Scenes: {', '.join(str(scene_id) for scene_id in sequence.scene_ids)}",
        f"Duration: {sequence.duration_frames} canonical frames",
        f"Scene graph: {sequence.scene_graph}",
        "",
        "## Scene spans",
        "",
    ]
    for span in sequence.scene_spans:
        lines.append(
            f"- Scene {span.scene_id}: [{span.start_frame}, {span.end_frame}); "
            f"audio [{span.audio_start_frame}, {span.audio_end_frame}); "
            f"tail silence {span.tail_silence_frames} frames"
        )
    lines.extend(["", "## Timeline controllers", ""])
    for beat in sequence.timeline:
        lines.append(
            f"- {beat.beat_id}: [{beat.start_frame}, {beat.end_frame}); "
            f"controller {beat.controller}; simulation time "
            f"{beat.simulation_time_start} -> {beat.simulation_time_end}; "
            f"patch targets {', '.join(beat.patch_targets)}; priority {beat.priority}"
        )
    lines.extend(
        [
            "",
            "## Complete local sequence contract",
            "",
            "```json",
            json.dumps(
                sequence.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
            ),
            "```",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _artifact_destination(run_dir: Path, relative: str | Path) -> Path:
    destination = (run_dir / relative).resolve()
    if run_dir not in destination.parents:
        raise ValueError(f"artifact path escapes run directory: {relative}")
    return destination


def _preflight_artifacts(
    run_dir: Path,
    production: ProductionPlan,
    local: LocalSequencePlan,
    online: OnlinePlan,
    script: ScriptArtifact,
) -> list[_Artifact]:
    artifacts = [
        _Artifact(
            destination=_artifact_destination(run_dir, "video-plan.md"),
            content=render_run_video_plan(run_dir, production, local, online, script),
            owner="video review",
        )
    ]

    for sequence in local.sequences:
        relative = f"videoFiles/prompts/local/{sequence.sequence_id}.md"
        artifacts.append(
            _Artifact(
                destination=_artifact_destination(run_dir, relative),
                content=_compile_local_sequence_document(sequence, production),
                owner=f"local sequence {sequence.sequence_id}",
            )
        )

    for shot in online.shots:
        metadata = {
            **shot.model_dump(mode="json"),
            "script_sha256": online.script_sha256,
            "production_plan_sha256": online.production_plan_sha256,
        }
        artifacts.extend(
            [
                _Artifact(
                    destination=_artifact_destination(run_dir, shot.prompt_file),
                    content=compile_online_prompt(shot, production),
                    owner=f"online shot {shot.online_shot_id} prompt",
                ),
                _Artifact(
                    destination=_artifact_destination(run_dir, shot.metadata_file),
                    content=json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
                    owner=f"online shot {shot.online_shot_id} metadata",
                ),
            ]
        )

    owners_by_destination: dict[Path, list[str]] = {}
    for artifact in artifacts:
        owners_by_destination.setdefault(artifact.destination, []).append(artifact.owner)
    for destination, owners in owners_by_destination.items():
        if len(owners) > 1:
            raise ValueError(
                f"duplicate artifact destination: {destination} "
                f"is shared by {', '.join(owners)}"
            )
    return artifacts


def write_sequence_prompt_artifacts(
    run_dir: Path,
    production: ProductionPlan,
    local: LocalSequencePlan,
    online: OnlinePlan,
    script: ScriptArtifact,
) -> PromptArtifactManifest:
    run_dir = run_dir.resolve()
    artifacts = _preflight_artifacts(run_dir, production, local, online, script)
    for artifact in artifacts:
        atomic_write(artifact.destination, artifact.content)
    return PromptArtifactManifest(
        generated=[artifact.destination.relative_to(run_dir).as_posix() for artifact in artifacts],
        planned_references=[
            shot.reference_video_file
            for shot in online.shots
            if shot.reference_video_file is not None
        ],
        _artifact_root=run_dir,
    )
