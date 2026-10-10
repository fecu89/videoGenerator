from __future__ import annotations

import json
import shutil
import stat
import sys
import uuid
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import Field

from . import sequence_render as sequence_render_module
from .media import AudioPlacement, OutputSpec
from .models import StrictModel
from .performance import PerformanceRecorder
from .production import script_sha256
from .production_models import ProductionPlan
from .sequence_models import LocalSequence, LocalSequencePlan, OnlinePlan
from .sequence_qa import run_sequence_qa
from .sequence_render import (
    SceneSliceResult,
    SequenceArtifactSource,
    SequenceRenderBackend,
    SequenceRenderReport,
    SequenceResult,
)
from .settings import HarnessSettings, VariantMode
from .simulation import load_simulation
from .storage import RunStore, atomic_write, fingerprint, scene_filename
from .variants import (
    SequenceVariantOverride,
    SequenceVariantPlan,
    SequenceVariantRecipe,
    VariantId,
    validate_sequence_variant_plan,
)


class SequenceVariantOutput(StrictModel):
    variant_id: VariantId
    final_file: str
    original_file: str
    rendered_sequence_ids: list[str]
    reused_sequence_ids: list[str]
    final_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    original_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    qa_status: Literal["passed"]


class SequenceVariantManifest(StrictModel):
    schema_version: Literal[2] = 2
    production_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    local_sequence_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    variant_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    script_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    state_cache_sha256: dict[str, str]
    variants: list[SequenceVariantOutput] = Field(min_length=1, max_length=4)


@dataclass(frozen=True)
class _PlanBindings:
    production_sha256: str
    local_sha256: str
    online_sha256: str
    variant_sha256: str
    script_sha256: str


@dataclass(frozen=True)
class _CacheSnapshot:
    path: Path
    raw_bytes: bytes
    payload: list[dict[str, object]]
    sha256: str


_OWNERSHIP_MARKER = ".task8-sequence-variant-owned"
_OWNERSHIP_CONTENT = "task8-sequence-variant-transaction\n"
_PUBLIC_DESTINATION_RELATIVES = (
    "final.mp4",
    "video-only.mp4",
    "videoFiles/variants/02_explain.mp4",
    "videoFiles/variants/video-only/02_explain.mp4",
    "videoFiles/variants/03_dynamic.mp4",
    "videoFiles/variants/video-only/03_dynamic.mp4",
    "videoFiles/variants/04_cinematic.mp4",
    "videoFiles/variants/video-only/04_cinematic.mp4",
    "videoFiles/variants/variants.json",
)
_BALANCED_PUBLIC_DESTINATION_RELATIVES = (
    "final.mp4",
    "video-only.mp4",
    "videoFiles/variants/variants.json",
)


def _lstat(path: Path):
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def _require_plain_directory(path: Path, label: str) -> None:
    metadata = _lstat(path)
    if metadata is None:
        raise ValueError(f"{label} does not exist: {path}")
    if stat.S_ISLNK(metadata.st_mode):
        raise ValueError(f"{label} cannot be a symlink: {path}")
    if not stat.S_ISDIR(metadata.st_mode):
        raise ValueError(f"{label} must be a directory: {path}")


def _ensure_plain_directory(path: Path, label: str) -> None:
    missing: list[Path] = []
    current = path
    while _lstat(current) is None:
        missing.append(current)
        if current.parent == current:
            raise ValueError(f"cannot create {label}: {path}")
        current = current.parent
    _require_plain_directory(current, f"{label} ancestor")
    for directory in reversed(missing):
        directory.mkdir()
        _require_plain_directory(directory, label)
    _require_plain_directory(path, label)


def _create_owned_directory(parent: Path, name: str, label: str) -> Path:
    _require_plain_directory(parent, f"{label} parent")
    if not name or Path(name).name != name:
        raise ValueError(f"invalid {label} name: {name}")
    path = parent / name
    if _lstat(path) is not None:
        raise ValueError(f"{label} already exists: {path}")
    path.mkdir()
    _require_plain_directory(path, label)
    marker = path / _OWNERSHIP_MARKER
    with marker.open("x", encoding="utf-8") as stream:
        stream.write(_OWNERSHIP_CONTENT)
    return path


def _require_owned_directory(path: Path, label: str) -> None:
    _require_plain_directory(path.parent, f"{label} parent")
    _require_plain_directory(path, label)
    marker = path / _OWNERSHIP_MARKER
    metadata = _lstat(marker)
    if metadata is None or stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(
        metadata.st_mode
    ):
        raise ValueError(f"{label} has no valid ownership marker: {path}")
    if marker.read_text(encoding="utf-8") != _OWNERSHIP_CONTENT:
        raise ValueError(f"{label} ownership marker differs: {path}")


