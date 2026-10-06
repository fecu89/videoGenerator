from __future__ import annotations

import argparse
import copy
import math
import shutil
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from .models import ScriptArtifact
from .production import (
    load_production_plan,
    script_sha256,
    validate_plan_against_script,
)
from .production_models import (
    CompositeShot,
    GeneratedShot,
    ProductionPlan,
    ProductionShot,
    SimulationShot,
)
from .production_review import render_video_plan
from .prompt_compiler import write_compiled_artifacts
from .simulation import SimulationConfig, load_simulation
from .sequence_models import (
    MAX_ONLINE_SHOT_SECONDS,
    LocalSequencePlan,
    OnlinePlan,
)
from .sequence_plans import (
    canonical_audio_frames,
    load_local_sequence_plan,
    load_online_plan,
    validate_sequence_plans,
)
from .settings import LocalVideoSettings, resolve_run_settings
from .storage import RunStore, atomic_write, fingerprint, scene_filename
from .variants import (
    SequenceVariantPlan,
    VariantPlan,
    load_variant_plan,
    validate_sequence_variant_plan,
    validate_variant_plan,
)


TEMPLATE_RELATIONSHIP = {
    "sky-orbit-reveal": "projection_intersection",
    "retrograde-track": "projection_intersection",
    "moving-observer": "path_membership",
    "sightline-angle": "attached_line",
    "speed-comparison": "path_membership",
    "earth-overtake": "fixed_distance",
    "projection-proof": "projection_intersection",
    "return-to-direct": "projection_intersection",
}


def _require_audio_ready(run_dir: Path, script: ScriptArtifact) -> None:
    for scene in script.scenes:
        if scene.duration_seconds is None:
            raise ValueError(f"scene {scene.scene_id} duration_seconds is required")
        if not scene.audio_file:
            raise ValueError(f"scene {scene.scene_id} audio_file is required")
        expected = f"audioFiles/{scene_filename(scene, '.mp3')}"
        if scene.audio_file != expected:
            raise ValueError(f"scene {scene.scene_id} audio_file must be {expected}")
        if not (run_dir / scene.audio_file).is_file():
            raise ValueError(f"scene {scene.scene_id} audio file is missing: {scene.audio_file}")


def _base_shot(scene, shot_id: str, render_mode: str) -> dict:
    duration = float(scene.duration_seconds)
    event = " ".join(scene.visual_subject.replace(";", ",").splitlines()).strip()
    return {
        "shot_id": shot_id,
        "title": scene.title,
        "duration_seconds": duration,
        "render_mode": render_mode,
        "purpose": scene.visual_subject,
        "single_event": event,
        "coordinate_space": {
            "type": "semantic",
            "frame_id": "shot_composition",
            "screen_convention": "viewer-facing horizontal frame",
        },
        "entities": [],
        "paths": [],
        "start_state": {"at_seconds": 0.0, "entities": {}},
        "end_state": {"at_seconds": duration, "entities": {}},
        "invariants": ["대상의 형태와 배경 조건이 장면 전체에서 유지된다"],
        "motion_contract": {"primary_event": event, "tracks": []},
        "camera": {
            "projection": "perspective",
            "framing": "clear knowledge-video composition",
            "movement": "locked",
        },
        "assets": {},
        "relationships": [],
        "dependencies": [],
        "excluded_elements": ["subtitles", "logos", "watermarks"],
    }


def build_legacy_generated_plan(
    run_dir: Path,
    script: ScriptArtifact,
) -> ProductionPlan:
    scenes = []
    for scene in script.scenes:
        shot_id = f"{scene.scene_id:02d}A"
        shot = _base_shot(scene, shot_id, "generated")
        shot["generation"] = {
            "mode": "t2v",
            "prompt_file": f"videoPrompt/{scene_filename(scene, '.txt').replace(f'{scene.scene_id:02d}_', f'{shot_id}_', 1)}",
            "inbox_file": f"shotFiles/inbox/{scene_filename(scene, '.mp4').replace(f'{scene.scene_id:02d}_', f'{shot_id}_', 1)}",
        }
        scenes.append(
            {
                "scene_id": scene.scene_id,
                "duration_seconds": scene.duration_seconds,
                "shots": [shot],
            }
        )
    return ProductionPlan.model_validate(
        {
            "schema_version": 1,
            "script_sha256": script_sha256(run_dir / "script.json"),
            "defaults": {
                "width": 1920,
                "height": 1080,
                "fps": 30,
                "preview_interval_seconds": 2.0,
            },
            "style_bible": {
                "visual_mode": "realistic knowledge-video cinematography",
                "entities": [],
                "palette": [],
                "lighting": "natural stable lighting",
                "excluded_elements": ["logos", "watermarks"],
            },
            "scenes": scenes,
        }
    )


