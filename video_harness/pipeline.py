from __future__ import annotations

import argparse
import shutil
import stat
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import Field

from .models import ScriptArtifact, StrictModel
from .performance import PerformanceRecorder
from .production import load_production_plan, script_sha256, validate_plan_against_script
from .production_models import ProductionPlan
from .prompt_compiler import PromptArtifactManifest, write_compiled_artifacts
from .sequence_models import LocalSequencePlan, OnlinePlan
from .sequence_plans import load_local_sequence_plan, load_online_plan, validate_sequence_plans
from .settings import (
    HarnessSettings,
    OutputMode,
    VariantMode,
    resolve_run_settings,
    settings_sha256,
    write_settings_snapshot,
)
from .storage import atomic_write, scene_filename
from .variants import SequenceVariantPlan, load_variant_plan, validate_sequence_variant_plan
from .video_plan_approval import require_current_video_plan_approval
from .stage_approvals import require_stage_approval


ArtifactState = Literal["generated", "reused", "planned", "skipped"]


class PipelineArtifact(StrictModel):
    path: str
    state: ArtifactState


class PipelineReport(StrictModel):
    schema_version: Literal[1] = 1
    status: Literal["complete"] = "complete"
    quality: Literal["draft", "final"]
    output_mode: OutputMode
    variant_mode: VariantMode
    settings_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    script_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    production_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    local_sequence_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    online_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifacts: list[PipelineArtifact]


@dataclass(frozen=True)
class PipelineContext:
    run_dir: Path
    script: ScriptArtifact
    production: ProductionPlan
    local: LocalSequencePlan
    online: OnlinePlan
    variant: SequenceVariantPlan


def load_pipeline_context(run_dir: Path) -> PipelineContext:
    run_root = run_dir.resolve()
    script = ScriptArtifact.model_validate_json((run_root / "script.json").read_text(encoding="utf-8"))
    production = load_production_plan(run_root / "production-plan.json")
    local = load_local_sequence_plan(run_root / "local-sequence-plan.json")
    online = load_online_plan(run_root / "online-plan.json")
    loaded_variant = load_variant_plan(run_root / "variant-plan.json")
    if production.schema_version != 2 or not isinstance(loaded_variant, SequenceVariantPlan):
        raise ValueError("produce requires schema version 2 production and variant plans")
    issues = [
        *validate_plan_against_script(production, script, run_root / "script.json", run_root),
        *validate_sequence_plans(
            production, local, online, script,
            script_path=run_root / "script.json",
            production_path=run_root / "production-plan.json",
        ),
        *validate_sequence_variant_plan(
            loaded_variant, production, local,
            production_path=run_root / "production-plan.json",
            local_path=run_root / "local-sequence-plan.json",
            script_path=run_root / "script.json",
        ),
    ]
    if issues:
        codes = ", ".join(dict.fromkeys(issue.code for issue in issues))
        raise ValueError(f"pipeline plan validation failed: {codes}")
    return PipelineContext(run_root, script, production, local, online, loaded_variant)


def validate_pipeline_inputs(context: PipelineContext, settings: HarnessSettings) -> list[str]:
    """Validate authored input media without requiring any published output."""
    issues: list[str] = []
    for scene in context.script.scenes:
        audio_relative = scene.audio_file or f"audioFiles/{scene_filename(scene, '.mp3')}"
        audio_path = context.run_dir / audio_relative
        narration_path = context.run_dir / "audioFiles" / scene_filename(scene, ".txt")
        if not audio_path.is_file() or audio_path.stat().st_size == 0:
            issues.append(f"missing audio for scene {scene.scene_id}")
            continue
        if not narration_path.is_file() or narration_path.stat().st_size == 0:
            issues.append(f"missing narration for scene {scene.scene_id}")
        try:
            from mutagen.mp3 import MP3

            measured = float(MP3(audio_path).info.length)
        except Exception as error:
            issues.append(f"invalid audio for scene {scene.scene_id}: {error}")
            continue
        if not settings.voice.min_scene_seconds <= measured <= settings.voice.max_scene_seconds:
            issues.append(f"invalid duration for scene {scene.scene_id}: {measured:.3f}")
        if scene.duration_seconds is None:
            issues.append(f"missing duration metadata for scene {scene.scene_id}")
        elif abs(scene.duration_seconds - measured) > settings.qa.duration_tolerance_seconds:
            issues.append(f"duration metadata mismatch for scene {scene.scene_id}")
    return issues