def _remove_owned_directory(path: Path, label: str) -> None:
    _require_owned_directory(path, label)
    shutil.rmtree(path)


def _prepare_transaction_root(artifact_root: Path) -> tuple[Path, Path]:
    _ensure_plain_directory(artifact_root, "artifact root")
    variants_root = artifact_root / ".sequence-variants"
    if _lstat(variants_root) is None:
        variants_root.mkdir()
    _require_plain_directory(variants_root, "sequence variants root")
    for variant_id in ("balanced", "explain", "dynamic", "cinematic"):
        legacy_workspace = variants_root / variant_id
        metadata = _lstat(legacy_workspace)
        if metadata is not None and stat.S_ISLNK(metadata.st_mode):
            raise ValueError(
                f"legacy variant workspace cannot be a symlink: {legacy_workspace}"
            )
    transaction = _create_owned_directory(
        variants_root,
        f".transaction-{uuid.uuid4().hex}",
        "variant transaction",
    )
    workspaces = _create_owned_directory(
        transaction, "workspaces", "variant workspaces root"
    )
    return transaction, workspaces


def _bind_plan_models(
    run_dir: Path,
    production: ProductionPlan,
    local: LocalSequencePlan,
    online: OnlinePlan,
    variant_plan: SequenceVariantPlan,
) -> _PlanBindings:
    artifacts: tuple[tuple[str, Path, type[StrictModel], StrictModel], ...] = (
        (
            "production",
            run_dir / "production-plan.json",
            ProductionPlan,
            production,
        ),
        ("local", run_dir / "local-sequence-plan.json", LocalSequencePlan, local),
        ("online", run_dir / "online-plan.json", OnlinePlan, online),
        ("variant", run_dir / "variant-plan.json", SequenceVariantPlan, variant_plan),
    )
    hashes: dict[str, str] = {}
    for label, path, model_type, supplied in artifacts:
        raw_bytes = path.read_bytes()
        loaded = model_type.model_validate_json(raw_bytes)
        if supplied != loaded:
            raise ValueError(f"{label} model differs from its on-disk artifact")
        hashes[label] = fingerprint(raw_bytes)
    script_bytes = (run_dir / "script.json").read_bytes()
    return _PlanBindings(
        production_sha256=hashes["production"],
        local_sha256=hashes["local"],
        online_sha256=hashes["online"],
        variant_sha256=hashes["variant"],
        script_sha256=fingerprint(script_bytes),
    )


def _avoided_copy_metrics(
    result: SequenceResult,
    *,
    source_root: Path,
) -> tuple[int, int]:
    """Measure the regular files former variant reuse would have copied."""
    relatives = [
        result.master_file,
        result.narrated_file,
        result.state_report_file,
        result.state_cache_file,
    ]
    for scene_slice in result.scene_slices:
        relatives.extend([scene_slice.silent_file, scene_slice.narrated_file])
    relatives.extend(
        f".render-cache/sequences/final/{result.sequence_id}/frame-{frame:06d}.png"
        for frame in range(result.frame_count)
    )
    file_count = 0
    byte_count = 0
    for relative in relatives:
        path = sequence_render_module._artifact_path(source_root, relative)
        metadata = _lstat(path)
        if metadata is None or not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"base artifact must be a regular file: {path}")
        file_count += 1
        byte_count += metadata.st_size
    return file_count, byte_count


def _canonical_table(cache: list[dict[str, object]]) -> list[tuple[int, float]]:
    table: list[tuple[int, float]] = []
    for item in cache:
        frame = item.get("canonical_frame")
        simulation_time = item.get("simulation_time")
        if not isinstance(frame, int) or isinstance(frame, bool):
            raise ValueError("base state cache has an invalid canonical frame")
        if not isinstance(simulation_time, (int, float)) or isinstance(
            simulation_time, bool
        ):
            raise ValueError("base state cache has an invalid simulation time")
        table.append((frame, float(simulation_time)))
    return table


def _read_cache_snapshot(path: Path) -> _CacheSnapshot:
    metadata = _lstat(path)
    if metadata is None or stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(
        metadata.st_mode
    ):
        raise ValueError(f"canonical cache must be a regular non-symlink file: {path}")
    raw_bytes = path.read_bytes()
    try:
        payload = json.loads(raw_bytes)
    except json.JSONDecodeError as error:
        raise ValueError(f"canonical cache is not valid JSON: {path}") from error
    if not isinstance(payload, list) or not all(
        isinstance(item, dict) for item in payload
    ):
        raise ValueError("canonical cache must contain an array of objects")
    return _CacheSnapshot(
        path=path,
        raw_bytes=raw_bytes,
        payload=payload,
        sha256=fingerprint(raw_bytes),
    )