def _simulation_shot(scene, simulation_scene, config: SimulationConfig) -> dict:
    shot_id = f"{scene.scene_id:02d}A"
    duration = float(scene.duration_seconds)
    relationship_type = TEMPLATE_RELATIONSHIP[simulation_scene.template]
    relationship_entities = (
        ["earth"]
        if simulation_scene.template == "moving-observer"
        else ["earth", "mars"]
    )
    return {
        "shot_id": shot_id,
        "title": scene.title,
        "duration_seconds": duration,
        "render_mode": "simulation",
        "purpose": scene.visual_subject,
        "single_event": scene.visual_subject,
        "coordinate_space": {
            "type": "world_3d",
            "frame_id": "heliocentric_ecliptic",
            "origin": "sun.center",
            "positive_x": "opposition direction at simulation day zero",
            "positive_y": "90 degrees counterclockwise in the orbital plane",
            "positive_z": "north ecliptic pole",
            "screen_convention": "north ecliptic pole viewed from positive z; apparent sky track is left to right to left",
        },
        "entities": [
            {
                "entity_id": "earth",
                "anchor": "center",
                "identity_ref": "earth-v1",
                "path_id": "earth_orbit",
            },
            {
                "entity_id": "mars",
                "anchor": "center",
                "identity_ref": "mars-v1",
                "path_id": "mars_orbit",
            },
        ],
        "paths": [
            {
                "path_id": "earth_orbit",
                "type": "circle",
                "center": "sun.center",
                "radius": config.physics.earth_orbit_radius,
                "plane": "heliocentric_ecliptic",
            },
            {
                "path_id": "mars_orbit",
                "type": "circle",
                "center": "sun.center",
                "radius": config.physics.mars_orbit_radius,
                "plane": "heliocentric_ecliptic",
            },
        ],
        "start_state": {
            "at_seconds": 0.0,
            "simulation_time": simulation_scene.simulation_day_start,
            "entities": {},
        },
        "end_state": {
            "at_seconds": duration,
            "simulation_time": simulation_scene.simulation_day_end,
            "entities": {},
        },
        "invariants": [
            "지구와 화성은 북황극에서 본 반시계 방향으로 계속 공전한다",
            "별 배경은 고정되고 겉보기 경로는 왼쪽에서 오른쪽으로 갔다가 다시 왼쪽으로 향한다",
        ],
        "motion_contract": {
            "primary_event": simulation_scene.template,
            "tracks": [
                {
                    "entity_id": "earth",
                    "path_id": "earth_orbit",
                    "direction": "counterclockwise",
                    "rate_profile": "physics",
                    "rate_source": "physics.earth_period_days",
                },
                {
                    "entity_id": "mars",
                    "path_id": "mars_orbit",
                    "direction": "counterclockwise",
                    "rate_profile": "physics",
                    "rate_source": "physics.mars_period_days",
                },
            ],
        },
        "camera": {
            "projection": (
                "orthographic"
                if simulation_scene.camera in {"fixed-sky", "orbit-top"}
                else "perspective"
            ),
            "framing": simulation_scene.camera,
            "movement": "template-controlled",
            "orientation_convention": "north ecliptic pole is positive z",
            "screen_direction_convention": "northern-sky apparent motion convention",
        },
        "assets": {},
        "relationships": [
            {
                "relationship_id": f"{shot_id}_{relationship_type}",
                "type": relationship_type,
                "owner": "simulation",
                "entity_ids": relationship_entities,
            }
        ],
        "dependencies": [],
        "excluded_elements": ["subtitles", "logos", "watermarks"],
        "simulation": {
            "model": config.physics.model,
            "template": simulation_scene.template,
            "parameters": {
                **config.physics.model_dump(mode="json"),
                "simulation_day_start": simulation_scene.simulation_day_start,
                "simulation_day_end": simulation_scene.simulation_day_end,
            },
            "renderer_options": {
                "camera": simulation_scene.camera,
                "style": config.style.model_dump(mode="json"),
            },
        },
    }


def build_simulation_plan(
    run_dir: Path,
    script: ScriptArtifact,
    simulation: SimulationConfig,
) -> ProductionPlan:
    simulation_by_id = {scene.scene_id: scene for scene in simulation.scenes}
    scenes = [
        {
            "scene_id": scene.scene_id,
            "duration_seconds": scene.duration_seconds,
            "shots": [_simulation_shot(scene, simulation_by_id[scene.scene_id], simulation)],
        }
        for scene in script.scenes
    ]
    return ProductionPlan.model_validate(
        {
            "schema_version": 1,
            "script_sha256": script_sha256(run_dir / "script.json"),
            "defaults": {
                "width": simulation.output.width,
                "height": simulation.output.height,
                "fps": simulation.output.fps,
                "preview_interval_seconds": 2.0,
            },
            "style_bible": {
                "visual_mode": "hybrid scientific space explainer",
                "entities": [
                    {
                        "entity_id": "earth-v1",
                        "appearance_constraints": ["blue oceans", "white clouds"],
                        "reference_assets": [],
                    },
                    {
                        "entity_id": "mars-v1",
                        "appearance_constraints": ["rust red surface"],
                        "reference_assets": [],
                    },
                ],
                "palette": ["deep navy", "white", "rust red"],
                "lighting": "stable educational space lighting",
                "excluded_elements": ["logos", "watermarks"],
            },
            "scenes": scenes,
        }
    )


