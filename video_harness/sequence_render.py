from __future__ import annotations

import json
import hashlib
import shutil
import subprocess
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal, Mapping, Protocol

from .media import (
    AudioPlacement,
    EncoderSpec,
    DEFAULT_ENCODER_SPEC,
    OutputSpec,
    concat_videos,
    encode_frames,
    extract_video_segment,
    mux_audio_timeline,
)
from .models import Scene, StrictModel
from .performance import PerformanceRecorder
from .production import load_production_plan, script_sha256
from .sequence_models import LocalSequence, LocalSequencePlan, OnlinePlan, SequenceTimelineBeat
from .sequence_plans import load_local_sequence_plan, load_online_plan
from .simulation import SimulationConfig, load_simulation
from .storage import RunStore, atomic_write, fingerprint, scene_filename
from .settings import HarnessSettings
from .pacing_presets import render_pacing_values
from .sequence_transitions import apply_entry_transitions


class SceneSliceResult(StrictModel):
    scene_id: int
    start_frame: int
    end_frame: int
    frame_count: int
    silent_file: str
    narrated_file: str


class SequenceResult(StrictModel):
    sequence_id: str
    frame_count: int
    width: int
    height: int
    fps: int
    master_file: str
    narrated_file: str
    state_report_file: str
    state_cache_file: str
    scene_slices: list[SceneSliceResult]


@dataclass(frozen=True)
class SequenceArtifactSource:
    result: SequenceResult
    root: Path
    reused: bool


class SequenceRenderReport(StrictModel):
    quality: Literal["draft", "final"]
    artifact_root: Path
    production_plan_sha256: str
    local_sequence_plan_sha256: str
    sequences: list[SequenceResult]
    final_file: str
    final_original_file: str


def resolve_sequence_artifact_sources(
    render_report: SequenceRenderReport,
    sequence_sources: Mapping[str, SequenceArtifactSource],
) -> dict[str, SequenceArtifactSource]:
    """Validate and normalize the roots that own variant sequence artifacts."""
    reported_by_id: dict[str, SequenceResult] = {}
    for result in render_report.sequences:
        if result.sequence_id in reported_by_id:
            raise ValueError(f"render report repeats sequence {result.sequence_id}")
        reported_by_id[result.sequence_id] = result
    missing = sorted(set(reported_by_id) - set(sequence_sources))
    unexpected = sorted(set(sequence_sources) - set(reported_by_id))
    if missing or unexpected:
        details = []
        if missing:
            details.append(f"missing sources: {missing}")
        if unexpected:
            details.append(f"unexpected sources: {unexpected}")
        raise ValueError(
            "sequence artifact sources do not match render report; "
            + "; ".join(details)
        )

    normalized: dict[str, SequenceArtifactSource] = {}
    for sequence_id, result in reported_by_id.items():
        source = sequence_sources[sequence_id]
        if source.result != result:
            raise ValueError(
                f"sequence artifact source differs from render report: {sequence_id}"
            )
        if not source.root.is_absolute() or ".." in source.root.parts:
            raise ValueError(
                "sequence artifact source root must be an absolute non-escaping path: "
                f"{source.root}"
            )
        if source.root.is_symlink() or not source.root.is_dir():
            raise ValueError(
                f"sequence artifact source root is not a plain directory: {source.root}"
            )
        root = source.root.resolve()
        if not root.is_dir():
            raise ValueError(f"sequence artifact source root is not a directory: {root}")
        relatives = [
            result.master_file,
            result.narrated_file,
            result.state_report_file,
            result.state_cache_file,
        ]
        for scene_slice in result.scene_slices:
            relatives.extend([scene_slice.silent_file, scene_slice.narrated_file])
        for relative in relatives:
            _artifact_path(root, relative)
        normalized[sequence_id] = SequenceArtifactSource(
            result=result,
            root=root,
            reused=source.reused,
        )
    return normalized


class SequenceRenderBackend(Protocol):
    def check_dependencies(self) -> None: ...

    def render_frames(
        self,
        job: dict[str, object],
        cache_dir: Path,
    ) -> Path: ...


