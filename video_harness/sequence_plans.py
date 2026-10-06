from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .models import Scene, ScriptArtifact
from .production import script_sha256
from .production_models import ProductionPlan
from .sequence_models import LocalSequencePlan, OnlinePlan, SequenceTimelineBeat
from .storage import atomic_write


ECLIPSE_EXPLANATION_CLOSE_VIEWS = {
    "solar-eclipse-alignment": "earth_close_shadow_track",
    "lunar-eclipse-alignment": "moon_close_shadow_entry",
}


@dataclass(frozen=True)
class SequencePlanIssue:
    code: str
    message: str
    sequence_id: str | None = None
    scene_id: int | None = None
    beat_id: str | None = None


def canonical_audio_frames(scene: Scene, fps: int) -> int:
    if scene.duration_seconds is None:
        raise ValueError(f"scene {scene.scene_id} has no measured duration")
    return math.ceil(scene.duration_seconds * fps)


def load_local_sequence_plan(path: Path) -> LocalSequencePlan:
    return LocalSequencePlan.model_validate_json(path.read_text(encoding="utf-8"))


def load_online_plan(path: Path) -> OnlinePlan:
    return OnlinePlan.model_validate_json(path.read_text(encoding="utf-8"))


def write_sequence_schemas(schema_dir: Path) -> None:
    for filename, model in (
        ("local-sequence-plan.schema.json", LocalSequencePlan),
        ("online-plan.schema.json", OnlinePlan),
    ):
        schema = model.model_json_schema(mode="validation")
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        atomic_write(
            schema_dir / filename,
            json.dumps(schema, ensure_ascii=False, indent=2) + "\n",
        )


def validate_sequence_plans(
    production: ProductionPlan,
    local: LocalSequencePlan,
    online: OnlinePlan,
    script: ScriptArtifact,
    *,
    script_path: Path,
    production_path: Path,
) -> list[SequencePlanIssue]:
    issues: list[SequencePlanIssue] = []
    issues.extend(validate_plan_hashes(local, online, script_path, production_path))
    issues.extend(validate_local_route_coverage(production, local))
    issues.extend(validate_scene_spans(local, script))
    issues.extend(validate_local_timelines(production, local))
    issues.extend(validate_eclipse_explanation_design(production, local))
    issues.extend(validate_online_coverage(production, local, online))
    return issues


def validate_plan_hashes(
    local: LocalSequencePlan,
    online: OnlinePlan,
    script_path: Path,
    production_path: Path,
) -> list[SequencePlanIssue]:
    issues: list[SequencePlanIssue] = []
    expected_script_hash = script_sha256(script_path)
    expected_production_hash = script_sha256(production_path)
    for plan_name, plan in (("local", local), ("online", online)):
        if plan.script_sha256 != expected_script_hash:
            issues.append(
                SequencePlanIssue(
                    "stale_script",
                    f"{plan_name} plan does not reference the current script",
                )
            )
        if plan.production_plan_sha256 != expected_production_hash:
            issues.append(
                SequencePlanIssue(
                    "stale_production_plan",
                    f"{plan_name} plan does not reference the current production plan",
                )
            )
    return issues


def _is_relative_descendant(value: str) -> bool:
    if "\\" in value:
        return False
    path = PurePosixPath(value)
    return bool(path.parts) and not path.is_absolute() and ".." not in path.parts


def _is_under(value: str, root: tuple[str, ...]) -> bool:
    if not _is_relative_descendant(value):
        return False
    parts = PurePosixPath(value).parts
    return len(parts) > len(root) and parts[: len(root)] == root