def _load_bound_base_cache(
    sequence: LocalSequence,
    base_result: SequenceResult,
    base_root: Path,
) -> _CacheSnapshot:
    path = sequence_render_module._artifact_path(
        base_root,
        base_result.state_cache_file,
    )
    snapshot = _read_cache_snapshot(path)
    payload = snapshot.payload
    expected = sequence_render_module._canonical_state_cache(sequence)
    if _canonical_table(payload) != _canonical_table(expected):
        raise ValueError(
            f"sequence {sequence.sequence_id} base canonical frame/simulation-time "
            "table differs from the local plan; canonical cache invalid"
        )
    if payload != expected:
        raise ValueError(
            f"sequence {sequence.sequence_id} base canonical cache differs from the local plan"
        )
    return snapshot


def _cache_matches(snapshot: _CacheSnapshot) -> bool:
    try:
        current = _read_cache_snapshot(snapshot.path)
    except (OSError, ValueError):
        return False
    return (
        current.raw_bytes == snapshot.raw_bytes
        and current.payload == snapshot.payload
        and current.sha256 == snapshot.sha256
    )


def _restore_cache(snapshot: _CacheSnapshot) -> None:
    snapshot.path.parent.mkdir(parents=True, exist_ok=True)
    metadata = _lstat(snapshot.path)
    if metadata is not None and (
        stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode)
    ):
        if stat.S_ISDIR(metadata.st_mode):
            raise ValueError(
                f"cannot restore canonical cache over a directory: {snapshot.path}"
            )
        snapshot.path.unlink()
    snapshot.path.write_bytes(snapshot.raw_bytes)


def _audit_and_restore_backend_caches(
    job: dict[str, object],
    canonical_cache: list[dict[str, object]],
    base_cache: _CacheSnapshot,
    workspace_cache: _CacheSnapshot,
) -> bool:
    changed = (
        job.get("canonical_state_cache") is not canonical_cache
        or canonical_cache != base_cache.payload
        or not _cache_matches(base_cache)
        or not _cache_matches(workspace_cache)
    )
    if not changed:
        return False
    canonical_cache[:] = json.loads(json.dumps(base_cache.payload))
    job["canonical_state_cache"] = canonical_cache
    _restore_cache(base_cache)
    _restore_cache(workspace_cache)
    if (
        job.get("canonical_state_cache") is not canonical_cache
        or canonical_cache != base_cache.payload
        or not _cache_matches(base_cache)
        or not _cache_matches(workspace_cache)
    ):
        raise RuntimeError("canonical cache restoration failed")
    return True


def _variant_profile(override: SequenceVariantOverride) -> dict[str, object]:
    return override.model_dump(mode="json", exclude={"sequence_id"})