def _raise_plan_issues(plan: ProductionPlan, script: ScriptArtifact, run_dir: Path) -> None:
    issues = validate_plan_against_script(
        plan,
        script,
        run_dir / "script.json",
        run_dir,
    )
    if issues:
        details = "; ".join(f"{issue.code}: {issue.message}" for issue in issues)
        raise ValueError(details)


def _load_valid_variant_plan(
    run_dir: Path,
    production_plan: ProductionPlan,
) -> VariantPlan | None:
    path = run_dir / "variant-plan.json"
    if not path.is_file():
        return None
    variant_plan = load_variant_plan(path)
    issues = validate_variant_plan(
        variant_plan,
        production_plan,
        run_dir / "production-plan.json",
        run_dir / "script.json",
    )
    if issues:
        details = "; ".join(f"{issue.code}: {issue.message}" for issue in issues)
        raise ValueError(details)
    return variant_plan


def _raise_sequence_plan_issues(
    run_dir: Path,
    production: ProductionPlan,
    local: LocalSequencePlan,
    online: OnlinePlan,
    script: ScriptArtifact,
) -> None:
    issues = validate_sequence_plans(
        production,
        local,
        online,
        script,
        script_path=run_dir / "script.json",
        production_path=run_dir / "production-plan.json",
    )
    if issues:
        details = "; ".join(f"{issue.code}: {issue.message}" for issue in issues)
        raise ValueError(details)


def _legacy_plan_for_run(
    run_dir: Path,
    script: ScriptArtifact,
) -> tuple[ProductionPlan, SimulationConfig | None]:
    if (run_dir / "simulation.json").is_file():
        simulation = load_simulation(run_dir, script)
        return build_simulation_plan(run_dir, script, simulation), simulation
    return build_legacy_generated_plan(run_dir, script), None


def _relationship_owner(shot: ProductionShot) -> str:
    if isinstance(shot, SimulationShot):
        return "simulation"
    if shot.relationships:
        return shot.relationships[0].owner
    if isinstance(shot, GeneratedShot):
        return "generated_model"
    return "reference_frame"


def _generation_mode(shot: ProductionShot) -> str | None:
    if isinstance(shot, GeneratedShot):
        return shot.generation.mode
    if (
        isinstance(shot, CompositeShot)
        and shot.base.mode == "generated"
        and shot.base.generation is not None
    ):
        return shot.base.generation.mode
    return None


def _shot_reference_images(shot: ProductionShot) -> list[str]:
    return [
        path
        for path in (
            shot.assets.start_image,
            shot.assets.end_image,
            *shot.assets.reference_images,
        )
        if path is not None
    ]


def _scene_shot_ranges(scene, fps: int) -> list[tuple[ProductionShot, int, int]]:
    duration_frames = math.ceil(float(scene.duration_seconds) * fps)
    ranges: list[tuple[ProductionShot, int, int]] = []
    cursor = 0
    for index, shot in enumerate(scene.shots):
        end_frame = (
            duration_frames
            if index == len(scene.shots) - 1
            else min(
                duration_frames,
                cursor + max(1, round(shot.duration_seconds * fps)),
            )
        )
        ranges.append((shot, cursor, end_frame))
        cursor = end_frame
    return ranges


def _split_online_payload(
    payload: dict,
    *,
    fps: int,
) -> list[dict]:
    start_frame = payload["source_start_frame"]
    end_frame = payload["source_end_frame"]
    max_frames = max(1, math.floor(MAX_ONLINE_SHOT_SECONDS * fps))
    part_count = math.ceil((end_frame - start_frame) / max_frames)
    parts: list[dict] = []
    for index in range(part_count):
        part_start = start_frame + index * max_frames
        part_end = min(end_frame, part_start + max_frames)
        part = copy.deepcopy(payload)
        if part_count > 1:
            part["online_shot_id"] = (
                f"{payload['online_shot_id']}-P{index + 1:02d}"
            )
            part["prompt_file"] = (
                f"videoFiles/prompts/online/{payload['source_sequence_id']}/"
                f"{part['online_shot_id']}.txt"
            )
            part["metadata_file"] = (
                f"videoFiles/prompts/online/{payload['source_sequence_id']}/"
                f"{part['online_shot_id']}.json"
            )
            if part.get("reference_video_file") is not None:
                part["reference_video_file"] = (
                    f"videoFiles/onlineReferences/{part['online_shot_id']}.mp4"
                )
        part["source_start_frame"] = part_start
        part["source_end_frame"] = part_end
        part["duration_seconds"] = (part_end - part_start) / fps
        if part["duration_seconds"] < 4:
            part["short_shot_reason"] = part.get("short_shot_reason") or (
                "eight-second online segment boundary"
            )
        parts.append(part)
    return parts