def validate_local_route_coverage(
    production: ProductionPlan,
    local: LocalSequencePlan,
) -> list[SequencePlanIssue]:
    issues: list[SequencePlanIssue] = []
    if (
        local.defaults.width != production.defaults.width
        or local.defaults.height != production.defaults.height
        or local.defaults.fps != production.defaults.fps
    ):
        issues.append(
            SequencePlanIssue(
                "local_defaults_mismatch",
                "local width, height, and fps must match the production defaults",
            )
        )
    if not _is_relative_descendant(local.simulation_config_file):
        issues.append(
            SequencePlanIssue(
                "invalid_local_path",
                "simulation_config_file must be a relative descendant path",
            )
        )

    production_sequences = {
        sequence.sequence_id: sequence for sequence in production.visual_sequences
    }
    required_ids = {
        sequence.sequence_id
        for sequence in production.visual_sequences
        if sequence.primary_route == "local"
    }
    counts = Counter(sequence.sequence_id for sequence in local.sequences)
    for sequence_id, count in counts.items():
        if count > 1:
            issues.append(
                SequencePlanIssue(
                    "duplicate_local_sequence",
                    f"local sequence {sequence_id} is declared {count} times",
                    sequence_id=sequence_id,
                )
            )
    for sequence_id in sorted(required_ids):
        if counts[sequence_id] != 1:
            issues.append(
                SequencePlanIssue(
                    "missing_local_sequence",
                    f"local route sequence {sequence_id} must appear exactly once",
                    sequence_id=sequence_id,
                )
            )
    for sequence_id in sorted(set(counts) - required_ids):
        issues.append(
            SequencePlanIssue(
                "unexpected_local_sequence",
                f"sequence {sequence_id} is not routed to local rendering",
                sequence_id=sequence_id,
            )
        )

    all_scene_ids = [scene_id for sequence in local.sequences for scene_id in sequence.scene_ids]
    for scene_id, count in sorted(Counter(all_scene_ids).items()):
        if count > 1:
            issues.append(
                SequencePlanIssue(
                    "duplicate_local_scene",
                    f"scene {scene_id} appears {count} times in local sequences",
                    scene_id=scene_id,
                )
            )

    for sequence in local.sequences:
        common = production_sequences.get(sequence.sequence_id)
        if common is None:
            continue
        if sequence.scene_ids != common.scene_ids:
            issues.append(
                SequencePlanIssue(
                    "local_sequence_scene_mismatch",
                    f"local sequence {sequence.sequence_id} scenes do not match production",
                    sequence_id=sequence.sequence_id,
                )
            )
    return issues