def _render_sequence_override(
    *,
    run_dir: Path,
    artifact_root: Path,
    sequence: LocalSequence,
    base_result: SequenceResult,
    base_cache: _CacheSnapshot,
    override: SequenceVariantOverride,
    backend: SequenceRenderBackend,
    settings: HarnessSettings | None = None,
    performance: PerformanceRecorder | None = None,
) -> SequenceResult:
    store = RunStore.open(run_dir)
    script = store.read_script()
    script_by_id = {scene.scene_id: scene for scene in script.scenes}
    simulation = load_simulation(store.root, script)
    from .settings import resolve_run_settings
    from .pacing_presets import render_pacing_values
    settings = settings or resolve_run_settings(run_dir)
    canonical_cache = json.loads(json.dumps(base_cache.payload))

    state_cache_path = sequence_render_module._artifact_path(
        artifact_root,
        f"videoFiles/sequences/state-cache/{sequence.sequence_id}.json",
    )
    state_cache_path.parent.mkdir(parents=True, exist_ok=True)
    state_cache_path.write_bytes(base_cache.raw_bytes)
    workspace_cache = _read_cache_snapshot(state_cache_path)
    if (
        workspace_cache.raw_bytes != base_cache.raw_bytes
        or workspace_cache.payload != base_cache.payload
    ):
        raise ValueError(
            f"sequence {sequence.sequence_id} workspace canonical cache differs before rendering"
        )
    sequence_directory = artifact_root / "videoFiles" / "sequences" / "final"
    sequence_directory.mkdir(parents=True, exist_ok=True)
    cache_dir = artifact_root / ".render-cache" / "sequences" / sequence.sequence_id
    cache_dir.mkdir(parents=True, exist_ok=True)
    job: dict[str, object] = {
        "job_kind": "sequence",
        "sequence_id": sequence.sequence_id,
        "scene_graph": sequence.scene_graph,
        "canonical_fps": sequence_render_module.load_local_sequence_plan(
            run_dir / "local-sequence-plan.json"
        ).defaults.fps,
        "duration_frames": sequence.duration_frames,
        "frame_count": base_result.frame_count,
        "output_directory": str(cache_dir),
        "output": {
            "width": base_result.width,
            "height": base_result.height,
            "fps": base_result.fps,
        },
        "timeline": sequence_render_module._timeline_payload(sequence),
        "canonical_state_cache": canonical_cache,
        "sample_frames": list(range(base_result.frame_count)),
        "physics": sequence_render_module._physics_payload(simulation),
        "style": sequence_render_module._style_payload(simulation),
        "variant_profile": _variant_profile(override),
    }
    timing = getattr(settings, 'local_video', None)
    if timing is not None:
        job['camera_transition_seconds'] = timing.camera_transition_seconds
    pacing = render_pacing_values(settings)
    if pacing is not None:
        job['pacing'] = pacing
    if not _cache_matches(base_cache) or not _cache_matches(workspace_cache):
        raise ValueError(
            f"sequence {sequence.sequence_id} canonical cache changed before rendering"
        )
    raw_state_report: Path | None = None
    backend_error: BaseException | None = None
    with (
        performance.phase("renderer", sequence_id=sequence.sequence_id, quality="final")
        if performance is not None
        else nullcontext()
    ):
        try:
            raw_state_report = backend.render_frames(job, cache_dir)
        except BaseException as error:
            backend_error = error
    try:
        cache_changed = _audit_and_restore_backend_caches(
            job,
            canonical_cache,
            base_cache,
            workspace_cache,
        )
    except BaseException as restore_error:
        if backend_error is not None:
            raise RuntimeError(
                f"sequence {sequence.sequence_id} canonical cache audit failed after backend error"
            ) from backend_error
        raise restore_error
    if cache_changed:
        mutation_error = ValueError(
            f"sequence {sequence.sequence_id} renderer changed the canonical cache"
        )
        if backend_error is not None:
            raise mutation_error from backend_error
        raise mutation_error
    if backend_error is not None:
        raise backend_error
    if raw_state_report is None:
        raise RuntimeError("sequence backend returned no state report")
    state_report_path = sequence_directory / f"{sequence.sequence_id}-frame-report.json"
    normalized_report = sequence_render_module._normalize_frame_report(
        raw_state_report,
        state_report_path,
        artifact_root=artifact_root,
        sequence_id=sequence.sequence_id,
        frame_count=base_result.frame_count,
        width=base_result.width,
        height=base_result.height,
    )
    if performance is not None:
        performance.record_renderer_report(normalized_report, fps=base_result.fps)

    spec = OutputSpec(
        width=base_result.width,
        height=base_result.height,
        fps=base_result.fps,
        duration_seconds=base_result.frame_count / base_result.fps,
        frames=base_result.frame_count,
    )
    master_path = sequence_directory / f"{sequence.sequence_id}.mp4"
    with (
        performance.phase("ffmpeg_encode", sequence_id=sequence.sequence_id)
        if performance is not None
        else nullcontext()
    ):
        sequence_render_module.encode_frames(
            cache_dir / "frame-%06d.png",
            master_path,
            spec,
        )
    canonical_fps = int(job["canonical_fps"])
    placements: list[AudioPlacement] = []
    for span in sequence.scene_spans:
        placement = sequence_render_module._audio_placement(
            script_by_id[span.scene_id],
            start_frame=span.audio_start_frame,
            end_frame=span.audio_end_frame,
            output_fps=base_result.fps,
            canonical_fps=canonical_fps,
        )
        placements.append(
            AudioPlacement(
                source=store.path(placement.source),
                start_frame=placement.start_frame,
                end_frame=placement.end_frame,
            )
        )
    narrated_path = sequence_directory / f"{sequence.sequence_id}-narrated.mp4"
    with (
        performance.phase("audio_mux", sequence_id=sequence.sequence_id)
        if performance is not None
        else nullcontext()
    ):
        sequence_render_module.mux_audio_timeline(
            master_path,
            placements,
            narrated_path,
            spec,
        )

    original_directory = artifact_root / "videoFiles" / "original"
    original_directory.mkdir(parents=True, exist_ok=True)
    scene_results: list[SceneSliceResult] = []
    for span in sequence.scene_spans:
        scene = script_by_id[span.scene_id]
        output_start = sequence_render_module._output_boundary(
            span.start_frame,
            output_fps=base_result.fps,
            canonical_fps=canonical_fps,
        )
        output_end = sequence_render_module._output_boundary(
            span.end_frame,
            output_fps=base_result.fps,
            canonical_fps=canonical_fps,
        )
        silent_path = original_directory / scene_filename(scene, ".mp4")
        narrated_scene_path = artifact_root / "videoFiles" / scene_filename(scene, ".mp4")
        sequence_render_module.extract_video_segment(
            master_path,
            silent_path,
            start_frame=output_start,
            end_frame=output_end,
            fps=base_result.fps,
        )
        scene_spec = OutputSpec(
            width=base_result.width,
            height=base_result.height,
            fps=base_result.fps,
            duration_seconds=(output_end - output_start) / base_result.fps,
            frames=output_end - output_start,
        )
        scene_placement = sequence_render_module._audio_placement(
            scene,
            start_frame=span.audio_start_frame,
            end_frame=span.audio_end_frame,
            output_fps=base_result.fps,
            canonical_fps=canonical_fps,
            sequence_output_start=output_start,
        )
        with (
            performance.phase("audio_mux", sequence_id=sequence.sequence_id)
            if performance is not None
            else nullcontext()
        ):
            sequence_render_module.mux_audio_timeline(
                silent_path,
                [
                    AudioPlacement(
                        source=store.path(scene_placement.source),
                        start_frame=scene_placement.start_frame,
                        end_frame=scene_placement.end_frame,
                    )
                ],
                narrated_scene_path,
                scene_spec,
            )
        scene_results.append(
            SceneSliceResult(
                scene_id=span.scene_id,
                start_frame=span.start_frame,
                end_frame=span.end_frame,
                frame_count=output_end - output_start,
                silent_file=sequence_render_module._relative_to(
                    artifact_root, silent_path
                ),
                narrated_file=sequence_render_module._relative_to(
                    artifact_root, narrated_scene_path
                ),
            )
        )
    return SequenceResult(
        sequence_id=sequence.sequence_id,
        frame_count=base_result.frame_count,
        width=base_result.width,
        height=base_result.height,
        fps=base_result.fps,
        master_file=sequence_render_module._relative_to(artifact_root, master_path),
        narrated_file=sequence_render_module._relative_to(
            artifact_root, narrated_path
        ),
        state_report_file=sequence_render_module._relative_to(
            artifact_root, state_report_path
        ),
        state_cache_file=sequence_render_module._relative_to(
            artifact_root, state_cache_path
        ),
        scene_slices=scene_results,
    )