def _input_hashes(run_dir: Path) -> dict[str, str]:
    return {
        "script_sha256": script_sha256(run_dir / "script.json"),
        "production_plan_sha256": script_sha256(run_dir / "production-plan.json"),
        "local_sequence_plan_sha256": script_sha256(run_dir / "local-sequence-plan.json"),
        "online_plan_sha256": script_sha256(run_dir / "online-plan.json"),
    }


def _safe_relative(value: str) -> Path:
    relative = PurePosixPath(value)
    if not relative.parts or relative.is_absolute() or ".." in relative.parts or "\\" in value:
        raise ValueError(f"pipeline artifact path must be a safe relative descendant: {value}")
    return Path(*relative.parts)


@contextmanager
def _preserve_artifacts(run_dir: Path, relatives: Sequence[str]) -> Iterator[None]:
    """Restore prior public bytes when a later pipeline gate fails."""
    unique = list(dict.fromkeys(relatives))
    paths = [(relative, run_dir / _safe_relative(relative)) for relative in unique]
    with tempfile.TemporaryDirectory(prefix=".pipeline-backup-", dir=run_dir) as temporary:
        backup_root = Path(temporary)
        existed: dict[str, bool] = {}
        for relative, path in paths:
            existed[relative] = path.is_file()
            if existed[relative]:
                backup = backup_root / _safe_relative(relative)
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, backup)
        try:
            yield
        except BaseException:
            for relative, path in reversed(paths):
                if path.is_file():
                    path.unlink()
                if existed[relative]:
                    backup = backup_root / _safe_relative(relative)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(backup, path)
            raise


def _prompt_paths(context: PipelineContext) -> list[str]:
    return sorted([
        "video-plan.md",
        *(f"videoFiles/prompts/local/{sequence.sequence_id}.md" for sequence in context.local.sequences),
        *(path for shot in context.online.shots for path in (shot.prompt_file, shot.metadata_file)),
    ])