def validate_scene_spans(
    local: LocalSequencePlan,
    script: ScriptArtifact,
) -> list[SequencePlanIssue]:
    issues: list[SequencePlanIssue] = []
    script_scenes = {scene.scene_id: scene for scene in script.scenes}
    final_scene_id = script.scenes[-1].scene_id if script.scenes else None
    timing_configured = local.defaults.scene_gap_seconds is not None
    for sequence in local.sequences:
        span_ids = [span.scene_id for span in sequence.scene_spans]
        if span_ids != sequence.scene_ids:
            issues.append(
                SequencePlanIssue(
                    "scene_span_coverage_mismatch",
                    f"sequence {sequence.sequence_id} scene_spans must match scene_ids",
                    sequence_id=sequence.sequence_id,
                )
            )
        for scene_id, count in Counter(span_ids).items():
            if count > 1:
                issues.append(
                    SequencePlanIssue(
                        "duplicate_scene_span",
                        f"scene {scene_id} has {count} spans",
                        sequence_id=sequence.sequence_id,
                        scene_id=scene_id,
                    )
                )

        cursor = 0
        for span in sequence.scene_spans:
            if span.start_frame > cursor:
                issues.append(
                    SequencePlanIssue(
                        "scene_span_gap",
                        f"sequence {sequence.sequence_id} has a gap before frame {span.start_frame}",
                        sequence_id=sequence.sequence_id,
                        scene_id=span.scene_id,
                    )
                )
            elif span.start_frame < cursor:
                issues.append(
                    SequencePlanIssue(
                        "scene_span_overlap",
                        f"sequence {sequence.sequence_id} scene spans overlap",
                        sequence_id=sequence.sequence_id,
                        scene_id=span.scene_id,
                    )
                )
            cursor = max(cursor, span.end_frame)

            if not (
                span.start_frame <= span.audio_start_frame
                < span.audio_end_frame <= span.end_frame
            ):
                issues.append(
                    SequencePlanIssue(
                        "audio_span_out_of_bounds",
                        f"scene {span.scene_id} audio must stay within its scene span",
                        sequence_id=sequence.sequence_id,
                        scene_id=span.scene_id,
                    )
                )
            if span.audio_start_frame != span.start_frame:
                issues.append(
                    SequencePlanIssue(
                        "audio_start_mismatch",
                        f"scene {span.scene_id} audio must start at its scene boundary",
                        sequence_id=sequence.sequence_id,
                        scene_id=span.scene_id,
                    )
                )
            if span.tail_silence_frames != span.end_frame - span.audio_end_frame:
                issues.append(
                    SequencePlanIssue(
                        "tail_silence_mismatch",
                        f"scene {span.scene_id} tail silence does not match its frame range",
                        sequence_id=sequence.sequence_id,
                        scene_id=span.scene_id,
                    )
                )
            if timing_configured:
                assert local.defaults.min_scene_seconds is not None
                assert local.defaults.max_scene_seconds is not None
                assert local.defaults.scene_gap_seconds is not None
                span_seconds = (
                    span.end_frame - span.start_frame
                ) / local.defaults.fps
                if span_seconds < local.defaults.min_scene_seconds:
                    issues.append(
                        SequencePlanIssue(
                            "local_scene_too_short",
                            f"scene {span.scene_id} local span is below "
                            f"{local.defaults.min_scene_seconds} seconds",
                            sequence_id=sequence.sequence_id,
                            scene_id=span.scene_id,
                        )
                    )
                if span_seconds >= local.defaults.max_scene_seconds:
                    issues.append(
                        SequencePlanIssue(
                            "local_scene_too_long",
                            f"scene {span.scene_id} local span must stay below "
                            f"{local.defaults.max_scene_seconds} seconds",
                            sequence_id=sequence.sequence_id,
                            scene_id=span.scene_id,
                        )
                    )
                expected_tail = (
                    0
                    if span.scene_id == final_scene_id
                    else round(
                        local.defaults.scene_gap_seconds * local.defaults.fps
                    )
                )
                if span.tail_silence_frames != expected_tail:
                    issues.append(
                        SequencePlanIssue(
                            "scene_gap_mismatch",
                            f"scene {span.scene_id} tail silence must be "
                            f"{expected_tail} configured frames",
                            sequence_id=sequence.sequence_id,
                            scene_id=span.scene_id,
                        )
                    )

            scene = script_scenes.get(span.scene_id)
            if scene is None:
                issues.append(
                    SequencePlanIssue(
                        "unknown_script_scene",
                        f"scene {span.scene_id} is absent from the script",
                        sequence_id=sequence.sequence_id,
                        scene_id=span.scene_id,
                    )
                )
                continue
            try:
                required_frames = canonical_audio_frames(scene, local.defaults.fps)
            except ValueError as error:
                issues.append(
                    SequencePlanIssue(
                        "missing_scene_duration",
                        str(error),
                        sequence_id=sequence.sequence_id,
                        scene_id=span.scene_id,
                    )
                )
            else:
                if span.audio_end_frame - span.audio_start_frame < required_frames:
                    issues.append(
                        SequencePlanIssue(
                            "audio_span_too_short",
                            f"scene {span.scene_id} audio span is shorter than {required_frames} frames",
                            sequence_id=sequence.sequence_id,
                            scene_id=span.scene_id,
                        )
                    )

        if cursor != sequence.duration_frames:
            issues.append(
                SequencePlanIssue(
                    "scene_span_duration_mismatch",
                    f"sequence {sequence.sequence_id} scene spans end at {cursor}, not {sequence.duration_frames}",
                    sequence_id=sequence.sequence_id,
                )
            )
    return issues


def _timeline_has_gap(intervals: list[tuple[int, int]], duration_frames: int) -> bool:
    cursor = 0
    for start, end in sorted(intervals):
        if end <= cursor:
            continue
        if start > cursor:
            return True
        cursor = max(cursor, end)
    return cursor < duration_frames


def _intervals_cover_range(
    intervals: list[tuple[int, int]], start_frame: int, end_frame: int
) -> bool:
    cursor = start_frame
    for start, end in sorted(intervals):
        if end <= cursor:
            continue
        if start > cursor:
            return False
        cursor = max(cursor, end)
    return cursor >= end_frame