def _final_names(recipe: SequenceVariantRecipe) -> tuple[str, str]:
    if recipe.variant_id == "balanced":
        return "final.mp4", "video-only.mp4"
    number = {"explain": "02", "dynamic": "03", "cinematic": "04"}[
        recipe.variant_id
    ]
    filename = f"{number}_{recipe.variant_id}.mp4"
    return (
        f"videoFiles/variants/{filename}",
        f"videoFiles/variants/video-only/{filename}",
    )


def _fresh_variant_workspace(
    workspaces_root: Path, variant_id: VariantId
) -> Path:
    return _create_owned_directory(
        workspaces_root, variant_id, f"{variant_id} variant workspace"
    )


def _verify_workspace_caches(
    sources: list[SequenceArtifactSource],
    base_caches: dict[str, _CacheSnapshot],
) -> dict[str, str]:
    actual: dict[str, str] = {}
    for source in sources:
        result = source.result
        expected = base_caches[result.sequence_id]
        path = sequence_render_module._artifact_path(
            source.root, result.state_cache_file
        )
        snapshot = _read_cache_snapshot(path)
        if (
            snapshot.raw_bytes != expected.raw_bytes
            or snapshot.payload != expected.payload
        ):
            raise ValueError(
                f"sequence {result.sequence_id} canonical cache differs from the base cache"
            )
        actual[result.sequence_id] = snapshot.sha256
    return actual


def _stage_public_artifact(
    source: Path,
    staging_root: Path,
    relative: str,
) -> Path:
    destination = sequence_render_module._artifact_path(staging_root, relative)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


def _protected_publication_artifacts(
    run_dir: Path,
    base_root: Path,
    base_report: SequenceRenderReport,
) -> tuple[list[Path], list[Path]]:
    protected_files = [
        run_dir / "script.json",
        run_dir / "production-plan.json",
        run_dir / "local-sequence-plan.json",
        run_dir / "online-plan.json",
        run_dir / "variant-plan.json",
    ]
    for result in base_report.sequences:
        protected_files.extend(
            sequence_render_module._artifact_path(base_root, relative)
            for relative in (
                result.master_file,
                result.narrated_file,
                result.state_report_file,
                result.state_cache_file,
            )
        )
        for scene_slice in result.scene_slices:
            protected_files.extend(
                sequence_render_module._artifact_path(base_root, relative)
                for relative in (
                    scene_slice.silent_file,
                    scene_slice.narrated_file,
                )
            )
    return protected_files, [base_root / ".render-cache"]