def _retime_online_payloads(
    shot_payloads: list[dict],
    *,
    new_beat_ranges: dict[str, tuple[int, int]],
    production_beats: dict,
    fps: int,
) -> list[dict]:
    retimed: list[dict] = []
    for original in shot_payloads:
        beat_ids = original["beat_ids"]
        for beat_id in beat_ids:
            beat = production_beats[beat_id]
            payload = copy.deepcopy(original)
            if len(beat_ids) > 1:
                payload["online_shot_id"] = (
                    f"{original['online_shot_id']}-{beat_id}"
                )
            payload["beat_ids"] = [beat_id]
            payload["scene_ids"] = [beat.scene_id]
            payload["primary_event"] = beat.primary_event
            (
                payload["source_start_frame"],
                payload["source_end_frame"],
            ) = new_beat_ranges[beat_id]
            payload["prompt_file"] = (
                f"videoFiles/prompts/online/{payload['source_sequence_id']}/"
                f"{payload['online_shot_id']}.txt"
            )
            payload["metadata_file"] = (
                f"videoFiles/prompts/online/{payload['source_sequence_id']}/"
                f"{payload['online_shot_id']}.json"
            )
            if payload.get("reference_video_file") is not None:
                payload["reference_video_file"] = (
                    f"videoFiles/onlineReferences/{payload['online_shot_id']}.mp4"
                )
            retimed.extend(_split_online_payload(payload, fps=fps))
    return retimed


def _build_v2_production_plan(legacy: ProductionPlan) -> ProductionPlan:
    visual_sequences: list[dict] = []
    visual_beats: list[dict] = []
    beat_index = 1
    for scene_index, scene in enumerate(legacy.scenes, start=1):
        sequence_id = f"SEQ{scene_index:02d}"
        beat_ids: list[str] = []
        for shot, start_frame, end_frame in _scene_shot_ranges(
            scene,
            legacy.defaults.fps,
        ):
            beat_id = f"B{beat_index:02d}"
            beat_index += 1
            beat_ids.append(beat_id)
            visual_beats.append(
                {
                    "beat_id": beat_id,
                    "scene_id": scene.scene_id,
                    "start_frame": start_frame,
                    "end_frame": end_frame,
                    "primary_event": shot.motion_contract.primary_event,
                    "relationship_owner": _relationship_owner(shot),
                }
            )
        visual_sequences.append(
            {
                "sequence_id": sequence_id,
                "scene_ids": [scene.scene_id],
                "primary_route": (
                    "local"
                    if all(shot.render_mode == "simulation" for shot in scene.shots)
                    else "online_required"
                ),
                "purpose": " ".join(shot.purpose for shot in scene.shots),
                "visual_beat_ids": beat_ids,
            }
        )
    payload = legacy.model_dump(mode="json")
    payload.update(
        {
            "schema_version": 2,
            "scenes": [
                {
                    "scene_id": scene.scene_id,
                    "duration_seconds": scene.duration_seconds,
                    "shots": [],
                }
                for scene in legacy.scenes
            ],
            "visual_sequences": visual_sequences,
            "visual_beats": visual_beats,
        }
    )
    return ProductionPlan.model_validate(payload)