def _simulation_time_at(beat: SequenceTimelineBeat, frame: int) -> float:
    start_frame = beat.start_frame
    end_frame = beat.end_frame
    progress = (frame - start_frame) / (end_frame - start_frame)
    return beat.simulation_time_start + progress * (
        beat.simulation_time_end - beat.simulation_time_start
    )


def _effective_clock_beat(
    beats: list[SequenceTimelineBeat],
) -> SequenceTimelineBeat:
    return max(beats, key=lambda beat: (beat.priority, beat.beat_id))


def validate_local_timelines(
    production: ProductionPlan,
    local: LocalSequencePlan,
) -> list[SequencePlanIssue]:
    issues: list[SequencePlanIssue] = []
    common_sequences = {
        sequence.sequence_id: sequence for sequence in production.visual_sequences
    }
    common_beats = {beat.beat_id: beat for beat in production.visual_beats}
    for sequence in local.sequences:
        common_sequence = common_sequences.get(sequence.sequence_id)
        timeline_ids = [beat.beat_id for beat in sequence.timeline]
        if common_sequence is not None and Counter(timeline_ids) != Counter(
            common_sequence.visual_beat_ids
        ):
            issues.append(
                SequencePlanIssue(
                    "local_beat_coverage_mismatch",
                    f"sequence {sequence.sequence_id} timeline beats do not match production",
                    sequence_id=sequence.sequence_id,
                )
            )

        intervals: list[tuple[int, int]] = []
        ordered_beats = sorted(
            sequence.timeline,
            key=lambda beat: (beat.start_frame, beat.end_frame, beat.beat_id),
        )
        scene_spans = {span.scene_id: span for span in sequence.scene_spans}
        last_beat_ids: dict[int, str] = {}
        if common_sequence is not None:
            for scene_id in common_sequence.scene_ids:
                candidates = [
                    common_beats[beat_id]
                    for beat_id in common_sequence.visual_beat_ids
                    if beat_id in common_beats
                    and common_beats[beat_id].scene_id == scene_id
                ]
                if candidates:
                    last_beat_ids[scene_id] = max(
                        candidates,
                        key=lambda item: (
                            item.end_frame,
                            item.start_frame,
                            item.beat_id,
                        ),
                    ).beat_id
        prior_start_times: list[float] = []
        for beat in ordered_beats:
            intervals.append((beat.start_frame, beat.end_frame))
            if beat.start_frame < 0 or beat.end_frame > sequence.duration_frames:
                issues.append(
                    SequencePlanIssue(
                        "local_timeline_out_of_bounds",
                        f"beat {beat.beat_id} falls outside sequence {sequence.sequence_id}",
                        sequence_id=sequence.sequence_id,
                        beat_id=beat.beat_id,
                    )
                )
            common_beat = common_beats.get(beat.beat_id)
            if common_beat is None:
                issues.append(
                    SequencePlanIssue(
                        "unknown_local_beat",
                        f"beat {beat.beat_id} is absent from production",
                        sequence_id=sequence.sequence_id,
                        beat_id=beat.beat_id,
                    )
                )
            else:
                owning_span = scene_spans.get(common_beat.scene_id)
                extends_configured_tail = (
                    owning_span is not None
                    and beat.beat_id == last_beat_ids.get(common_beat.scene_id)
                    and common_beat.end_frame == owning_span.audio_end_frame
                    and beat.end_frame == owning_span.end_frame
                )
                if beat.start_frame != common_beat.start_frame or (
                    beat.end_frame != common_beat.end_frame
                    and not extends_configured_tail
                ):
                    issues.append(
                        SequencePlanIssue(
                            "local_beat_range_mismatch",
                            f"beat {beat.beat_id} frame range does not match production "
                            "or its configured local tail",
                            sequence_id=sequence.sequence_id,
                            beat_id=beat.beat_id,
                        )
                    )
            if common_beat is not None:
                owning_span = scene_spans.get(common_beat.scene_id)
                if owning_span is None or not (
                    owning_span.start_frame
                    <= beat.start_frame
                    < beat.end_frame
                    <= owning_span.end_frame
                ):
                    issues.append(
                        SequencePlanIssue(
                            "local_beat_scene_span_mismatch",
                            f"beat {beat.beat_id} falls outside its owning scene span",
                            sequence_id=sequence.sequence_id,
                            scene_id=common_beat.scene_id,
                            beat_id=beat.beat_id,
                        )
                    )

            if beat.simulation_time_end < beat.simulation_time_start:
                issues.append(
                    SequencePlanIssue(
                        "simulation_time_reversal",
                        f"beat {beat.beat_id} reverses simulation time",
                        sequence_id=sequence.sequence_id,
                        beat_id=beat.beat_id,
                    )
                )
            completed_time_ends = [
                candidate.simulation_time_end
                for candidate in ordered_beats
                if candidate.end_frame <= beat.start_frame
            ]
            if (
                prior_start_times
                and beat.simulation_time_start < max(prior_start_times)
            ) or (
                completed_time_ends
                and beat.simulation_time_start < max(completed_time_ends)
            ):
                issues.append(
                    SequencePlanIssue(
                        "simulation_time_reversal",
                        f"simulation time reverses before beat {beat.beat_id}",
                        sequence_id=sequence.sequence_id,
                        beat_id=beat.beat_id,
                    )
                )
            prior_start_times.append(beat.simulation_time_start)

            if beat.simulation_time_end == beat.simulation_time_start:
                if beat.hold_intent is None or not beat.hold_intent.strip():
                    issues.append(
                        SequencePlanIssue(
                            "missing_hold_intent",
                            f"hold beat {beat.beat_id} requires hold_intent",
                            sequence_id=sequence.sequence_id,
                            beat_id=beat.beat_id,
                        )
                    )
                if beat.end_frame - beat.start_frame > 2 * local.defaults.fps:
                    issues.append(
                        SequencePlanIssue(
                            "hold_too_long",
                            f"hold beat {beat.beat_id} exceeds two seconds",
                            sequence_id=sequence.sequence_id,
                            beat_id=beat.beat_id,
                        )
                    )

        clock_beats = [
            beat for beat in ordered_beats if "simulation_clock" in beat.patch_targets
        ]
        clock_boundaries = sorted(
            {frame for beat in clock_beats for frame in (beat.start_frame, beat.end_frame)}
        )
        for frame in clock_boundaries:
            active_before = [
                beat
                for beat in clock_beats
                if beat.start_frame < frame <= beat.end_frame
            ]
            active_after = [
                beat
                for beat in clock_beats
                if beat.start_frame <= frame < beat.end_frame
            ]
            if not active_before or not active_after:
                continue
            before = _effective_clock_beat(active_before)
            after = _effective_clock_beat(active_after)
            if _simulation_time_at(after, frame) < _simulation_time_at(before, frame):
                issues.append(
                    SequencePlanIssue(
                        "simulation_time_reversal",
                        f"effective simulation clock reverses at frame {frame}",
                        sequence_id=sequence.sequence_id,
                        beat_id=after.beat_id,
                    )
                )

        if _timeline_has_gap(intervals, sequence.duration_frames):
            issues.append(
                SequencePlanIssue(
                    "local_timeline_gap",
                    f"sequence {sequence.sequence_id} timeline does not cover every frame",
                    sequence_id=sequence.sequence_id,
                )
            )

        for index, left in enumerate(sequence.timeline):
            for right in sequence.timeline[index + 1 :]:
                overlaps = max(left.start_frame, right.start_frame) < min(
                    left.end_frame, right.end_frame
                )
                shared_targets = set(left.patch_targets) & set(right.patch_targets)
                if overlaps and shared_targets and left.priority == right.priority:
                    issues.append(
                        SequencePlanIssue(
                            "ambiguous_patch_priority",
                            f"beats {left.beat_id} and {right.beat_id} overlap shared targets at equal priority",
                            sequence_id=sequence.sequence_id,
                            beat_id=right.beat_id,
                        )
                    )
    return issues


