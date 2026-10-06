from __future__ import annotations

import json
from typing import TYPE_CHECKING

from .models import ScriptArtifact
from .production_models import ProductionPlan
from .storage import shot_filename
from .text_labels import format_labels_line

if TYPE_CHECKING:
    from .sequence_models import LocalSequencePlan, OnlinePlan


def _json(value: object) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json", exclude_none=True)
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=lambda item: item.model_dump(mode="json", exclude_none=True),
    )


def render_video_plan(plan: ProductionPlan, script: ScriptArtifact) -> str:
    script_by_id = {scene.scene_id: scene for scene in script.scenes}
    lines = [
        "# Video Production Plan",
        "",
        f"Script SHA-256: {plan.script_sha256}",
        (
            f"Resolution: {plan.defaults.width}x{plan.defaults.height} "
            f"at {plan.defaults.fps} fps"
        ),
        f"Scene transition: {_json(plan.defaults.scene_transition)}",
        "",
    ]

    for production_scene in plan.scenes:
        script_scene = script_by_id[production_scene.scene_id]
        lines.extend(
            [
                f"## SCENE {production_scene.scene_id:02d} - {script_scene.title}",
                "",
                f"Duration: {production_scene.duration_seconds:.2f} seconds",
                "",
            ]
        )
        for shot in production_scene.shots:
            lines.extend(
                [
                    f"### SHOT {shot.shot_id} - {shot.title}",
                    "",
                    f"Duration: {shot.duration_seconds:.2f} seconds",
                    f"Render mode: {shot.render_mode}",
                    f"Purpose: {shot.purpose}",
                    f"Primary visual event: {shot.motion_contract.primary_event}",
                    f"Coordinate space: {_json(shot.coordinate_space)}",
                    f"Start state: {_json(shot.start_state)}",
                    f"End state: {_json(shot.end_state)}",
                    f"Camera: {_json(shot.camera)}",
                    f"Invariants: {_json(shot.invariants)}",
                ]
            )
            if shot.relationships:
                for relationship in shot.relationships:
                    lines.extend(
                        [
                            f"Relationship: {relationship.relationship_id} ({relationship.type})",
                            f"Relationship owner: {relationship.owner}",
                        ]
                    )
            else:
                lines.append("Relationships: []")
            lines.extend(
                [
                    f"Dependencies: {_json(shot.dependencies)}",
                    f"Assets: {_json(shot.assets)}",
                    f"Excluded elements: {_json(shot.excluded_elements)}",
                    (
                        "Expected output: shotFiles/"
                        f"{shot_filename(shot.shot_id, shot.title, '.mp4')}"
                    ),
                    "",
                ]
            )
    return "\n".join(lines).rstrip() + "\n"