def _validate_public_destinations(
    artifact_root: Path,
    relatives: list[str],
    *,
    protected_files: list[Path],
    protected_roots: list[Path],
) -> list[Path]:
    if tuple(relatives) not in {
        _PUBLIC_DESTINATION_RELATIVES,
        _BALANCED_PUBLIC_DESTINATION_RELATIVES,
    }:
        raise ValueError(
            "public variant destinations differ from a declared publication set"
        )

    lexical_destinations: list[Path] = []
    resolved_destinations: list[Path] = []
    for relative in relatives:
        lexical = artifact_root / relative
        current = artifact_root
        components = [current]
        for part in Path(relative).parts:
            current = current / part
            components.append(current)
        for index, component in enumerate(components):
            metadata = _lstat(component)
            if metadata is None:
                continue
            if stat.S_ISLNK(metadata.st_mode):
                raise ValueError(
                    f"public variant destination or parent cannot be a symlink: {component}"
                )
            if index < len(components) - 1 and not stat.S_ISDIR(metadata.st_mode):
                raise ValueError(
                    f"public variant destination parent is not a directory: {component}"
                )
            if index == len(components) - 1 and not stat.S_ISREG(metadata.st_mode):
                raise ValueError(
                    f"public variant destination is not a file: {component}"
                )
        resolved = sequence_render_module._artifact_path(artifact_root, relative)
        lexical_destinations.append(lexical)
        resolved_destinations.append(resolved)

    lexical_keys = {str(path.absolute()) for path in lexical_destinations}
    resolved_keys = {str(path) for path in resolved_destinations}
    if len(lexical_keys) != len(relatives) or len(resolved_keys) != len(relatives):
        raise ValueError("public variant destinations must be pairwise distinct")

    protected_file_keys = {
        str(path.absolute()) for path in protected_files
    } | {str(path.resolve()) for path in protected_files}
    protected_root_pairs = [(root.absolute(), root.resolve()) for root in protected_roots]
    for lexical, resolved in zip(lexical_destinations, resolved_destinations):
        if (
            str(lexical.absolute()) in protected_file_keys
            or str(resolved) in protected_file_keys
        ):
            raise ValueError(
                f"public variant destination aliases a protected artifact: {lexical}"
            )
        for lexical_root, resolved_root in protected_root_pairs:
            if (
                lexical == lexical_root
                or lexical_root in lexical.parents
                or resolved == resolved_root
                or resolved_root in resolved.parents
            ):
                raise ValueError(
                    f"public variant destination aliases a protected artifact root: {lexical}"
                )
    return lexical_destinations