def validate_eclipse_explanation_design(
    production: ProductionPlan,
    local: LocalSequencePlan,
) -> list[SequencePlanIssue]:
    issues: list[SequencePlanIssue] = []
    common_beats = {beat.beat_id: beat for beat in production.visual_beats}
    for sequence in local.sequences:
        for controller, close_view_mode in ECLIPSE_EXPLANATION_CLOSE_VIEWS.items():
            controller_beats = [
                beat for beat in sequence.timeline if beat.controller == controller
            ]
            if not controller_beats:
                continue

            wide_beats = [
                beat
                for beat in controller_beats
                if beat.controller_options.get("view_mode") == "wide_alignment"
            ]
            close_beats = [
                beat
                for beat in controller_beats
                if beat.controller_options.get("view_mode") == close_view_mode
            ]
            wide_beats.sort(
                key=lambda beat: (beat.start_frame, beat.end_frame, beat.beat_id)
            )
            close_beats.sort(
                key=lambda beat: (beat.start_frame, beat.end_frame, beat.beat_id)
            )
            if not wide_beats and not close_beats:
                issues.append(
                    SequencePlanIssue(
                        "eclipse_explanation_missing_wide",
                        f"{controller} requires a wide_alignment context beat",
                        sequence_id=sequence.sequence_id,
                    )
                )
                issues.append(
                    SequencePlanIssue(
                        "eclipse_explanation_missing_close",
                        f"{controller} requires a {close_view_mode} mechanism beat",
                        sequence_id=sequence.sequence_id,
                    )
                )
                continue

            pair_count = min(len(wide_beats), len(close_beats))
            for wide, close in zip(
                wide_beats[:pair_count],
                close_beats[:pair_count],
                strict=True,
            ):
                wide_common = common_beats.get(wide.beat_id)
                close_common = common_beats.get(close.beat_id)
                if wide_common is None or close_common is None:
                    continue
                if wide_common.scene_id != close_common.scene_id:
                    issues.append(
                        SequencePlanIssue(
                            "eclipse_explanation_scene_mismatch",
                            f"{controller} context and mechanism beats must share a scene",
                            sequence_id=sequence.sequence_id,
                            scene_id=close_common.scene_id,
                            beat_id=close.beat_id,
                        )
                    )
                    continue
                if wide.end_frame > close.start_frame:
                    issues.append(
                        SequencePlanIssue(
                            "eclipse_explanation_order_mismatch",
                            f"{controller} wide context must precede its mechanism close-up",
                            sequence_id=sequence.sequence_id,
                            scene_id=close_common.scene_id,
                            beat_id=close.beat_id,
                        )
                    )
                    continue
                if wide.end_frame != close.start_frame:
                    issues.append(
                        SequencePlanIssue(
                            "eclipse_explanation_gap",
                            f"{controller} context and mechanism beats must be contiguous",
                            sequence_id=sequence.sequence_id,
                            scene_id=close_common.scene_id,
                            beat_id=close.beat_id,
                        )
                    )

            for close in close_beats[pair_count:]:
                common = common_beats.get(close.beat_id)
                issues.append(
                    SequencePlanIssue(
                        "eclipse_explanation_missing_wide",
                        f"{controller} mechanism beat requires a preceding wide_alignment beat",
                        sequence_id=sequence.sequence_id,
                        scene_id=common.scene_id if common is not None else None,
                        beat_id=close.beat_id,
                    )
                )
            for wide in wide_beats[pair_count:]:
                common = common_beats.get(wide.beat_id)
                issues.append(
                    SequencePlanIssue(
                        "eclipse_explanation_missing_close",
                        f"{controller} wide beat requires a following {close_view_mode} beat",
                        sequence_id=sequence.sequence_id,
                        scene_id=common.scene_id if common is not None else None,
                        beat_id=wide.beat_id,
                    )
                )
    return issues