class LocalSequenceRenderBackend:

    def __init__(self) -> None:
        self.renderer_dir = Path(__file__).resolve().parent / "science_renderer"

    @property
    def version(self) -> str:
        digest=hashlib.sha256()
        for path in sorted((self.renderer_dir/'src').rglob('*.ts')):
            digest.update(str(path.relative_to(self.renderer_dir)).encode())
            digest.update(path.read_bytes())
        digest.update((self.renderer_dir/'package-lock.json').read_bytes())
        return 'science-renderer-sequence-v2-'+digest.hexdigest()

    def check_dependencies(self) -> None:
        missing = [
            command
            for command in ("npm", "ffmpeg", "ffprobe")
            if shutil.which(command) is None
        ]
        if missing:
            raise RuntimeError(f"필요한 명령이 없습니다: {', '.join(missing)}")
        if not (self.renderer_dir / "node_modules").is_dir():
            raise RuntimeError(
                f"렌더러 의존성이 없습니다: cd {self.renderer_dir} && npm install"
            )

    def render_frames(
        self,
        job: dict[str, object],
        cache_dir: Path,
    ) -> Path:
        cache_dir.mkdir(parents=True, exist_ok=True)
        job_path = cache_dir / "render-job.json"
        atomic_write(
            job_path,
            json.dumps(job, ensure_ascii=False, indent=2) + "\n",
        )
        subprocess.run(
            ["npm", "run", "render", "--silent", "--", str(job_path)],
            cwd=self.renderer_dir,
            text=True,
            capture_output=True,
            check=True,
        )
        report_path = cache_dir / "frame-report.json"
        if not report_path.is_file():
            raise FileNotFoundError(report_path)
        return report_path


def sequence_renderer(local: LocalSequencePlan, sequence: LocalSequence) -> str:
    return getattr(sequence, 'renderer', None) or getattr(local, 'renderer', 'threejs')


def _make_backend(renderer: str) -> SequenceRenderBackend:
    if renderer == "blender":
        from .blender_backend import BlenderSequenceRenderBackend
        return BlenderSequenceRenderBackend()
    if renderer == "threejs":
        return LocalSequenceRenderBackend()
    raise ValueError(f"unsupported renderer: {renderer!r}; choose blender or threejs")


class RoutedSequenceRenderBackend:
    """Keep independent sequence renders on their explicitly selected engine."""
    def __init__(self, local: LocalSequencePlan):
        self.routes={s.sequence_id:sequence_renderer(local,s) for s in local.sequences}
        self.backends={name:_make_backend(name) for name in set(self.routes.values())}

    def backend_for_sequence(self, sequence_id: str) -> SequenceRenderBackend:
        if sequence_id not in self.routes:
            raise ValueError(f'unknown sequence: {sequence_id}')
        return self.backends[self.routes[sequence_id]]

    @property
    def version(self) -> str:
        return '|'.join(name+':'+_backend_version(backend)
                        for name,backend in sorted(self.backends.items()))

    def check_dependencies(self) -> None:
        for backend in self.backends.values():backend.check_dependencies()

    def render_frames(self, job: dict[str, object], cache_dir: Path) -> Path:
        return self.backend_for_sequence(str(job['sequence_id'])).render_frames(job,cache_dir)


def backend_for_plan(local: LocalSequencePlan) -> SequenceRenderBackend:
    if any(getattr(s,'renderer',None) is not None for s in local.sequences):
        return RoutedSequenceRenderBackend(local)
    return _make_backend(local.renderer)


def _output_boundary(
    canonical_frame: int,
    *,
    output_fps: int,
    canonical_fps: int,
) -> int:
    if canonical_frame < 0 or output_fps <= 0 or canonical_fps <= 0:
        raise ValueError("frame mapping requires non-negative frames and positive fps")
    return (canonical_frame * output_fps + canonical_fps - 1) // canonical_fps


def _simulation_time_at(beat: SequenceTimelineBeat, frame: int) -> float:
    progress = (frame - beat.start_frame) / (beat.end_frame - beat.start_frame)
    return beat.simulation_time_start + progress * (
        beat.simulation_time_end - beat.simulation_time_start
    )