def _publish_complete_set(
    staging_root: Path,
    artifact_root: Path,
    relatives: list[str],
    transaction_root: Path,
    *,
    protected_files: list[Path],
    protected_roots: list[Path],
) -> None:
    _require_owned_directory(staging_root, "variant publication stage")
    _require_owned_directory(transaction_root, "variant transaction")
    destinations = _validate_public_destinations(
        artifact_root,
        relatives,
        protected_files=protected_files,
        protected_roots=[*protected_roots, transaction_root],
    )
    backup_root = _create_owned_directory(
        transaction_root,
        "publication-backup",
        "variant publication backup",
    )
    published: list[Path] = []
    backed_up: list[tuple[Path, Path]] = []
    remove_backup = True
    try:
        for relative, destination in zip(relatives, destinations):
            source = sequence_render_module._artifact_path(staging_root, relative)
            if not source.is_file():
                raise FileNotFoundError(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                if not destination.is_file():
                    raise ValueError(
                        f"public variant destination is not a file: {destination}"
                    )
                backup = sequence_render_module._artifact_path(backup_root, relative)
                backup.parent.mkdir(parents=True, exist_ok=True)
                destination.replace(backup)
                backed_up.append((destination, backup))
            source.replace(destination)
            published.append(destination)
    except BaseException as publication_error:
        rollback_errors: list[OSError] = []
        for destination in reversed(published):
            try:
                if destination.exists():
                    destination.unlink()
            except OSError as error:
                rollback_errors.append(error)
        for destination, backup in reversed(backed_up):
            try:
                if destination.exists():
                    destination.unlink()
                backup.replace(destination)
            except OSError as error:
                rollback_errors.append(error)
        if rollback_errors:
            remove_backup = False
            raise RuntimeError(
                "variant publication failed and rollback was incomplete"
            ) from publication_error
        raise
    finally:
        if remove_backup:
            _remove_owned_directory(backup_root, "variant publication backup")


def assemble_sequence_variants(
    run_dir: Path,
    production: ProductionPlan,
    local: LocalSequencePlan,
    online: OnlinePlan,
    variant_plan: SequenceVariantPlan,
    base_report: SequenceRenderReport,
    *,
    output_root: Path,
    backend: SequenceRenderBackend | None = None,
    create_references: bool = True,
    variant_mode: VariantMode = "four",
    settings: HarnessSettings | None = None,
    performance: PerformanceRecorder | None = None,
) -> SequenceVariantManifest:
    run_dir = run_dir.resolve()
    from .video_plan_approval import require_current_video_plan_approval
    require_current_video_plan_approval(run_dir)
    bindings = _bind_plan_models(run_dir, production, local, online, variant_plan)
    artifact_root = output_root.absolute()
    issues = validate_sequence_variant_plan(
        variant_plan,
        production,
        local,
        production_path=run_dir / "production-plan.json",
        local_path=run_dir / "local-sequence-plan.json",
        script_path=run_dir / "script.json",
    )
    if issues:
        raise ValueError("; ".join(f"{issue.code}: {issue.message}" for issue in issues))
    if base_report.quality != "final":
        raise ValueError("sequence variants require a final base render")
    if base_report.production_plan_sha256 != bindings.production_sha256:
        raise ValueError("base render production-plan hash differs from variant plan")
    if base_report.local_sequence_plan_sha256 != bindings.local_sha256:
        raise ValueError("base render local-sequence-plan hash differs from variant plan")
    if variant_mode not in {"four", "balanced_only"}:
        raise ValueError(f"unknown variant mode: {variant_mode}")
    from .settings import resolve_run_settings
    settings = settings or (
        resolve_run_settings(run_dir)
        if (run_dir / 'run-settings.json').is_file()
        else HarnessSettings()
    )

    planned_ids = [sequence.sequence_id for sequence in local.sequences]
    base_ids = [result.sequence_id for result in base_report.sequences]
    if base_ids != planned_ids:
        raise ValueError("base render sequence order differs from the local plan")
    base_by_id = {result.sequence_id: result for result in base_report.sequences}
    sequence_by_id = {sequence.sequence_id: sequence for sequence in local.sequences}
    base_root = base_report.artifact_root.resolve()
    protected_files, protected_roots = _protected_publication_artifacts(
        run_dir, base_root, base_report
    )
    base_caches = {
        sequence_id: _load_bound_base_cache(
            sequence_by_id[sequence_id],
            base_by_id[sequence_id],
            base_root,
        )
        for sequence_id in planned_ids
    }

    active_backend = backend or sequence_render_module.backend_for_plan(local, run_dir=run_dir, settings=settings)
    active_backend.check_dependencies()
    outputs: list[SequenceVariantOutput] = []
    transaction_root, workspaces_root = _prepare_transaction_root(artifact_root)
    publication_root = _create_owned_directory(
        transaction_root,
        "publication-stage",
        "variant publication stage",
    )
    publication_relatives: list[str] = []
    state_hashes: dict[str, str] | None = None
    active_variant_phase = None
    try:
        recipes = (
            variant_plan.variants
            if variant_mode == "four"
            else [recipe for recipe in variant_plan.variants if recipe.variant_id == "balanced"]
        )
        for recipe in recipes:
            active_variant_phase = (
                performance.phase("variant", variant_id=recipe.variant_id)
                if performance is not None
                else None
            )
            if active_variant_phase is not None:
                active_variant_phase.__enter__()
            workspace = _fresh_variant_workspace(
                workspaces_root, recipe.variant_id
            )
            overrides = {
                override.sequence_id: override
                for override in recipe.overrides
                if not override.is_base()
            }
            results: list[SequenceResult] = []
            sources: list[SequenceArtifactSource] = []
            rendered_ids: list[str] = []
            reused_ids: list[str] = []
            avoided_copy_files = 0
            avoided_copy_bytes = 0
            for sequence_id in recipe.sequence_ids:
                override = overrides.get(sequence_id)
                if override is None:
                    result = base_by_id[sequence_id]
                    sources.append(
                        SequenceArtifactSource(
                            result=result,
                            root=base_root,
                            reused=True,
                        )
                    )
                    results.append(result)
                    reused_ids.append(sequence_id)
                    copied_files, copied_bytes = _avoided_copy_metrics(
                        result,
                        source_root=base_root,
                    )
                    avoided_copy_files += copied_files
                    avoided_copy_bytes += copied_bytes
                else:
                    result = _render_sequence_override(
                        run_dir=run_dir,
                        artifact_root=workspace,
                        sequence=sequence_by_id[sequence_id],
                        base_result=base_by_id[sequence_id],
                        base_cache=base_caches[sequence_id],
                        override=override,
                        backend=active_backend,
                        settings=settings,
                        performance=performance,
                    )
                    results.append(result)
                    sources.append(
                        SequenceArtifactSource(
                            result=result,
                            root=workspace,
                            reused=False,
                        )
                    )
                    rendered_ids.append(sequence_id)

            recipe_cache_hashes = _verify_workspace_caches(sources, base_caches)
            if state_hashes is None:
                state_hashes = recipe_cache_hashes
            elif recipe_cache_hashes != state_hashes:
                raise ValueError("variant workspaces use different canonical cache hashes")

            workspace_original = workspace / "video-only.mp4"
            workspace_final = workspace / "final.mp4"
            output_fps = results[0].fps
            silent_sequences = [
                sequence_render_module._artifact_path(
                    source.root,
                    source.result.master_file,
                )
                for source in sources
            ]
            expected_duration = (
                sum(source.result.frame_count for source in sources) / output_fps
            )
            sequence_render_module.concat_videos(
                silent_sequences,
                workspace_original,
                expected_duration=expected_duration,
                require_audio=False,
                transition_seconds=0.0,
                transition_fade_seconds=0.0,
                performance=performance,
                performance_labels={
                    "variant_id": recipe.variant_id,
                    "output_kind": "silent",
                },
            )
            sequence_render_module.mux_sequence_narration(
                run_dir, local, results, workspace_original, workspace_final,
                settings=settings,
            )
            render_report = SequenceRenderReport(
                quality="final",
                artifact_root=workspace,
                production_plan_sha256=bindings.production_sha256,
                local_sequence_plan_sha256=bindings.local_sha256,
                sequences=results,
                final_file="final.mp4",
                final_original_file="video-only.mp4",
            )
            if create_references:
                sequence_render_module.create_online_references(
                    run_dir,
                    online,
                    render_report,
                    output_root=workspace,
                    sequence_sources={
                        source.result.sequence_id: source for source in sources
                    },
                )
            qa_report = run_sequence_qa(
                run_dir,
                production,
                local,
                online,
                render_report,
                quality="final",
                settings=settings,
                performance=performance,
                sequence_sources={
                    source.result.sequence_id: source for source in sources
                },
            )
            if qa_report.status != "passed":
                raise ValueError(f"variant {recipe.variant_id} failed sequence QA")

            final_relative, original_relative = _final_names(recipe)
            staged_final = _stage_public_artifact(
                workspace_final, publication_root, final_relative
            )
            staged_original = _stage_public_artifact(
                workspace_original, publication_root, original_relative
            )
            publication_relatives.extend([final_relative, original_relative])
            output = SequenceVariantOutput(
                variant_id=recipe.variant_id,
                final_file=final_relative,
                original_file=original_relative,
                rendered_sequence_ids=rendered_ids,
                reused_sequence_ids=reused_ids,
                final_sha256=script_sha256(staged_final),
                original_sha256=script_sha256(staged_original),
                qa_status="passed",
            )
            outputs.append(output)
            if performance is not None:
                performance.record_variant_output(
                    variant_id=output.variant_id,
                    rendered_sequence_ids=output.rendered_sequence_ids,
                    reused_sequence_ids=output.reused_sequence_ids,
                    rendered_frame_count=sum(
                        source.result.frame_count
                        for source in sources
                        if not source.reused
                    ),
                    reused_frame_count=sum(
                        source.result.frame_count
                        for source in sources
                        if source.reused
                    ),
                    avoided_copy_files=avoided_copy_files,
                    avoided_copy_bytes=avoided_copy_bytes,
                )
            if active_variant_phase is not None:
                active_variant_phase.__exit__(None, None, None)
                active_variant_phase = None

        if state_hashes is None:
            raise ValueError("sequence variant assembly produced no cache hashes")
        for snapshot in base_caches.values():
            if not _cache_matches(snapshot):
                _restore_cache(snapshot)
                raise ValueError("base canonical cache changed during variant assembly")
        manifest = SequenceVariantManifest(
            production_plan_sha256=bindings.production_sha256,
            local_sequence_plan_sha256=bindings.local_sha256,
            variant_plan_sha256=bindings.variant_sha256,
            script_sha256=bindings.script_sha256,
            state_cache_sha256=state_hashes,
            variants=outputs,
        )
        manifest_relative = "videoFiles/variants/variants.json"
        manifest_path = sequence_render_module._artifact_path(
            publication_root, manifest_relative
        )
        atomic_write(manifest_path, manifest.model_dump_json(indent=2) + "\n")
        publication_relatives.append(manifest_relative)
        require_current_video_plan_approval(run_dir)
        _publish_complete_set(
            publication_root,
            artifact_root,
            publication_relatives,
            transaction_root,
            protected_files=protected_files,
            protected_roots=protected_roots,
        )
        return manifest
    finally:
        if active_variant_phase is not None:
            active_variant_phase.__exit__(*sys.exc_info())
        if _lstat(publication_root) is not None:
            _remove_owned_directory(
                publication_root, "variant publication stage"
            )