def render_sequence_video_plan(
    plan: ProductionPlan,
    local: LocalSequencePlan,
    online: OnlinePlan,
    script: ScriptArtifact,
    text_policy: str = "legacy",
) -> str:
    # Legacy runs keep the byte-exact review their approval hashes were taken from.
    show_labels = text_policy == "keywords"
    script_by_id = {scene.scene_id: scene for scene in script.scenes}
    beats_by_scene: dict[int, list[object]] = {scene.scene_id: [] for scene in script.scenes}
    for beat in plan.visual_beats:
        beats_by_scene.setdefault(beat.scene_id, []).append(beat)
    for beats in beats_by_scene.values():
        beats.sort(key=lambda item: (item.start_frame, item.end_frame, item.beat_id))
    local_by_beat: dict[str, list[tuple[object, object]]] = {}
    for sequence in local.sequences:
        for timeline_beat in sequence.timeline:
            local_by_beat.setdefault(timeline_beat.beat_id, []).append(
                (sequence, timeline_beat)
            )
    online_by_beat: dict[str, list[object]] = {}
    for shot in online.shots:
        for beat_id in shot.beat_ids:
            online_by_beat.setdefault(beat_id, []).append(shot)

    lines = [
        "# Visual Generation Script",
        "",
        f"Script SHA-256: {plan.script_sha256}",
        (
            f"Resolution: {local.defaults.width}x{local.defaults.height} "
            f"at {local.defaults.fps} fps"
        ),
        "",
        "This is the human review copy. Review every scene and shot in order before rendering.",
        "",
    ]
    for scene in script.scenes:
        lines.extend(
            [
                f"## Scene {scene.scene_id:02d} — {scene.title}",
                "",
                f"Narration: {scene.narration}",
                f"Narration duration: {(scene.duration_seconds or 0.0):.2f}s",
                "",
            ]
        )
        for shot_number, visual_beat in enumerate(
            beats_by_scene.get(scene.scene_id, []), start=1
        ):
            duration_frames = visual_beat.end_frame - visual_beat.start_frame
            start_seconds = visual_beat.start_frame / local.defaults.fps
            end_seconds = visual_beat.end_frame / local.defaults.fps
            executions = local_by_beat.get(visual_beat.beat_id, [])
            alternatives = online_by_beat.get(visual_beat.beat_id, [])
            first_execution = executions[0] if executions else None
            if first_execution is not None:
                sequence, timeline_beat = first_execution
                options = timeline_beat.controller_options
                visual_direction = str(
                    options.get("review_visual_description", visual_beat.primary_event)
                )
                framing = str(
                    options.get(
                        "review_framing",
                        f"controller {timeline_beat.controller}; "
                        f"patch targets {_json(timeline_beat.patch_targets)}",
                    )
                )
                camera_movement = str(
                    options.get(
                        "review_camera_movement",
                        (
                            f"controller {timeline_beat.controller} owns the camera change"
                            if "camera" in timeline_beat.patch_targets
                            else "locked camera"
                        ),
                    )
                )
                labels_line = format_labels_line(options)
                local_execution = (
                    f"{sequence.sequence_id} / {timeline_beat.controller}; "
                    f"frames [{timeline_beat.start_frame}, {timeline_beat.end_frame})"
                )
            else:
                visual_direction = visual_beat.primary_event
                framing = "online shot contract"
                camera_movement = "defined by the online shot prompt"
                labels_line = "없음"
                local_execution = "none"
            online_labels = [
                (
                    f"{shot.online_shot_id} "
                    f"({shot.preferred_mode}, {shot.science_authority})"
                )
                for shot in alternatives
            ]
            invariants = list(
                dict.fromkeys(
                    invariant
                    for shot in alternatives
                    for invariant in shot.invariants
                )
            )
            lines.extend(
                [
                    f"### Shot {shot_number} — {visual_beat.beat_id}",
                    f"Sequence time: {start_seconds:.2f}s–{end_seconds:.2f}s "
                    f"({duration_frames / local.defaults.fps:.2f}s)",
                    f"Visual direction: {visual_direction}",
                    f"Framing: {framing}",
                    *([f"On-screen labels: {labels_line}"] if show_labels else []),
                    f"Camera movement: {camera_movement}",
                    f"Relationship owner: {visual_beat.relationship_owner}",
                    f"Local execution: {local_execution}",
                    (
                        f"Online alternative: {', '.join(online_labels)}"
                        if online_labels
                        else "Online alternative: none"
                    ),
                    f"Science invariants: {_json(invariants)}",
                    "",
                ]
            )

    lines.extend(
        [
        "## Technical Appendix",
        "",
        "## Common Visual Sequences",
        "",
        ]
    )
    for sequence in plan.visual_sequences:
        scene_labels = [
            f"{scene_id:02d} {script_by_id[scene_id].title}"
            for scene_id in sequence.scene_ids
        ]
        lines.extend(
            [
                f"### {sequence.sequence_id}",
                f"Scenes: {_json(scene_labels)}",
                f"Primary route: {sequence.primary_route}",
                f"Purpose: {sequence.purpose}",
                f"Visual beats: {_json(sequence.visual_beat_ids)}",
                "",
            ]
        )

    lines.extend(["## Common Visual Beats", ""])
    for beat in plan.visual_beats:
        lines.extend(
            [
                f"### {beat.beat_id}",
                f"Scene: {beat.scene_id:02d} {script_by_id[beat.scene_id].title}",
                f"Frames: [{beat.start_frame}, {beat.end_frame})",
                f"Primary visual event: {beat.primary_event}",
                f"Relationship owner: {beat.relationship_owner}",
                "",
            ]
        )

    lines.extend(["## Local Sequence Execution", ""])
    for sequence in local.sequences:
        lines.extend(
            [
                f"### {sequence.sequence_id}",
                f"Scene graph: {sequence.scene_graph}",
                f"Duration frames: {sequence.duration_frames}",
                f"Scene spans: {_json(sequence.scene_spans)}",
            ]
        )
        for beat in sequence.timeline:
            lines.append(
                f"Controller {beat.beat_id}: {beat.controller}; "
                f"frames [{beat.start_frame}, {beat.end_frame}); "
                f"patch targets {_json(beat.patch_targets)}; priority {beat.priority}"
            )
        lines.append("")

    lines.extend(["## Online Shots", ""])
    for shot in online.shots:
        lines.extend(
            [
                f"### {shot.online_shot_id}",
                f"Sequence: {shot.source_sequence_id}",
                f"Beats: {_json(shot.beat_ids)}",
                f"Scenes: {_json(shot.scene_ids)}",
                f"Source frames: [{shot.source_start_frame}, {shot.source_end_frame})",
                f"Mode: {shot.preferred_mode}",
                f"Science authority: {shot.science_authority}",
                f"Prompt file: {shot.prompt_file}",
                f"Metadata file: {shot.metadata_file}",
                f"Reference image files: {_json(shot.reference_image_files)}",
                f"Reference video file: {shot.reference_video_file or 'none'}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def render_run_video_plan(run_dir, production, local, online, script):
    """One canonical review for compilation, approval and validation."""
    from .creative_gates import render_continuity_review, text_policy_of
    from .pacing_presets import render_pacing_review
    return (
        render_sequence_video_plan(production, local, online, script, text_policy=text_policy_of(run_dir))
        + render_continuity_review(run_dir)
        + render_pacing_review(run_dir, local)
    )