def _canonical_state_cache(sequence: LocalSequence) -> list[dict[str, object]]:
    cache: list[dict[str, object]] = []
    for frame in range(sequence.duration_frames):
        active = sorted(
            (
                beat
                for beat in sequence.timeline
                if beat.start_frame <= frame < beat.end_frame
            ),
            key=lambda beat: (beat.priority, beat.beat_id),
        )
        if not active:
            raise ValueError(
                f"sequence {sequence.sequence_id} has no active beat at frame {frame}"
            )
        clock_beat = max(active, key=lambda beat: (beat.priority, beat.beat_id))
        cache.append(
            {
                "canonical_frame": frame,
                "active_beat_ids": [beat.beat_id for beat in active],
                "simulation_time": _simulation_time_at(clock_beat, frame),
            }
        )
    previous = float("-inf")
    for entry in cache:
        current = float(entry["simulation_time"])
        if current < previous:
            raise ValueError(
                f"sequence {sequence.sequence_id} canonical simulation time decreases"
            )
        previous = current
    return cache


def _relative_to(root: Path, path: Path) -> str:
    resolved_root = root.resolve()
    resolved_path = path.resolve()
    if resolved_path != resolved_root and resolved_root not in resolved_path.parents:
        raise ValueError(f"artifact path escapes output root: {path}")
    return resolved_path.relative_to(resolved_root).as_posix()


def _artifact_path(root: Path, relative: str) -> Path:
    posix = PurePosixPath(relative)
    if posix.is_absolute() or ".." in posix.parts or "\\" in relative:
        raise ValueError(f"artifact path must be a relative descendant: {relative}")
    candidate = (root / Path(*posix.parts)).resolve()
    resolved_root = root.resolve()
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise ValueError(f"artifact path escapes output root: {relative}")
    return candidate


def _backend_version(backend: SequenceRenderBackend) -> str:
    value = getattr(backend, "version", None)
    if isinstance(value, str) and value:
        return value
    cls = type(backend)
    return f"{cls.__module__}.{cls.__qualname__}"


def _render_fingerprint(
    *,
    local_plan_sha256: str,
    simulation_sha256: str,
    quality: str,
    variant_profile: dict[str, object] | None,
    backend_version: str,
    render_settings: HarnessSettings,
) -> str:
    payload = {
        "local_sequence_plan_sha256": local_plan_sha256,
        "simulation_sha256": simulation_sha256,
        "quality": quality,
        "variant_profile": variant_profile,
        "backend_version": backend_version,
        "transition_code_sha256": hashlib.sha256(Path(__file__).with_name('sequence_transitions.py').read_bytes()).hexdigest(),
        "render_settings": render_settings.render.model_dump(mode="json"),
    }
    return fingerprint(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )


def _result_artifacts_exist(root: Path, result: SequenceResult) -> bool:
    relatives = [
        result.master_file,
        result.narrated_file,
        result.state_report_file,
        result.state_cache_file,
    ]
    for scene_slice in result.scene_slices:
        relatives.extend([scene_slice.silent_file, scene_slice.narrated_file])
    return all(_artifact_path(root, relative).is_file() for relative in relatives)


def _load_reusable_result(
    record_path: Path,
    *,
    expected_fingerprint: str,
    artifact_root: Path,
) -> SequenceResult | None:
    if not record_path.is_file():
        return None
    try:
        payload = json.loads(record_path.read_text(encoding="utf-8"))
        if payload.get("fingerprint") != expected_fingerprint:
            return None
        result = SequenceResult.model_validate(payload["result"])
    except (OSError, json.JSONDecodeError, KeyError, ValueError):
        return None
    return result if _result_artifacts_exist(artifact_root, result) else None