def _write_staged_prompts(context: PipelineContext) -> PromptArtifactManifest:
    with tempfile.TemporaryDirectory(prefix=".pipeline-prompts-", dir=context.run_dir) as temporary:
        staging = Path(temporary)
        from .creative_gates import stage_creative_reviews
        stage_creative_reviews(context.run_dir, staging)
        manifest = write_compiled_artifacts(
            staging, context.production, context.script,
            local_plan=context.local, online_plan=context.online,
        )
        for relative in manifest.generated:
            source = staging / _safe_relative(relative)
            if not source.is_file():
                raise ValueError(f"prompt compiler did not stage declared artifact: {relative}")
            destination = context.run_dir / _safe_relative(relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            source.replace(destination)
        return manifest


def _write_settings_snapshot(run_dir: Path, settings: HarnessSettings) -> None:
    write_settings_snapshot(run_dir, settings)


def _write_pipeline_report(run_dir: Path, report: PipelineReport) -> None:
    atomic_write(run_dir / "pipeline-report.json", report.model_dump_json(indent=2) + "\n")


def validate_published_run(run_dir: Path, *, settings: HarnessSettings) -> list[object]:
    from .validation import validate_run

    return validate_run(run_dir, settings=settings)


def _render_local(*args, **kwargs):
    # Deliberately lazy: prompts_only works without renderer/FFmpeg dependencies.
    from .produce_local import produce_local as render_local

    return render_local(*args, **kwargs)


def produce_local(*args, **kwargs):
    """Lazy injection boundary for the local renderer."""
    return _render_local(*args, **kwargs)


def _artifacts_from_prompt_manifest(manifest: PromptArtifactManifest) -> list[PipelineArtifact]:
    return [
        *(PipelineArtifact(path=path, state="generated") for path in manifest.generated),
        *(PipelineArtifact(path=path, state="planned") for path in manifest.planned_references),
    ]


def _artifacts_from_local_report(
    report: object,
    context: PipelineContext,
    mode: OutputMode,
    quality: Literal["draft", "final"],
) -> list[PipelineArtifact]:
    paths = [
        getattr(report, "draft_qa_file", None), getattr(report, "final_qa_file", None),
        getattr(report, "final_file", None), getattr(report, "final_original_file", None),
        *getattr(report, "variant_files", []),
    ]
    if quality == "draft":
        paths.extend(["final-draft.mp4", "video-only-draft.mp4"])
    artifacts = [PipelineArtifact(path=path, state="generated") for path in paths if path]
    artifacts.extend(
        PipelineArtifact(
            path=shot.reference_video_file,
            state="generated" if mode == "all" and quality == "final" else "planned",
        )
        for shot in context.online.shots if shot.reference_video_file
    )
    return artifacts


def _stable_artifacts(artifacts: Sequence[PipelineArtifact]) -> list[PipelineArtifact]:
    by_path: dict[str, PipelineArtifact] = {}
    for artifact in artifacts:
        existing = by_path.get(artifact.path)
        if existing is not None and existing.state != artifact.state:
            if {existing.state, artifact.state} == {"planned", "generated"}:
                by_path[artifact.path] = PipelineArtifact(
                    path=artifact.path, state="generated"
                )
                continue
            raise ValueError(f"pipeline artifact has conflicting states: {artifact.path}")
        by_path[artifact.path] = artifact
    return [by_path[path] for path in sorted(by_path)]


def _video_protection_paths(context: PipelineContext, settings: HarnessSettings) -> list[str]:
    from .validation import _expected_v2_owned_files

    expected = _expected_v2_owned_files(
        context.script, context.local, context.online,
        preview_interval_seconds=settings.render.preview_interval_seconds,
        compile_prompts=settings.pipeline.output_mode == "all",
        create_references=settings.pipeline.output_mode == "all",
        include_video=True, variant_mode=settings.pipeline.variant_mode,
    )
    expected.update({"final.mp4", "video-only.mp4", "final-draft.mp4", "video-only-draft.mp4", "local-production-report.json"})
    return sorted(expected)


def _existing_owned_paths(run_dir: Path, roots: Sequence[str]) -> list[str]:
    """Include stale owned files in an outer rollback, not just this plan's manifest."""
    paths: set[str] = set()
    for relative_root in roots:
        root = run_dir / relative_root
        if not root.exists():
            continue
        metadata = root.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise ValueError(f"pipeline owned artifact root is not a plain directory: {root}")
        for path in root.rglob("*"):
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                raise ValueError(f"pipeline owned artifact cannot be a symlink: {path}")
            if stat.S_ISREG(metadata.st_mode):
                paths.add(path.relative_to(run_dir).as_posix())
    for relative in (
        "video-plan.md",
        "video-plan-approval.json",
        "final-draft.mp4",
        "video-only-draft.mp4",
        "final.mp4",
        "video-only.mp4",
        "qa-report.json",
        "local-production-report.json",
    ):
        if (run_dir / relative).is_file():
            paths.add(relative)
    return sorted(paths)


def produce(
    run_dir: Path,
    *,
    quality: Literal["draft", "final"] = "draft",
    output_mode: OutputMode | None = None,
    variant_mode: VariantMode | None = None,
    refresh_settings: bool = False,
    force: bool = False,
) -> PipelineReport:
    if quality not in {"draft", "final"}:
        raise ValueError("quality must be draft or final")
    run_dir = run_dir.resolve()
    settings = resolve_run_settings(
        run_dir,
        cli_overrides={"pipeline": {"output_mode": output_mode, "variant_mode": variant_mode}},
        refresh=refresh_settings,
        persist=False,
    )
    context = load_pipeline_context(run_dir)
    input_issues = validate_pipeline_inputs(context, settings)
    if input_issues:
        raise ValueError(f"input validation failed: {'; '.join(str(item) for item in input_issues)}")
    require_current_video_plan_approval(run_dir)
    require_stage_approval(run_dir, quality)
    hashes = _input_hashes(run_dir)
    mode = settings.pipeline.output_mode
    protected = ["run-settings.json", "pipeline-report.json", "render-performance.json"]
    if mode != "video_only":
        protected.extend(_prompt_paths(context))
        protected.extend(_existing_owned_paths(run_dir, ("videoFiles/prompts/local", "videoFiles/prompts/online")))
    if mode != "prompts_only":
        protected.extend(_video_protection_paths(context, settings))
        protected.extend(
            _existing_owned_paths(
                run_dir,
                (
                    "videoFiles/sequences",
                    "videoFiles/draft",
                    "videoFiles/original",
                    "videoFiles/previews/half-second",
                    "videoFiles/onlineReferences",
                    "videoFiles/variants",
                ),
            )
        )

    with _preserve_artifacts(run_dir, protected):
        performance = PerformanceRecorder(
            quality=quality,
            encoder_settings={
                "codec": "libx264",
                "preset": settings.render.x264_preset,
                "crf": settings.render.x264_crf,
            },
        )
        prompt_manifest = _write_staged_prompts(context) if mode != "video_only" else None
        local_report = (
            produce_local(
                run_dir, quality=quality, force=force, settings=settings,
                compile_prompts=mode == "all", create_references=mode == "all",
                variant_mode=settings.pipeline.variant_mode,
                performance=performance,
            ) if mode != "prompts_only" else None
        )
        _write_settings_snapshot(run_dir, settings)
        if local_report is not None:
            performance.write_performance_report(run_dir)
        artifacts: list[PipelineArtifact] = []
        if prompt_manifest is not None:
            artifacts.extend(_artifacts_from_prompt_manifest(prompt_manifest))
        if local_report is not None:
            artifacts.extend(_artifacts_from_local_report(local_report, context, mode, quality))
        report = PipelineReport(
            quality=quality, output_mode=mode, variant_mode=settings.pipeline.variant_mode,
            settings_sha256=settings_sha256(settings), artifacts=_stable_artifacts(artifacts), **hashes,
        )
        _write_pipeline_report(run_dir, report)
        if quality == "final" and mode != "prompts_only":
            publication_issues = validate_published_run(run_dir, settings=settings)
            if publication_issues:
                codes = ", ".join(str(getattr(issue, "code", issue)) for issue in publication_issues)
                raise ValueError(f"published artifact validation failed: {codes}")
        return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Produce a settings-aware schema-v2 video run.")
    parser.add_argument("run_directory", type=Path, help="schema-v2 run directory")
    parser.add_argument(
        "--quality", choices=("draft", "final"), default="draft",
        help="default: draft; review the low-resolution video before explicitly selecting final",
    )
    parser.add_argument("--output-mode", choices=("all", "video_only", "prompts_only"), default=None)
    parser.add_argument("--variant-mode", choices=("four", "balanced_only"), default=None)
    parser.add_argument("--refresh-settings", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = produce(args.run_directory, quality=args.quality, output_mode=args.output_mode,
                         variant_mode=args.variant_mode, refresh_settings=args.refresh_settings, force=args.force)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"production failed: {error}")
        return 1
    print(f"production complete: mode={report.output_mode} report={args.run_directory / 'pipeline-report.json'}")
    if report.quality == "draft" and report.output_mode != "prompts_only":
        print(f"draft ready for review: {args.run_directory.resolve() / 'final-draft.mp4'}")
        print("Show the draft to the user first; use --quality final after feedback.")
    return 0