def _build_v2_execution_plans(
    production: ProductionPlan,
    legacy: ProductionPlan,
    production_hash: str,
    local_timing: LocalVideoSettings,
) -> tuple[LocalSequencePlan, OnlinePlan]:
    common_sequences = {
        sequence.scene_ids[0]: sequence for sequence in production.visual_sequences
    }
    common_beats = {beat.beat_id: beat for beat in production.visual_beats}
    local_sequences: list[dict] = []
    online_shots: list[dict] = []

    final_scene_id = legacy.scenes[-1].scene_id
    gap_frames = round(local_timing.scene_gap_seconds * legacy.defaults.fps)
    for scene in legacy.scenes:
        sequence = common_sequences[scene.scene_id]
        shot_ranges = _scene_shot_ranges(scene, legacy.defaults.fps)
        beat_ids = iter(sequence.visual_beat_ids)
        timeline: list[dict] = []
        for shot, start_frame, end_frame in shot_ranges:
            beat_id = next(beat_ids)
            if isinstance(shot, SimulationShot):
                simulation_start = shot.start_state.simulation_time
                simulation_end = shot.end_state.simulation_time
                if simulation_start is None:
                    simulation_start = start_frame / legacy.defaults.fps
                if simulation_end is None:
                    simulation_end = end_frame / legacy.defaults.fps
                timeline_beat = {
                    "beat_id": beat_id,
                    "start_frame": start_frame,
                    "end_frame": end_frame,
                    "simulation_time_start": simulation_start,
                    "simulation_time_end": simulation_end,
                    "controller": shot.simulation.template,
                    "patch_targets": [
                        "simulation_clock",
                        "geometry",
                        "layers",
                        "entities",
                        "camera",
                    ],
                    "priority": 0,
                    "controller_options": shot.simulation.renderer_options,
                }
                if simulation_start == simulation_end:
                    timeline_beat["hold_intent"] = "legacy simulation hold preserved"
                timeline.append(timeline_beat)

            preferred_mode = _generation_mode(shot) or "v2v"
            reference_images = _shot_reference_images(shot)
            online_shot_id = f"ON-{beat_id}"
            duration_seconds = shot.duration_seconds
            online_payload = {
                "online_shot_id": online_shot_id,
                "beat_ids": [beat_id],
                "scene_ids": [scene.scene_id],
                "source_sequence_id": sequence.sequence_id,
                "source_start_frame": start_frame,
                "source_end_frame": end_frame,
                "duration_seconds": duration_seconds,
                "preferred_mode": preferred_mode,
                "science_authority": (
                    "local_reference"
                    if preferred_mode == "v2v"
                    else ("reference_frame" if reference_images else "advisory_only")
                ),
                "primary_event": common_beats[beat_id].primary_event,
                "invariants": shot.invariants,
                "allowed_changes": (
                    ["materials", "lighting", "background density"]
                    if preferred_mode == "v2v"
                    else []
                ),
                "excluded_elements": shot.excluded_elements,
                "reference_image_files": reference_images,
                "reference_video_file": (
                    f"videoFiles/onlineReferences/{online_shot_id}.mp4"
                    if preferred_mode == "v2v"
                    else None
                ),
                "prompt_file": (
                    f"videoFiles/prompts/online/{sequence.sequence_id}/"
                    f"{online_shot_id}.txt"
                ),
                "metadata_file": (
                    f"videoFiles/prompts/online/{sequence.sequence_id}/"
                    f"{online_shot_id}.json"
                ),
            }
            if duration_seconds < 4:
                online_payload["short_shot_reason"] = "legacy shot boundary preserved"
            online_shots.extend(
                _split_online_payload(
                    online_payload,
                    fps=legacy.defaults.fps,
                )
            )

        if sequence.primary_route == "local":
            audio_frames = math.ceil(scene.duration_seconds * legacy.defaults.fps)
            tail_silence_frames = 0 if scene.scene_id == final_scene_id else gap_frames
            duration_frames = audio_frames + tail_silence_frames
            simulation_shot = scene.shots[0]
            if not isinstance(simulation_shot, SimulationShot):
                raise TypeError("local migrated sequence requires a simulation shot")
            if tail_silence_frames:
                last_timeline_beat = max(
                    timeline,
                    key=lambda item: (
                        item["end_frame"],
                        item["start_frame"],
                        item["beat_id"],
                    ),
                )
                last_timeline_beat["end_frame"] = duration_frames
            local_sequences.append(
                {
                    "sequence_id": sequence.sequence_id,
                    "scene_ids": [scene.scene_id],
                    "duration_frames": duration_frames,
                    "render_mode": "simulation",
                    "scene_graph": simulation_shot.simulation.template,
                    "scene_spans": [
                        {
                            "scene_id": scene.scene_id,
                            "start_frame": 0,
                            "end_frame": duration_frames,
                            "audio_start_frame": 0,
                            "audio_end_frame": audio_frames,
                            "tail_silence_frames": tail_silence_frames,
                        }
                    ],
                    "timeline": timeline,
                }
            )

    common = {
        "schema_version": 1,
        "script_sha256": production.script_sha256,
        "production_plan_sha256": production_hash,
    }
    local = LocalSequencePlan.model_validate(
        {
            **common,
            "defaults": {
                "width": production.defaults.width,
                "height": production.defaults.height,
                "fps": production.defaults.fps,
                "min_scene_seconds": local_timing.min_scene_seconds,
                "max_scene_seconds": local_timing.max_scene_seconds,
                "scene_gap_seconds": local_timing.scene_gap_seconds,
            },
            "simulation_config_file": "simulation.json",
            "sequences": local_sequences,
        }
    )
    online = OnlinePlan.model_validate({**common, "shots": online_shots})
    return local, online