def _write_render_record(
    path: Path,
    *,
    render_fingerprint: str,
    result: SequenceResult,
) -> None:
    atomic_write(
        path,
        json.dumps(
            {
                "fingerprint": render_fingerprint,
                "result": result.model_dump(mode="json"),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    )


def _physics_payload(config: SimulationConfig) -> dict[str, object]:
    if config.preset in {"stellar-spectra-blender", "sun-earth-moon-blender", "vorticity-blender", "bonding-blender", "coriolis-blender", "phantom-jam-blender", "optical-depth-blender", "transfer-equation-blender", "virial-galaxy-blender", "adiabatic-blender", "saturn-rings-blender", "typhoon-beta-blender", "energy-transport-blender"}:
        return config.physics.model_dump(mode="json")
    return {
        "earth_period_days": config.physics.earth_period_days,
        "mars_period_days": config.physics.mars_period_days,
        "earth_orbit_radius": config.physics.earth_orbit_radius,
        "mars_orbit_radius": config.physics.mars_orbit_radius,
        "opposition_day": config.physics.opposition_day,
    }


def _style_payload(config: SimulationConfig) -> dict[str, object]:
    if config.preset in {"stellar-spectra-blender", "sun-earth-moon-blender", "vorticity-blender", "bonding-blender", "coriolis-blender", "phantom-jam-blender", "optical-depth-blender", "transfer-equation-blender", "virial-galaxy-blender", "adiabatic-blender", "saturn-rings-blender", "typhoon-beta-blender", "energy-transport-blender"}:
        return config.style.model_dump(mode="json")
    return {
        "seed": config.style.seed,
        "earth_scale": config.style.earth_scale,
        "mars_scale": config.style.mars_scale,
    }


def _timeline_payload(sequence: LocalSequence) -> list[dict[str, object]]:
    return [beat.model_dump(mode="json", exclude_none=True) for beat in sequence.timeline]


def build_sequence_job(
    sequence: LocalSequence,
    *,
    width: int,
    height: int,
    output_fps: int,
    canonical_fps: int,
    cache_dir: Path,
    simulation,
    variant_profile: dict[str, object] | None = None,
    sample_frames: list[int] | None = None,
    camera_transition_seconds: float | None = None,
    pacing: dict | None = None,
) -> dict[str, object]:
    spec = _sequence_output_spec(
        sequence, width=width, height=height, output_fps=output_fps, canonical_fps=canonical_fps
    )
    job: dict[str, object] = {
        "job_kind": "sequence",
        "sequence_id": sequence.sequence_id,
        "scene_graph": sequence.scene_graph,
        "canonical_fps": canonical_fps,
        "duration_frames": sequence.duration_frames,
        "frame_count": spec.frame_count,
        "output_directory": str(cache_dir),
        "output": {"width": width, "height": height, "fps": output_fps},
        "timeline": _timeline_payload(sequence),
        "canonical_state_cache": _canonical_state_cache(sequence),
        "sample_frames": list(range(spec.frame_count)) if sample_frames is None else sorted(set(sample_frames)),
        "physics": _physics_payload(simulation),
        "style": _style_payload(simulation),
    }
    if variant_profile is not None:
        job["variant_profile"] = variant_profile
    # Advisory pacing for renderers; the default is omitted so existing render caches stay valid.
    from .settings import CAMERA_TRANSITION_DEFAULT
    if camera_transition_seconds is not None and camera_transition_seconds != CAMERA_TRANSITION_DEFAULT:
        job["camera_transition_seconds"] = camera_transition_seconds
    if pacing is not None:
        job["pacing"] = pacing
        job["camera_transition_seconds"] = pacing["camera_transition_seconds"]
    return job


def _normalize_frame_report(
    source: Path,
    destination: Path,
    *,
    artifact_root: Path,
    sequence_id: str,
    frame_count: int,
    width: int,
    height: int,
) -> dict[str, object]:
    payload = json.loads(source.read_text(encoding="utf-8"))
    expected = {
        "sequence_id": sequence_id,
        "frame_count": frame_count,
        "width": width,
        "height": height,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise ValueError(
                f"sequence frame report {key} differs: {payload.get(key)!r} / {value!r}"
            )
    frames = payload.get("frames")
    if not isinstance(frames, list) or len(frames) != frame_count:
        raise ValueError("sequence frame report has an invalid frames list")
    normalized_frames: list[str] = []
    for value in frames:
        if not isinstance(value, str):
            raise ValueError("sequence frame report frame path must be a string")
        frame_path = Path(value)
        if not frame_path.is_absolute():
            frame_path = source.parent / frame_path
        normalized_frames.append(_relative_to(artifact_root, frame_path))
    payload["frames"] = normalized_frames
    if not isinstance(payload.get("state_samples"), list):
        raise ValueError("sequence frame report state_samples must be a list")
    atomic_write(
        destination,
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
    )
    return payload


def _sequence_output_spec(
    sequence: LocalSequence,
    *,
    width: int,
    height: int,
    output_fps: int,
    canonical_fps: int,
) -> OutputSpec:
    frame_count = _output_boundary(
        sequence.duration_frames,
        output_fps=output_fps,
        canonical_fps=canonical_fps,
    )
    return OutputSpec(
        width=width,
        height=height,
        fps=output_fps,
        duration_seconds=frame_count / output_fps,
        frames=frame_count,
    )


def _audio_placement(
    scene: Scene,
    *,
    start_frame: int,
    end_frame: int,
    output_fps: int,
    canonical_fps: int,
    sequence_output_start: int = 0,
) -> AudioPlacement:
    if not scene.audio_file:
        raise ValueError(f"scene {scene.scene_id} has no audio_file")
    output_start = _output_boundary(
        start_frame,
        output_fps=output_fps,
        canonical_fps=canonical_fps,
    )
    output_end = _output_boundary(
        end_frame,
        output_fps=output_fps,
        canonical_fps=canonical_fps,
    )
    if output_end <= output_start:
        raise ValueError(f"scene {scene.scene_id} audio maps to no output frames")
    return AudioPlacement(
        source=Path(scene.audio_file),
        start_frame=output_start - sequence_output_start,
        end_frame=output_end - sequence_output_start,
    )


def mux_sequence_narration(
    run_dir: Path,
    local: LocalSequencePlan,
    results: list[SequenceResult],
    video: Path,
    destination: Path,
    *,
    encoder: EncoderSpec = DEFAULT_ENCODER_SPEC,
    settings: HarnessSettings | None = None,
):
    """Encode narration once on the final frame clock, avoiding repeated AAC priming."""
    if not results:
        raise ValueError("narration assembly requires rendered sequences")
    store = RunStore.open(run_dir)
    scenes = {scene.scene_id: scene for scene in store.read_script().scenes}
    sequences = {sequence.sequence_id: sequence for sequence in local.sequences}
    fps = results[0].fps
    placements: list[AudioPlacement] = []
    cursor = 0
    for result in results:
        if result.fps != fps:
            raise ValueError("narration assembly requires one output frame rate")
        for span in sequences[result.sequence_id].scene_spans:
            placement = _audio_placement(
                scenes[span.scene_id], start_frame=span.audio_start_frame,
                end_frame=span.audio_end_frame, output_fps=fps,
                canonical_fps=local.defaults.fps,
            )
            placements.append(AudioPlacement(
                source=store.path(placement.source),
                start_frame=cursor + placement.start_frame,
                end_frame=cursor + placement.end_frame,
            ))
        cursor += result.frame_count
    spec = OutputSpec(width=results[0].width, height=results[0].height,
                      fps=fps, frames=cursor, duration_seconds=cursor / fps)
    result = mux_audio_timeline(video, placements, destination, spec, encoder=encoder)
    from .music import score_master
    score_master(run_dir, source=destination, duration=spec.duration_seconds, fps=fps,
                 settings=settings or HarnessSettings())
    return result


def render_sequence_quality(
    run_dir: Path,
    *,
    quality: Literal["draft", "final"],
    backend: SequenceRenderBackend | None = None,
    output_root: Path | None = None,
    variant_profile: dict[str, object] | None = None,
    force: bool = False,
    settings: HarnessSettings | None = None,
    performance: PerformanceRecorder | None = None,
) -> SequenceRenderReport:
    if quality not in {"draft", "final"}:
        raise ValueError("quality must be draft or final")
    from .creative_gates import require_creative_plan
    require_creative_plan(run_dir)
    store = RunStore.open(run_dir)
    settings = settings or HarnessSettings()
    encoder = EncoderSpec(
        preset=settings.render.x264_preset,
        crf=settings.render.x264_crf,
    )
    artifact_root = (output_root or store.root).resolve()
    artifact_root.mkdir(parents=True, exist_ok=True)
    script = store.read_script()
    production_path = store.root / "production-plan.json"
    local_path = store.root / "local-sequence-plan.json"
    online_path = store.root / "online-plan.json"
    simulation_path = store.root / "simulation.json"
    production = load_production_plan(production_path)
    local = load_local_sequence_plan(local_path)
    load_online_plan(online_path)
    simulation = load_simulation(store.root, script)

    canonical_fps = local.defaults.fps
    if quality == "draft":
        width, height, output_fps = (
            settings.render.draft_width,
            settings.render.draft_height,
            settings.render.draft_fps,
        )
    else:
        width, height, output_fps = (
            local.defaults.width,
            local.defaults.height,
            local.defaults.fps,
        )
    script_by_id = {scene.scene_id: scene for scene in script.scenes}
    for sequence in local.sequences:
        for span in sequence.scene_spans:
            scene = script_by_id.get(span.scene_id)
            if scene is None or not scene.audio_file:
                raise ValueError(f"scene {span.scene_id} has no audio metadata")
            audio_path = store.path(scene.audio_file)
            if not audio_path.is_file() or audio_path.stat().st_size == 0:
                raise FileNotFoundError(audio_path)

    active_backend = backend or backend_for_plan(local)
    active_backend.check_dependencies()
    production_sha = script_sha256(production_path)
    local_sha = script_sha256(local_path)
    simulation_sha = script_sha256(simulation_path)
    render_fingerprint = _render_fingerprint(
        local_plan_sha256=local_sha,
        simulation_sha256=simulation_sha,
        quality=quality,
        variant_profile=variant_profile,
        backend_version=_backend_version(active_backend),
        render_settings=settings,
    )
    sequence_directory = artifact_root / "videoFiles" / "sequences" / quality
    state_cache_directory = artifact_root / "videoFiles" / "sequences" / "state-cache"
    sequence_directory.mkdir(parents=True, exist_ok=True)
    state_cache_directory.mkdir(parents=True, exist_ok=True)
    scene_directory = artifact_root / "videoFiles"
    if quality == "draft":
        scene_directory = scene_directory / "draft"
    original_directory = scene_directory / "original"
    original_directory.mkdir(parents=True, exist_ok=True)

    sequence_results: list[SequenceResult] = []
    rendered_sequence_ids: list[str] = []
    reused_sequence_ids: list[str] = []
    for sequence in local.sequences:
        record_path = sequence_directory / f"{sequence.sequence_id}-render-record.json"
        reusable = None if force else _load_reusable_result(
            record_path,
            expected_fingerprint=render_fingerprint,
            artifact_root=artifact_root,
        )
        if reusable is not None:
            sequence_results.append(reusable)
            reused_sequence_ids.append(sequence.sequence_id)
            continue
        rendered_sequence_ids.append(sequence.sequence_id)
        spec = _sequence_output_spec(
            sequence,
            width=width,
            height=height,
            output_fps=output_fps,
            canonical_fps=canonical_fps,
        )
        cache_dir = (
            artifact_root
            / ".render-cache"
            / "sequences"
            / quality
            / sequence.sequence_id
        )
        cache_dir.mkdir(parents=True, exist_ok=True)
        job = build_sequence_job(
            sequence,
            width=width,
            height=height,
            output_fps=output_fps,
            canonical_fps=canonical_fps,
            cache_dir=cache_dir,
            simulation=simulation,
            variant_profile=variant_profile,
            camera_transition_seconds=getattr(getattr(settings, "local_video", None), "camera_transition_seconds", None),
            pacing=render_pacing_values(settings),
        )
        state_cache_path = state_cache_directory / f"{sequence.sequence_id}.json"
        atomic_write(
            state_cache_path,
            json.dumps(job["canonical_state_cache"], ensure_ascii=False, indent=2) + "\n",
        )
        state_report_path = sequence_directory / f"{sequence.sequence_id}-frame-report.json"
        with (
            performance.phase("renderer", sequence_id=sequence.sequence_id, quality=quality)
            if performance is not None
            else nullcontext()
        ):
            raw_state_report = active_backend.render_frames(job, cache_dir)
        previous_frame = None
        has_entry = any(b.controller_options.get('entry_transition') for b in sequence.timeline)
        if has_entry and sequence_results:
            previous = sequence_results[-1]
            previous_report = json.loads(_artifact_path(artifact_root, previous.state_report_file).read_text())
            previous_frame = _artifact_path(artifact_root, previous_report['frames'][-1])
            if not previous_frame.is_file():
                previous_frame = cache_dir / 'previous-sequence-last.png'
                subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', str(_artifact_path(artifact_root, previous.master_file)),
                    '-vf', f'select=eq(n\\,{previous.frame_count-1})', '-frames:v', '1', str(previous_frame)], check=True, capture_output=True)
        with (performance.phase('scene_transition', sequence_id=sequence.sequence_id) if performance is not None else nullcontext()):
            apply_entry_transitions(job, raw_state_report, previous_frame=previous_frame)
        normalized_report = _normalize_frame_report(
            raw_state_report,
            state_report_path,
            artifact_root=artifact_root,
            sequence_id=sequence.sequence_id,
            frame_count=spec.frame_count,
            width=width,
            height=height,
        )
        if sequence_renderer(local, sequence) == "blender":
            shutil.copy2(cache_dir / "scene.blend", sequence_directory / f"{sequence.sequence_id}.blend")
        if performance is not None:
            performance.record_renderer_report(normalized_report, fps=output_fps)

        master_path = sequence_directory / f"{sequence.sequence_id}.mp4"
        with (
            performance.phase("ffmpeg_encode", sequence_id=sequence.sequence_id)
            if performance is not None
            else nullcontext()
        ):
            encode_frames(cache_dir / "frame-%06d.png", master_path, spec, encoder=encoder)
        master_placements: list[AudioPlacement] = []
        for span in sequence.scene_spans:
            scene = script_by_id[span.scene_id]
            placement = _audio_placement(
                scene,
                start_frame=span.audio_start_frame,
                end_frame=span.audio_end_frame,
                output_fps=output_fps,
                canonical_fps=canonical_fps,
            )
            master_placements.append(
                AudioPlacement(
                    source=store.path(placement.source),
                    start_frame=placement.start_frame,
                    end_frame=placement.end_frame,
                )
            )
        narrated_master_path = sequence_directory / f"{sequence.sequence_id}-narrated.mp4"
        with (
            performance.phase("audio_mux", sequence_id=sequence.sequence_id)
            if performance is not None
            else nullcontext()
        ):
            mux_audio_timeline(
                master_path,
                master_placements,
                narrated_master_path,
                spec,
                encoder=encoder,
            )

        scene_results: list[SceneSliceResult] = []
        for span in sequence.scene_spans:
            scene = script_by_id[span.scene_id]
            output_start = _output_boundary(
                span.start_frame,
                output_fps=output_fps,
                canonical_fps=canonical_fps,
            )
            output_end = _output_boundary(
                span.end_frame,
                output_fps=output_fps,
                canonical_fps=canonical_fps,
            )
            silent_path = original_directory / scene_filename(scene, ".mp4")
            narrated_path = scene_directory / scene_filename(scene, ".mp4")
            extract_video_segment(
                master_path,
                silent_path,
                start_frame=output_start,
                end_frame=output_end,
                fps=output_fps,
                encoder=encoder,
            )
            scene_spec = OutputSpec(
                width=width,
                height=height,
                fps=output_fps,
                duration_seconds=(output_end - output_start) / output_fps,
                frames=output_end - output_start,
            )
            scene_placement = _audio_placement(
                scene,
                start_frame=span.audio_start_frame,
                end_frame=span.audio_end_frame,
                output_fps=output_fps,
                canonical_fps=canonical_fps,
                sequence_output_start=output_start,
            )
            with (
                performance.phase("audio_mux", sequence_id=sequence.sequence_id)
                if performance is not None
                else nullcontext()
            ):
                mux_audio_timeline(
                    silent_path,
                    [
                        AudioPlacement(
                            source=store.path(scene_placement.source),
                            start_frame=scene_placement.start_frame,
                            end_frame=scene_placement.end_frame,
                        )
                    ],
                    narrated_path,
                    scene_spec,
                    encoder=encoder,
                )
            scene_results.append(
                SceneSliceResult(
                    scene_id=span.scene_id,
                    start_frame=span.start_frame,
                    end_frame=span.end_frame,
                    frame_count=output_end - output_start,
                    silent_file=_relative_to(artifact_root, silent_path),
                    narrated_file=_relative_to(artifact_root, narrated_path),
                )
            )

        result = SequenceResult(
            sequence_id=sequence.sequence_id,
            frame_count=spec.frame_count,
            width=width,
            height=height,
            fps=output_fps,
            master_file=_relative_to(artifact_root, master_path),
            narrated_file=_relative_to(artifact_root, narrated_master_path),
            state_report_file=_relative_to(artifact_root, state_report_path),
            state_cache_file=_relative_to(artifact_root, state_cache_path),
            scene_slices=scene_results,
        )
        _write_render_record(
            record_path,
            render_fingerprint=render_fingerprint,
            result=result,
        )
        sequence_results.append(result)

    silent_sequences = [
        _artifact_path(artifact_root, result.master_file)
        for result in sequence_results
    ]
    if quality == "draft":
        final_path = artifact_root / "final-draft.mp4"
        final_original_path = artifact_root / "video-only-draft.mp4"
    else:
        final_path = artifact_root / "final.mp4"
        final_original_path = artifact_root / "video-only.mp4"
    expected_duration = sum(result.frame_count for result in sequence_results) / output_fps
    concat_videos(
        silent_sequences,
        final_original_path,
        expected_duration=expected_duration,
        require_audio=False,
        transition_seconds=0.0,
        transition_fade_seconds=0.0,
        encoder=encoder,
        performance=performance,
    )
    mux_sequence_narration(
        store.root, local, sequence_results, final_original_path, final_path,
        encoder=encoder, settings=settings,
    )

    report = SequenceRenderReport(
        quality=quality,
        artifact_root=artifact_root,
        production_plan_sha256=production_sha,
        local_sequence_plan_sha256=local_sha,
        sequences=sequence_results,
        final_file=_relative_to(artifact_root, final_path),
        final_original_file=_relative_to(artifact_root, final_original_path),
    )
    if performance is not None:
        frames_by_sequence = {
            result.sequence_id: result.frame_count for result in sequence_results
        }
        performance.record_base_output(
            output_id=quality,
            rendered_sequence_ids=rendered_sequence_ids,
            reused_sequence_ids=reused_sequence_ids,
            rendered_frame_count=sum(
                frames_by_sequence[sequence_id]
                for sequence_id in rendered_sequence_ids
            ),
            reused_frame_count=sum(
                frames_by_sequence[sequence_id] for sequence_id in reused_sequence_ids
            ),
        )
    return report


def create_online_references(
    run_dir: Path,
    online: OnlinePlan,
    render_report: SequenceRenderReport,
    *,
    output_root: Path | None = None,
    sequence_sources: Mapping[str, SequenceArtifactSource] | None = None,
) -> list[str]:
    RunStore.open(run_dir)
    if render_report.quality != "final":
        raise ValueError("online references require a final render report")
    source_root = render_report.artifact_root.resolve()
    artifact_root = (output_root or source_root).resolve()
    artifact_root.mkdir(parents=True, exist_ok=True)
    sequences = {result.sequence_id: result for result in render_report.sequences}
    sources = (
        resolve_sequence_artifact_sources(render_report, sequence_sources)
        if sequence_sources is not None
        else None
    )
    references: list[str] = []
    for shot in online.shots:
        if shot.reference_video_file is None:
            continue
        if shot.preferred_mode != "v2v":
            raise ValueError(
                f"online shot {shot.online_shot_id} declares a video reference without v2v"
            )
        result = sequences.get(shot.source_sequence_id)
        if result is None:
            raise ValueError(
                f"online shot {shot.online_shot_id} names an unknown source sequence"
            )
        if shot.source_end_frame > result.frame_count:
            raise ValueError(
                f"online shot {shot.online_shot_id} exceeds its source sequence"
            )
        source_root_for_sequence = (
            sources[result.sequence_id].root if sources is not None else source_root
        )
        source = _artifact_path(source_root_for_sequence, result.master_file)
        destination = _artifact_path(artifact_root, shot.reference_video_file)
        expected_root = PurePosixPath("videoFiles", "onlineReferences")
        declared = PurePosixPath(shot.reference_video_file)
        if declared.parent != expected_root:
            raise ValueError(
                f"online reference must be directly under {expected_root.as_posix()}"
            )
        extract_video_segment(
            source,
            destination,
            start_frame=shot.source_start_frame,
            end_frame=shot.source_end_frame,
            fps=result.fps,
        )
        references.append(_relative_to(artifact_root, destination))
    return references