def validate_online_coverage(
    production: ProductionPlan,
    local: LocalSequencePlan,
    online: OnlinePlan,
) -> list[SequencePlanIssue]:
    issues: list[SequencePlanIssue] = []
    common_sequences = {
        sequence.sequence_id: sequence for sequence in production.visual_sequences
    }
    common_beats = {beat.beat_id: beat for beat in production.visual_beats}
    beat_sequence_ids = {
        beat_id: sequence.sequence_id
        for sequence in production.visual_sequences
        for beat_id in sequence.visual_beat_ids
    }
    local_sequences = {sequence.sequence_id: sequence for sequence in local.sequences}
    precise_owners = {"simulation", "deterministic_overlay"}
    artifact_owners: dict[PurePosixPath, list[str]] = {}
    for shot in online.shots:
        for artifact_kind, value in (
            ("prompt", shot.prompt_file),
            ("metadata", shot.metadata_file),
        ):
            artifact_owners.setdefault(PurePosixPath(value), []).append(
                f"{shot.online_shot_id} {artifact_kind}"
            )
    for path, owners in artifact_owners.items():
        if len(owners) > 1:
            issues.append(
                SequencePlanIssue(
                    "duplicate_online_artifact_path",
                    f"online artifact path {path} is shared by {', '.join(owners)}",
                )
            )

    shot_counts = Counter(shot.online_shot_id for shot in online.shots)
    for shot_id, count in shot_counts.items():
        if count > 1:
            issues.append(
                SequencePlanIssue(
                    "duplicate_online_shot",
                    f"online shot {shot_id} is declared {count} times",
                )
            )

    coverage: dict[str, list] = {beat_id: [] for beat_id in common_beats}
    fps = local.defaults.fps
    for shot in online.shots:
        for beat_id in shot.beat_ids:
            if beat_id in coverage:
                coverage[beat_id].append(shot)
            else:
                issues.append(
                    SequencePlanIssue(
                        "unknown_online_beat",
                        f"online shot {shot.online_shot_id} references unknown beat {beat_id}",
                        beat_id=beat_id,
                    )
                )

        common_sequence = common_sequences.get(shot.source_sequence_id)
        if common_sequence is None:
            issues.append(
                SequencePlanIssue(
                    "unknown_source_sequence",
                    f"online shot {shot.online_shot_id} references unknown sequence {shot.source_sequence_id}",
                    sequence_id=shot.source_sequence_id,
                )
            )
        else:
            source_beat_ids = set(common_sequence.visual_beat_ids)
            if any(beat_id not in source_beat_ids for beat_id in shot.beat_ids):
                issues.append(
                    SequencePlanIssue(
                        "online_beat_sequence_mismatch",
                        f"online shot {shot.online_shot_id} includes a beat from another sequence",
                        sequence_id=shot.source_sequence_id,
                    )
                )
            declared_beats = [
                common_beats[beat_id]
                for beat_id in shot.beat_ids
                if beat_id in common_beats
            ]
            if any(
                beat.relationship_owner in precise_owners for beat in declared_beats
            ):
                valid_local_reference = (
                    shot.preferred_mode == "v2v"
                    and shot.reference_video_file is not None
                    and _is_under(
                        shot.reference_video_file,
                        ("videoFiles", "onlineReferences"),
                    )
                )
                if (
                    shot.science_authority == "local_reference"
                    and not valid_local_reference
                ) or (
                    shot.preferred_mode != "v2v"
                    and shot.science_authority != "advisory_only"
                ):
                    issues.append(
                        SequencePlanIssue(
                            "invalid_science_authority",
                            f"precise online shot {shot.online_shot_id} has invalid science authority",
                            sequence_id=shot.source_sequence_id,
                        )
                    )
            expected_scene_ids = list(dict.fromkeys(beat.scene_id for beat in declared_beats))
            if shot.scene_ids != expected_scene_ids:
                issues.append(
                    SequencePlanIssue(
                        "online_scene_coverage_mismatch",
                        f"online shot {shot.online_shot_id} scene_ids do not match its beats",
                        sequence_id=shot.source_sequence_id,
                    )
                )
            if any(
                shot.source_end_frame <= beat.start_frame
                or shot.source_start_frame >= beat.end_frame
                for beat in declared_beats
            ):
                issues.append(
                    SequencePlanIssue(
                        "online_source_range_mismatch",
                        f"online shot {shot.online_shot_id} does not intersect every declared beat",
                        sequence_id=shot.source_sequence_id,
                    )
                )

            local_sequence = local_sequences.get(shot.source_sequence_id)
            if (
                local_sequence is not None
                and shot.source_end_frame > local_sequence.duration_frames
            ):
                issues.append(
                    SequencePlanIssue(
                        "online_source_range_mismatch",
                        f"online shot {shot.online_shot_id} exceeds its local source sequence",
                        sequence_id=shot.source_sequence_id,
                    )
                )

        duration_frames = shot.source_end_frame - shot.source_start_frame
        if abs(shot.duration_seconds * fps - duration_frames) > 1:
            issues.append(
                SequencePlanIssue(
                    "online_duration_mismatch",
                    f"online shot {shot.online_shot_id} duration differs from its source frames",
                    sequence_id=shot.source_sequence_id,
                )
            )
        if shot.duration_seconds < 4 and (
            shot.short_shot_reason is None or not shot.short_shot_reason.strip()
        ):
            issues.append(
                SequencePlanIssue(
                    "missing_short_shot_reason",
                    f"online shot {shot.online_shot_id} is below four seconds without a reason",
                    sequence_id=shot.source_sequence_id,
                )
            )

        prompt_ok = _is_under(
            shot.prompt_file, ("videoFiles", "prompts", "online")
        )
        metadata_ok = _is_under(
            shot.metadata_file, ("videoFiles", "prompts", "online")
        )
        if prompt_ok and metadata_ok:
            metadata_ok = (
                PurePosixPath(shot.metadata_file).parent
                == PurePosixPath(shot.prompt_file).parent
            )
        video_reference_ok = shot.reference_video_file is None or _is_under(
            shot.reference_video_file, ("videoFiles", "onlineReferences")
        )
        image_references_ok = all(
            _is_relative_descendant(path) for path in shot.reference_image_files
        )
        if not (prompt_ok and metadata_ok and video_reference_ok and image_references_ok):
            issues.append(
                SequencePlanIssue(
                    "invalid_online_path",
                    f"online shot {shot.online_shot_id} contains an invalid declared path",
                    sequence_id=shot.source_sequence_id,
                )
            )
        if shot.preferred_mode == "v2v" and shot.reference_video_file is None:
            issues.append(
                SequencePlanIssue(
                    "missing_v2v_reference",
                    f"online shot {shot.online_shot_id} requires a video reference",
                    sequence_id=shot.source_sequence_id,
                )
            )
        if shot.science_authority == "reference_frame" and not shot.reference_image_files:
            issues.append(
                SequencePlanIssue(
                    "missing_reference_image",
                    f"online shot {shot.online_shot_id} requires a reference image",
                    sequence_id=shot.source_sequence_id,
                )
            )

    for beat_id, shots in coverage.items():
        beat = common_beats[beat_id]
        owning_sequence_id = beat_sequence_ids.get(beat_id)
        intervals = [
            (
                max(shot.source_start_frame, beat.start_frame),
                min(shot.source_end_frame, beat.end_frame),
            )
            for shot in shots
            if shot.source_sequence_id == owning_sequence_id
            and shot.source_start_frame < beat.end_frame
            and shot.source_end_frame > beat.start_frame
        ]
        if not intervals:
            issues.append(
                SequencePlanIssue(
                    "missing_online_beat",
                    f"production beat {beat_id} has no online shot coverage",
                    sequence_id=owning_sequence_id,
                    scene_id=beat.scene_id,
                    beat_id=beat_id,
                )
            )
        elif not _intervals_cover_range(intervals, beat.start_frame, beat.end_frame):
            issues.append(
                SequencePlanIssue(
                    "incomplete_online_beat",
                    f"production beat {beat_id} is not fully covered by online shots",
                    sequence_id=owning_sequence_id,
                    scene_id=beat.scene_id,
                    beat_id=beat_id,
                )
            )

    for sequence in production.visual_sequences:
        if sequence.primary_route != "local":
            continue
        for beat_id in sequence.visual_beat_ids:
            beat = common_beats.get(beat_id)
            if beat is None or beat.relationship_owner not in precise_owners:
                continue
            has_local_reference = any(
                shot.source_sequence_id == sequence.sequence_id
                and shot.preferred_mode == "v2v"
                and shot.science_authority == "local_reference"
                and shot.reference_video_file is not None
                for shot in coverage.get(beat_id, [])
            )
            if not has_local_reference:
                issues.append(
                    SequencePlanIssue(
                        "missing_local_v2v_reference",
                        f"precise beat {beat_id} lacks a local V2V reference",
                        sequence_id=sequence.sequence_id,
                        scene_id=beat.scene_id,
                        beat_id=beat_id,
                    )
                )
    return issues