def migrate_run(
    run_dir: Path,
    force: bool = False,
    *,
    schema_version: int = 2,
) -> ProductionPlan:
    if schema_version not in {1, 2}:
        raise ValueError("schema_version must be 1 or 2")
    run_dir = run_dir.resolve()
    store = RunStore.open(run_dir)
    destination = run_dir / "production-plan.json"
    if destination.exists() and not force:
        raise FileExistsError(f"production-plan.json already exists: {destination}")

    script = store.read_script()
    _require_audio_ready(run_dir, script)
    legacy_plan, simulation = _legacy_plan_for_run(run_dir, script)

    if schema_version == 1:
        _raise_plan_issues(legacy_plan, script, run_dir)
        store.ensure_production_directories()
        store.write_model("production-plan.json", legacy_plan)
        if simulation is not None:
            store.write_text("video-plan.md", render_video_plan(legacy_plan, script))
        else:
            write_compiled_artifacts(run_dir, legacy_plan, script)
        return legacy_plan

    plan = _build_v2_production_plan(legacy_plan)
    _raise_plan_issues(plan, script, run_dir)
    store.ensure_production_directories()
    store.write_model("production-plan.json", plan)
    production_hash = script_sha256(run_dir / "production-plan.json")
    resolved_settings = resolve_run_settings(run_dir)
    local_timing = getattr(
        resolved_settings,
        "local_video",
        LocalVideoSettings(),
    )
    local, online = _build_v2_execution_plans(
        plan,
        legacy_plan,
        production_hash,
        local_timing,
    )
    _raise_sequence_plan_issues(run_dir, plan, local, online, script)
    store.write_model("local-sequence-plan.json", local)
    store.write_model("online-plan.json", online)
    write_compiled_artifacts(
        run_dir,
        plan,
        script,
        local_plan=local,
        online_plan=online,
    )
    return plan


def _serialized_model(model) -> str:
    return model.model_dump_json(indent=2) + "\n"


def _retimed_v2_models(
    run_dir: Path,
    script: ScriptArtifact,
    production: ProductionPlan,
    local: LocalSequencePlan,
    online: OnlinePlan,
    local_timing: LocalVideoSettings,
) -> tuple[ProductionPlan, LocalSequencePlan, OnlinePlan]:
    if production.schema_version != 2:
        raise ValueError("retime-production requires a schema-v2 production plan")

    fps = production.defaults.fps
    script_by_id = {scene.scene_id: scene for scene in script.scenes}
    production_payload = production.model_dump(mode="json")
    local_payload = local.model_dump(mode="json")
    online_payload = online.model_dump(mode="json")
    local_by_id = {item.sequence_id: item for item in local.sequences}
    production_beats = {item.beat_id: item for item in production.visual_beats}
    final_scene_id = script.scenes[-1].scene_id
    gap_frames = round(local_timing.scene_gap_seconds * fps)

    new_scene_ranges: dict[tuple[str, int], tuple[int, int]] = {}
    new_audio_ranges: dict[tuple[str, int], tuple[int, int]] = {}
    new_beat_ranges: dict[str, tuple[int, int]] = {}
    beat_owners: dict[str, str] = {}
    for sequence in production.visual_sequences:
        for beat_id in sequence.visual_beat_ids:
            prior = beat_owners.setdefault(beat_id, sequence.sequence_id)
            if prior != sequence.sequence_id:
                raise ValueError(f"visual beat {beat_id} belongs to multiple sequences")

        existing_local = local_by_id.get(sequence.sequence_id)
        old_spans = (
            {
                span.scene_id: (span.audio_start_frame, span.audio_end_frame)
                for span in existing_local.scene_spans
            }
            if existing_local is not None
            else {}
        )
        cursor = 0
        for scene_id in sequence.scene_ids:
            scene = script_by_id.get(scene_id)
            if scene is None:
                raise ValueError(f"production sequence references unknown scene {scene_id}")
            duration_frames = canonical_audio_frames(scene, fps)
            new_start = cursor
            new_audio_end = new_start + duration_frames
            new_end = new_audio_end + (
                0 if scene_id == final_scene_id else gap_frames
            )
            new_audio_ranges[(sequence.sequence_id, scene_id)] = (
                new_start,
                new_audio_end,
            )
            new_scene_ranges[(sequence.sequence_id, scene_id)] = (
                new_start,
                new_end,
            )
            cursor = new_end

            scene_beats = [
                production_beats[beat_id]
                for beat_id in sequence.visual_beat_ids
                if production_beats[beat_id].scene_id == scene_id
            ]
            if not scene_beats:
                raise ValueError(
                    f"sequence {sequence.sequence_id} scene {scene_id} has no visual beat"
                )
            if scene_id in old_spans:
                old_start, old_end = old_spans[scene_id]
            else:
                old_start = min(beat.start_frame for beat in scene_beats)
                old_end = max(beat.end_frame for beat in scene_beats)
            if old_end <= old_start:
                raise ValueError(
                    f"sequence {sequence.sequence_id} scene {scene_id} has an invalid old range"
                )

            old_width = old_end - old_start
            new_width = new_audio_end - new_start
            for beat in scene_beats:
                scaled_start = new_start + round(
                    (beat.start_frame - old_start) * new_width / old_width
                )
                scaled_end = new_start + round(
                    (beat.end_frame - old_start) * new_width / old_width
                )
                scaled_start = min(max(new_start, scaled_start), new_audio_end - 1)
                scaled_end = min(max(scaled_start + 1, scaled_end), new_audio_end)
                new_beat_ranges[beat.beat_id] = (scaled_start, scaled_end)

    new_local_beat_ranges = dict(new_beat_ranges)
    for sequence in production.visual_sequences:
        for scene_id in sequence.scene_ids:
            scene_beats = [
                production_beats[beat_id]
                for beat_id in sequence.visual_beat_ids
                if production_beats[beat_id].scene_id == scene_id
            ]
            last_beat = max(
                scene_beats,
                key=lambda item: (
                    new_beat_ranges[item.beat_id][1],
                    new_beat_ranges[item.beat_id][0],
                    item.beat_id,
                ),
            )
            start_frame, _ = new_local_beat_ranges[last_beat.beat_id]
            _, scene_end = new_scene_ranges[(sequence.sequence_id, scene_id)]
            new_local_beat_ranges[last_beat.beat_id] = (start_frame, scene_end)

    production_payload["script_sha256"] = script_sha256(run_dir / "script.json")
    for scene_payload in production_payload["scenes"]:
        scene_payload["duration_seconds"] = script_by_id[
            scene_payload["scene_id"]
        ].duration_seconds
    for beat_payload in production_payload["visual_beats"]:
        beat_payload["start_frame"], beat_payload["end_frame"] = new_beat_ranges[
            beat_payload["beat_id"]
        ]
    retimed_production = ProductionPlan.model_validate(production_payload)
    production_hash = fingerprint(_serialized_model(retimed_production))

    local_payload["script_sha256"] = production_payload["script_sha256"]
    local_payload["production_plan_sha256"] = production_hash
    local_payload["defaults"].update(
        {
            "min_scene_seconds": local_timing.min_scene_seconds,
            "max_scene_seconds": local_timing.max_scene_seconds,
            "scene_gap_seconds": local_timing.scene_gap_seconds,
        }
    )
    for sequence_payload in local_payload["sequences"]:
        sequence_id = sequence_payload["sequence_id"]
        spans = []
        for scene_id in sequence_payload["scene_ids"]:
            start_frame, end_frame = new_scene_ranges[(sequence_id, scene_id)]
            _, audio_end_frame = new_audio_ranges[(sequence_id, scene_id)]
            spans.append(
                {
                    "scene_id": scene_id,
                    "start_frame": start_frame,
                    "end_frame": end_frame,
                    "audio_start_frame": start_frame,
                    "audio_end_frame": audio_end_frame,
                    "tail_silence_frames": end_frame - audio_end_frame,
                }
            )
        sequence_payload["scene_spans"] = spans
        sequence_payload["duration_frames"] = spans[-1]["end_frame"]
        for beat_payload in sequence_payload["timeline"]:
            beat_payload["start_frame"], beat_payload["end_frame"] = new_local_beat_ranges[
                beat_payload["beat_id"]
            ]
    retimed_local = LocalSequencePlan.model_validate(local_payload)

    online_payload["script_sha256"] = production_payload["script_sha256"]
    online_payload["production_plan_sha256"] = production_hash
    online_payload["shots"] = _retime_online_payloads(
        online_payload["shots"],
        new_beat_ranges=new_beat_ranges,
        production_beats=production_beats,
        fps=fps,
    )
    retimed_online = OnlinePlan.model_validate(online_payload)
    return retimed_production, retimed_local, retimed_online


def retime_run(run_dir: Path) -> ProductionPlan:
    """Rebind a schema-v2 authored plan to current measured narration durations."""
    run_dir = run_dir.resolve()
    store = RunStore.open(run_dir)
    script = store.read_script()
    _require_audio_ready(run_dir, script)
    production = load_production_plan(run_dir / "production-plan.json")
    local = load_local_sequence_plan(run_dir / "local-sequence-plan.json")
    online = load_online_plan(run_dir / "online-plan.json")
    resolved_settings = resolve_run_settings(run_dir)
    local_timing = getattr(
        resolved_settings,
        "local_video",
        LocalVideoSettings(),
    )
    retimed_production, retimed_local, retimed_online = _retimed_v2_models(
        run_dir,
        script,
        production,
        local,
        online,
        local_timing,
    )

    variant_path = run_dir / "variant-plan.json"
    retimed_variant: SequenceVariantPlan | None = None
    if variant_path.is_file():
        variant = load_variant_plan(variant_path)
        if not isinstance(variant, SequenceVariantPlan):
            raise ValueError("schema-v2 retiming requires a schema-v2 variant plan")
        variant_payload = variant.model_dump(mode="json")
        variant_payload.update(
            {
                "script_sha256": script_sha256(run_dir / "script.json"),
                "production_plan_sha256": fingerprint(
                    _serialized_model(retimed_production)
                ),
                "local_sequence_plan_sha256": fingerprint(
                    _serialized_model(retimed_local)
                ),
            }
        )
        retimed_variant = SequenceVariantPlan.model_validate(variant_payload)

    plan_issues = validate_plan_against_script(
        retimed_production,
        script,
        run_dir / "script.json",
        run_dir,
    )
    if plan_issues:
        details = "; ".join(f"{item.code}: {item.message}" for item in plan_issues)
        raise ValueError(details)

    models = {
        "production-plan.json": retimed_production,
        "local-sequence-plan.json": retimed_local,
        "online-plan.json": retimed_online,
    }
    if retimed_variant is not None:
        models["variant-plan.json"] = retimed_variant

    with tempfile.TemporaryDirectory(prefix=".retime-", dir=run_dir) as temporary:
        stage = Path(temporary)
        for filename, model in models.items():
            atomic_write(stage / filename, _serialized_model(model))

        sequence_issues = validate_sequence_plans(
            retimed_production,
            retimed_local,
            retimed_online,
            script,
            script_path=run_dir / "script.json",
            production_path=stage / "production-plan.json",
        )
        if sequence_issues:
            details = "; ".join(
                f"{item.code}: {item.message}" for item in sequence_issues
            )
            raise ValueError(details)
        if retimed_variant is not None:
            variant_issues = validate_sequence_variant_plan(
                retimed_variant,
                retimed_production,
                retimed_local,
                production_path=stage / "production-plan.json",
                local_path=stage / "local-sequence-plan.json",
                script_path=run_dir / "script.json",
            )
            if variant_issues:
                details = "; ".join(
                    f"{item.code}: {item.message}" for item in variant_issues
                )
                raise ValueError(details)

        backup = stage / "backup"
        backup.mkdir()
        for filename in models:
            shutil.copy2(run_dir / filename, backup / filename)
        published: list[str] = []
        try:
            for filename in models:
                (stage / filename).replace(run_dir / filename)
                published.append(filename)
        except BaseException:
            for filename in reversed(published):
                (backup / filename).replace(run_dir / filename)
            raise

    return retimed_production


def plan_video(run_dir: Path) -> list[Path]:
    run_dir = run_dir.resolve()
    from .creative_gates import require_creative_plan
    require_creative_plan(run_dir)
    store = RunStore.open(run_dir)
    script = store.read_script()
    plan = load_production_plan(run_dir / "production-plan.json")
    _raise_plan_issues(plan, script, run_dir)
    if plan.schema_version == 2:
        local = load_local_sequence_plan(run_dir / "local-sequence-plan.json")
        online = load_online_plan(run_dir / "online-plan.json")
        _raise_sequence_plan_issues(run_dir, plan, local, online, script)
        return write_compiled_artifacts(
            run_dir,
            plan,
            script,
            local_plan=local,
            online_plan=online,
        )
    variant_plan = _load_valid_variant_plan(run_dir, plan)
    return write_compiled_artifacts(
        run_dir,
        plan,
        script,
        variant_plan=variant_plan,
    )


def _run_cli(
    action,
    argv: Sequence[str] | None,
    description: str,
    force: bool,
    schema_version: bool = False,
) -> int:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("run_directory", type=Path, help="runs 아래의 실행 폴더")
    if force:
        parser.add_argument("--force", action="store_true", help="파생 계획 파일을 다시 작성")
    if schema_version:
        parser.add_argument(
            "--schema-version",
            type=int,
            choices=(1, 2),
            default=2,
            help="마이그레이션 production-plan schema version (default: 2)",
        )
    args = parser.parse_args(argv)
    try:
        if force:
            kwargs = {"force": args.force}
            if schema_version:
                kwargs["schema_version"] = args.schema_version
            action(args.run_directory, **kwargs)
        else:
            action(args.run_directory)
    except (FileNotFoundError, FileExistsError, ValueError) as error:
        print(f"오류: {error}", file=sys.stderr)
        return 1
    return 0


def migration_main(argv: Sequence[str] | None = None) -> int:
    return _run_cli(
        migrate_run,
        argv,
        "기존 실행 폴더를 production-plan.json 기반 구조로 변환합니다.",
        True,
        True,
    )


def retime_main(argv: Sequence[str] | None = None) -> int:
    return _run_cli(
        retime_run,
        argv,
        "현재 음성 길이에 맞춰 schema-v2 영상 계획의 프레임과 해시를 다시 계산합니다.",
        False,
    )


def plan_video_main(argv: Sequence[str] | None = None) -> int:
    return _run_cli(
        plan_video,
        argv,
        "production-plan.json을 검증하고 영상 검토본과 생성 샷 프롬프트를 만듭니다.",
        False,
    )
