from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import Field

from .models import ScriptArtifact, StrictModel
from .performance import PerformanceRecorder
from .production import load_production_plan, script_sha256, validate_plan_against_script
from .production_models import ProductionPlan
from .prompt_compiler import write_compiled_artifacts
from .sequence_models import LocalSequencePlan, OnlinePlan
from .sequence_plans import (
    load_local_sequence_plan,
    load_online_plan,
    validate_sequence_plans,
)
from .sequence_qa import QaReport, run_sequence_qa
from .sequence_render import (
    SequenceRenderReport,
    create_online_references,
    render_sequence_quality,
)
from .sequence_variants import SequenceVariantManifest, assemble_sequence_variants
from .settings import HarnessSettings, VariantMode, resolve_run_settings
from .storage import atomic_write, scene_filename
from .validation import validate_run
from .variants import (
    SequenceVariantPlan,
    load_variant_plan,
    validate_sequence_variant_plan,
)


@dataclass(frozen=True)
class LocalProductionContext:
    run_dir: Path
    script: ScriptArtifact
    production: ProductionPlan
    local: LocalSequencePlan
    online: OnlinePlan
    variant: SequenceVariantPlan


class LocalProductionReport(StrictModel):
    schema_version: Literal[1] = 1
    status: Literal["complete"] = "complete"
    quality: Literal["draft", "final"]
    script_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    production_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    local_sequence_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    online_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    draft_qa_file: str
    final_qa_file: str | None = None
    final_file: str | None = None
    final_original_file: str | None = None
    reference_files: list[str] = Field(default_factory=list)
    variant_files: list[str] = Field(default_factory=list)


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


def _require_lexical_root(path: Path, label: str) -> Path:
    absolute = path.absolute()
    chain = [absolute, *absolute.parents]
    for component in reversed(chain):
        metadata = _lstat(component)
        if metadata is None:
            continue
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError(f"{label} cannot contain a symlink: {component}")
    _require_plain_directory(absolute, label)
    resolved = absolute.resolve()
    if resolved != absolute:
        raise ValueError(f"{label} cannot contain symlink aliases: {path}")
    return resolved


def _safe_relative(value: str) -> PurePosixPath:
    declared = PurePosixPath(value)
    if (
        not declared.parts
        or declared.is_absolute()
        or ".." in declared.parts
        or "\\" in value
    ):
        raise ValueError(f"artifact path must be a safe relative descendant: {value}")
    return declared


def _lexical_destination(root: Path, relative: str) -> Path:
    declared = _safe_relative(relative)
    current = root
    parts = list(declared.parts)
    for index, part in enumerate(parts):
        current = current / part
        metadata = _lstat(current)
        if metadata is None:
            continue
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError(f"publication destination cannot be a symlink: {current}")
        if index < len(parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
            raise ValueError(f"publication parent is not a directory: {current}")
        if index == len(parts) - 1 and not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"publication destination is not a file: {current}")
    resolved = current.resolve(strict=False)
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"publication destination escapes run directory: {relative}")
    return current


def _ensure_plain_parents(root: Path, destination: Path) -> None:
    relative_parent = destination.parent.relative_to(root)
    current = root
    for part in relative_parent.parts:
        current = current / part
        metadata = _lstat(current)
        if metadata is None:
            current.mkdir()
            metadata = current.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise ValueError(f"publication parent must be a plain directory: {current}")


def _staged_manifest(staging: Path) -> list[tuple[str, Path]]:
    staging = _require_lexical_root(staging, "final staging directory")
    manifest: list[tuple[str, Path]] = []
    for current_text, directory_names, file_names in os.walk(staging, followlinks=False):
        current = Path(current_text)
        _require_plain_directory(current, "staging directory")
        kept_directories: list[str] = []
        for name in directory_names:
            child = current / name
            metadata = child.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                raise ValueError(f"staged directory cannot be a symlink: {child}")
            if not stat.S_ISDIR(metadata.st_mode):
                raise ValueError(f"staged directory is invalid: {child}")
            relative = child.relative_to(staging)
            if relative.parts and relative.parts[0] == ".sequence-variants":
                continue
            kept_directories.append(name)
        directory_names[:] = kept_directories
        for name in file_names:
            source = current / name
            metadata = source.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                raise ValueError(f"staged file cannot be a symlink: {source}")
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError(f"staged artifact must be a regular file: {source}")
            relative = source.relative_to(staging).as_posix()
            manifest.append((relative, source))
    manifest.sort(key=lambda item: item[0])
    relatives = [relative for relative, _ in manifest]
    if len(relatives) != len(set(relatives)):
        raise ValueError("staged artifact destinations must be unique")
    return manifest


def _replace_file(source: Path, destination: Path) -> None:
    source.replace(destination)


def load_local_production_context(run_dir: Path) -> LocalProductionContext:
    run_root = _require_lexical_root(run_dir, "run directory")
    script = ScriptArtifact.model_validate_json(
        (run_root / "script.json").read_text(encoding="utf-8")
    )
    production = load_production_plan(run_root / "production-plan.json")
    if production.schema_version != 2:
        raise ValueError("produce-local requires production schema version 2")
    local = load_local_sequence_plan(run_root / "local-sequence-plan.json")
    online = load_online_plan(run_root / "online-plan.json")
    variant_artifact = load_variant_plan(run_root / "variant-plan.json")
    if not isinstance(variant_artifact, SequenceVariantPlan):
        raise ValueError("produce-local requires a schema version 2 variant plan")

    semantic_issues = [
        *validate_plan_against_script(
            production,
            script,
            run_root / "script.json",
            run_root,
        ),
        *validate_sequence_plans(
            production,
            local,
            online,
            script,
            script_path=run_root / "script.json",
            production_path=run_root / "production-plan.json",
        ),
        *validate_sequence_variant_plan(
            variant_artifact,
            production,
            local,
            production_path=run_root / "production-plan.json",
            local_path=run_root / "local-sequence-plan.json",
            script_path=run_root / "script.json",
        ),
    ]
    if semantic_issues:
        codes = ", ".join(dict.fromkeys(issue.code for issue in semantic_issues))
        raise ValueError(f"local production plan validation failed: {codes}")
    return LocalProductionContext(
        run_dir=run_root,
        script=script,
        production=production,
        local=local,
        online=online,
        variant=variant_artifact,
    )


def require_passed(report: QaReport, label: str) -> None:
    if report.status != "passed":
        raise ValueError(f"{label} failed")


@contextmanager
def final_staging_directory(run_dir: Path) -> Iterator[Path]:
    run_root = _require_lexical_root(run_dir, "run directory")
    staging = Path(tempfile.mkdtemp(prefix=".local-final-", dir=run_root)).absolute()
    completed = False
    try:
        _require_plain_directory(staging, "final staging directory")
        resolved = staging.resolve()
        if resolved.parent != run_root:
            raise ValueError("final staging directory must be directly beneath the run")
        yield resolved
        completed = True
    finally:
        # Keep costly renders and diagnostics when a later QA/publication gate
        # fails. Published files still use the existing rollback transaction.
        if completed:
            shutil.rmtree(staging)


_INTERNAL_STAGING_PREFIXES = (".render-cache/",)
_APPROVED_DRAFT_DIRECTORIES = (
    ".render-cache/sequences/draft",  # frames the draft QA re-reads
    "videoFiles/sequences/draft",
    "videoFiles/sequences/state-cache",
    "videoFiles/draft",
)


def _seed_approved_draft(run_dir: Path, staging: Path) -> None:
    """Copy the reviewed draft into the final stage so its render records can be reused.

    Reuse still requires each sequence's render fingerprint to match; anything
    stale is rendered again exactly as before.
    """
    for relative in _APPROVED_DRAFT_DIRECTORIES:
        source = run_dir / relative
        if source.is_dir() and not source.is_symlink():
            shutil.copytree(source, staging / relative, dirs_exist_ok=True)


def _is_documented_internal(relative: str) -> bool:
    return relative.startswith(_INTERNAL_STAGING_PREFIXES)


def _fixed_variant_paths() -> dict[str, tuple[str, str]]:
    return {
        "balanced": ("final.mp4", "video-only.mp4"),
        "explain": (
            "videoFiles/variants/02_explain.mp4",
            "videoFiles/variants/video-only/02_explain.mp4",
        ),
        "dynamic": (
            "videoFiles/variants/03_dynamic.mp4",
            "videoFiles/variants/video-only/03_dynamic.mp4",
        ),
        "cinematic": (
            "videoFiles/variants/04_cinematic.mp4",
            "videoFiles/variants/video-only/04_cinematic.mp4",
        ),
    }


def _derive_owned_public_manifest(
    context: LocalProductionContext,
    draft_qa: QaReport,
    final_qa: QaReport,
    *,
    compile_prompts: bool,
    create_references: bool,
    variant_mode: VariantMode,
    settings: HarnessSettings | None = None,
) -> set[str]:
    relatives = {
        "final-draft.mp4",
        "video-only-draft.mp4",
        "final.mp4",
        "video-only.mp4",
        "videoFiles/sequences/draft/qa-report.json",
        "qa-report.json",
    }
    run_dir = getattr(context, "run_dir", None)
    if settings is not None:
        from .localize import expected_language_outputs
        relatives.update(expected_language_outputs(settings))
    if compile_prompts or (
        run_dir is not None and (run_dir / "video-plan.md").is_file()
    ):
        relatives.add("video-plan.md")
    if run_dir is not None and (run_dir / "video-plan-approval.json").is_file():
        relatives.add("video-plan-approval.json")
    if compile_prompts:
        relatives.update(
            f"videoFiles/prompts/local/{sequence.sequence_id}.md"
            for sequence in context.local.sequences
        )
        for shot in context.online.shots:
            relatives.update((shot.prompt_file, shot.metadata_file))
    if create_references:
        relatives.update(
            shot.reference_video_file
            for shot in context.online.shots
            if shot.reference_video_file is not None
        )
    script_by_id = {scene.scene_id: scene for scene in context.script.scenes}
    for sequence in context.local.sequences:
        relatives.add(f"videoFiles/sequences/state-cache/{sequence.sequence_id}.json")
        for quality in ("draft", "final"):
            prefix = f"videoFiles/sequences/{quality}/{sequence.sequence_id}"
            if (getattr(sequence, "renderer", None) or getattr(context.local, "renderer", "threejs")) == "blender":
                relatives.add(f"{prefix}.blend")
            relatives.update(
                {
                    f"{prefix}.mp4",
                    f"{prefix}-narrated.mp4",
                    f"{prefix}-frame-report.json",
                    f"{prefix}-render-record.json",
                }
            )
        for span in sequence.scene_spans:
            name = scene_filename(script_by_id[span.scene_id], ".mp4")
            relatives.update(
                {
                    f"videoFiles/draft/original/{name}",
                    f"videoFiles/draft/{name}",
                    f"videoFiles/original/{name}",
                    f"videoFiles/{name}",
                }
            )
    selected_variant_ids = (
        _fixed_variant_paths()
        if variant_mode == "four"
        else {"balanced": _fixed_variant_paths()["balanced"]}
    )
    relatives.add("videoFiles/variants/variants.json")
    for final_path, original_path in selected_variant_ids.values():
        relatives.update((final_path, original_path))

    qa_paths: set[str] = set()
    known_sequence_ids = {sequence.sequence_id for sequence in context.local.sequences}
    expected_contact_sheet = "videoFiles/previews/half-second/contact-sheet.png"
    for report in (draft_qa, final_qa):
        if report.contact_sheet_file != expected_contact_sheet:
            raise ValueError(
                f"QA report declares unexpected contact sheet: {report.contact_sheet_file}"
            )
        qa_paths.add(report.contact_sheet_file)
        for result in report.sequence_results:
            if result.sequence_id not in known_sequence_ids:
                raise ValueError(
                    f"QA report declares an unknown sequence: {result.sequence_id}"
                )
            expected_parent = PurePosixPath(
                "videoFiles", "previews", "half-second", result.sequence_id
            )
            for value in result.preview_files:
                path = PurePosixPath(value)
                timestamp = path.stem
                if (
                    path.parent != expected_parent
                    or path.suffix != ".png"
                    or not timestamp.endswith("ms")
                    or not timestamp[:-2].isdigit()
                ):
                    raise ValueError(
                        f"QA report declares an unexpected preview artifact: {value}"
                    )
                qa_paths.add(value)
    relatives.update(qa_paths)
    return relatives


def _current_owned_public_files(run_dir: Path) -> set[str]:
    roots = (
        "videoFiles/prompts/local",
        "videoFiles/prompts/online",
        "videoFiles/sequences",
        "videoFiles/draft",
        "videoFiles/original",
        "videoFiles/previews/half-second",
        "videoFiles/onlineReferences",
        "videoFiles/variants",
        "subtitles",
    )
    files: set[str] = set()
    for relative_root in roots:
        root = run_dir / relative_root
        metadata = _lstat(root)
        if metadata is None:
            continue
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise ValueError(f"owned artifact root must be a plain directory: {root}")
        for path in root.rglob("*"):
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                raise ValueError(f"owned artifact path cannot be a symlink: {path}")
            if stat.S_ISREG(metadata.st_mode):
                files.add(path.relative_to(run_dir).as_posix())
    video_root = run_dir / "videoFiles"
    if video_root.is_dir():
        files.update(
            path.relative_to(run_dir).as_posix()
            for path in video_root.glob("[0-9][0-9]_*.mp4")
            if path.is_file() and not path.is_symlink()
        )
    for relative in (
        "video-plan.md",
        "video-plan-approval.json",
        "final-draft.mp4",
        "video-only-draft.mp4",
        "final.mp4",
        "video-only.mp4",
        "qa-report.json",
    ):
        if _lstat(run_dir / relative) is not None:
            files.add(relative)
    # Language layers: final-<lang>.mp4 / final-draft-<lang>.mp4 are owned so dropped languages get swept.
    for pattern in ("final-*.mp4", "final-draft-*.mp4", "final-*.m4a", "final-draft-*.m4a"):
        files.update(path.name for path in run_dir.glob(pattern) if path.is_file() and not path.is_symlink() and path.name != "final-draft.mp4")
    return files


def _stage_review_artifacts(
    run_dir: Path,
    staging: Path,
    *,
    video_plan_already_staged: bool,
) -> None:
    for relative in ("video-plan.md", "video-plan-approval.json"):
        if relative == "video-plan.md" and video_plan_already_staged:
            continue
        source = run_dir / relative
        metadata = _lstat(source)
        if metadata is None:
            continue
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"review artifact must be a plain file: {source}")
        destination = staging / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def _current_obsolete_owned_directories(
    run_dir: Path,
    context: LocalProductionContext,
) -> set[str]:
    preview_root = run_dir / "videoFiles/previews/half-second"
    metadata = _lstat(preview_root)
    if metadata is None:
        return set()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError(
            f"owned preview root must be a plain directory: {preview_root}"
        )
    expected = {sequence.sequence_id for sequence in context.local.sequences}
    obsolete: set[str] = set()
    for path in preview_root.rglob("*"):
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError(f"owned preview path cannot be a symlink: {path}")
        if not stat.S_ISDIR(metadata.st_mode):
            continue
        relative = path.relative_to(preview_root)
        if len(relative.parts) != 1 or relative.parts[0] not in expected:
            obsolete.add(path.relative_to(run_dir).as_posix())
    return obsolete


def _lexical_owned_directory(root: Path, relative: str) -> Path:
    declared = _safe_relative(relative)
    current = root
    for part in declared.parts:
        current = current / part
        metadata = _lstat(current)
        if metadata is None:
            raise ValueError(f"obsolete directory does not exist: {relative}")
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError(f"obsolete directory cannot contain a symlink: {current}")
        if not stat.S_ISDIR(metadata.st_mode):
            raise ValueError(f"obsolete directory path is not a directory: {current}")
    resolved = current.resolve()
    if root not in resolved.parents:
        raise ValueError(f"obsolete directory escapes run directory: {relative}")
    return current


def publish_staged_outputs(
    run_dir: Path,
    staging: Path,
    *,
    expected_relatives: set[str] | None = None,
    obsolete_relatives: set[str] | None = None,
    obsolete_directories: set[str] | None = None,
) -> list[Path]:
    run_root = _require_lexical_root(run_dir, "run directory")
    staging_root = _require_lexical_root(staging, "final staging directory")
    if staging_root.parent != run_root:
        raise ValueError("final staging directory must be directly beneath the run")
    manifest = _staged_manifest(staging_root)
    if any(relative == 'final.mp4' for relative, _ in manifest):
        from .video_plan_approval import require_current_video_plan_approval
        from .creative_gates import require_rendered_continuity
        require_current_video_plan_approval(run_root)
        from .stage_approvals import require_stage_approval
        require_stage_approval(run_root, 'final')
        require_rendered_continuity(run_root, staging_root)
        from .creative_gates import require_text_render
        require_text_render(run_root, staging_root, 'final')
    if expected_relatives is not None:
        staged_public = {
            relative for relative, _ in manifest if not _is_documented_internal(relative)
        }
        if staged_public != expected_relatives:
            missing = sorted(expected_relatives - staged_public)
            extra = sorted(staged_public - expected_relatives)
            raise ValueError(
                f"staged artifact manifest differs: missing={missing}, extra={extra}"
            )
    obsolete = set(obsolete_relatives or ())
    if expected_relatives is not None and obsolete & expected_relatives:
        raise ValueError("obsolete artifacts overlap the expected manifest")
    destinations = [
        _lexical_destination(run_root, relative) for relative, _ in manifest
    ]
    obsolete_destinations = [
        (relative, _lexical_destination(run_root, relative))
        for relative in sorted(obsolete)
    ]
    obsolete_directory_destinations = [
        (relative, _lexical_owned_directory(run_root, relative))
        for relative in sorted(
            set(obsolete_directories or ()),
            key=lambda value: (-len(PurePosixPath(value).parts), value),
        )
    ]
    resolved_keys = [str(destination.resolve(strict=False)) for destination in destinations]
    if len(resolved_keys) != len(set(resolved_keys)):
        raise ValueError("publication destinations must be pairwise distinct")

    with tempfile.TemporaryDirectory(prefix=".local-publish-backup-", dir=run_root) as value:
        backup_root = Path(value).resolve()
        backups: list[tuple[Path, Path]] = []
        published: list[Path] = []
        removed_directories: list[Path] = []
        try:
            for (relative, source), destination in zip(manifest, destinations):
                _ensure_plain_parents(run_root, destination)
                if destination.exists():
                    backup = backup_root / Path(*PurePosixPath(relative).parts)
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    _replace_file(destination, backup)
                    backups.append((destination, backup))
                # Preserve the source until all post-publication validators
                # succeed; rollback must not destroy the only rendered copy.
                publication_copy = backup_root / '.new-artifacts' / Path(*PurePosixPath(relative).parts)
                publication_copy.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, publication_copy)
                _replace_file(publication_copy, destination)
                published.append(destination)
            for relative, destination in obsolete_destinations:
                if destination.exists():
                    backup = backup_root / Path(*PurePosixPath(relative).parts)
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    _replace_file(destination, backup)
                    backups.append((destination, backup))
            for _, directory in obsolete_directory_destinations:
                directory.rmdir()
                removed_directories.append(directory)
        except BaseException as publication_error:
            rollback_errors: list[BaseException] = []
            for destination in reversed(published):
                try:
                    if _lstat(destination) is not None:
                        destination.unlink()
                except BaseException as error:
                    rollback_errors.append(error)
            for directory in reversed(removed_directories):
                try:
                    directory.mkdir(parents=True, exist_ok=True)
                except BaseException as error:
                    rollback_errors.append(error)
            for destination, backup in reversed(backups):
                try:
                    if _lstat(destination) is not None:
                        destination.unlink()
                    _replace_file(backup, destination)
                except BaseException as error:
                    rollback_errors.append(error)
            if rollback_errors:
                raise RuntimeError(
                    "local publication failed and rollback was incomplete"
                ) from publication_error
            raise
    for _, destination in obsolete_destinations:
        current = destination.parent
        while current != run_root:
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent
    return destinations


@contextmanager
def _preserve_publication_until_validated(
    run_dir: Path,
    relatives: Sequence[str],
    *,
    directories: Sequence[str] = (),
) -> Iterator[None]:
    run_root = _require_lexical_root(run_dir, "run directory")
    unique_relatives = list(dict.fromkeys([*relatives, "local-production-report.json"]))
    destinations = [
        _lexical_destination(run_root, relative) for relative in unique_relatives
    ]
    preserved_directories = [
        _lexical_owned_directory(run_root, relative)
        for relative in sorted(
            set(directories),
            key=lambda value: (len(PurePosixPath(value).parts), value),
        )
    ]
    with tempfile.TemporaryDirectory(prefix=".local-validation-backup-", dir=run_root) as value:
        backup_root = Path(value).resolve()
        existed: dict[str, bool] = {}
        for relative, destination in zip(unique_relatives, destinations):
            exists = destination.is_file()
            existed[relative] = exists
            if exists:
                backup = backup_root / Path(*PurePosixPath(relative).parts)
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, backup)
        try:
            yield
        except BaseException as production_error:
            rollback_errors: list[BaseException] = []
            for relative, destination in reversed(list(zip(unique_relatives, destinations))):
                try:
                    metadata = _lstat(destination)
                    if metadata is not None:
                        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                            raise ValueError(
                                f"published destination changed type during rollback: {destination}"
                            )
                        destination.unlink()
                    if existed[relative]:
                        backup = backup_root / Path(*PurePosixPath(relative).parts)
                        _ensure_plain_parents(run_root, destination)
                        _replace_file(backup, destination)
                except BaseException as error:
                    rollback_errors.append(error)
            for directory in preserved_directories:
                try:
                    directory.mkdir(parents=True, exist_ok=True)
                except BaseException as error:
                    rollback_errors.append(error)
            if rollback_errors:
                raise RuntimeError(
                    "local validation failed and publication rollback was incomplete"
                ) from production_error
            raise


def write_local_production_report(
    context: LocalProductionContext,
    render_report: SequenceRenderReport,
    qa_report: QaReport,
    variants: SequenceVariantManifest | None = None,
    *,
    reference_files: Sequence[str] = (),
) -> LocalProductionReport:
    is_final = render_report.quality == "final"
    report = LocalProductionReport(
        quality=render_report.quality,
        script_sha256=script_sha256(context.run_dir / "script.json"),
        production_plan_sha256=script_sha256(
            context.run_dir / "production-plan.json"
        ),
        local_sequence_plan_sha256=script_sha256(
            context.run_dir / "local-sequence-plan.json"
        ),
        online_plan_sha256=script_sha256(context.run_dir / "online-plan.json"),
        draft_qa_file="videoFiles/sequences/draft/qa-report.json",
        final_qa_file="qa-report.json" if is_final else None,
        final_file=render_report.final_file if is_final else None,
        final_original_file=render_report.final_original_file if is_final else None,
        reference_files=list(reference_files) if is_final else [],
        variant_files=(
            [item.final_file for item in variants.variants]
            if is_final and variants is not None
            else []
        ),
    )
    atomic_write(
        context.run_dir / "local-production-report.json",
        report.model_dump_json(indent=2) + "\n",
    )
    return report


def _localize_stage(context, report, *, quality, root, settings, fps=None, width=None, height=None) -> None:
    """Build narrated language outputs with optional subtitles from the stage's visual master."""
    from .localize import delivery_mode, language_outputs, localize_outputs, require_localization
    from .media import probe_media
    languages = language_outputs(settings)
    if not languages:
        return
    if fps is None:
        # Final quality renders at the plan's canonical resolution and frame rate.
        fps, width, height = context.local.defaults.fps, context.local.defaults.width, context.local.defaults.height
    video_only = Path(root) / report.final_original_file
    info = probe_media(video_only)
    frame_count = info.frame_count if info.frame_count is not None else round(info.duration_seconds * fps)
    scene_audio = {scene.scene_id: scene.audio_file for scene in context.script.scenes if scene.audio_file}
    localize_outputs(context.run_dir, quality=quality, artifact_root=root, video_only=video_only, scene_audio=scene_audio,
                     settings=settings, output_fps=fps, width=width, height=height, frame_count=frame_count)
    require_localization(context.run_dir, root, quality, languages, delivery_mode(settings))


def _raise_validation(label: str, issues: Sequence[object]) -> None:
    if issues:
        codes = ", ".join(str(getattr(issue, "code", "unknown")) for issue in issues)
        raise ValueError(f"{label} validation failed: {codes}")


def produce_local(
    run_dir: Path,
    *,
    quality: Literal["draft", "final"] = "draft",
    force: bool = False,
    settings: HarnessSettings | None = None,
    compile_prompts: bool = True,
    create_references: bool = True,
    variant_mode: VariantMode = "four",
    performance: PerformanceRecorder | None = None,
) -> LocalProductionReport:
    if quality not in {"draft", "final"}:
        raise ValueError("quality must be draft or final")
    settings = settings or resolve_run_settings(run_dir)
    if settings.pipeline.output_mode == "prompts_only":
        raise ValueError("prompts_only does not render local video; compile prompts directly")
    if settings.pipeline.output_mode == "video_only":
        compile_prompts = False
        create_references = False
    if settings.pipeline.variant_mode == "balanced_only" and variant_mode == "four":
        variant_mode = "balanced_only"
    if variant_mode not in {"four", "balanced_only"}:
        raise ValueError(f"unknown variant mode: {variant_mode}")
    from .video_plan_approval import require_current_video_plan_approval
    from .stage_approvals import require_stage_approval
    require_current_video_plan_approval(run_dir)
    require_stage_approval(run_dir, quality)
    context = load_local_production_context(run_dir)
    if quality == "draft":
        if compile_prompts:
            write_compiled_artifacts(
                context.run_dir,
                context.production,
                context.script,
                local_plan=context.local,
                online_plan=context.online,
            )
        with (
            performance.phase("base_output", output_id="draft")
            if performance is not None
            else nullcontext()
        ):
            draft = render_sequence_quality(
                context.run_dir,
                quality="draft",
                force=force,
                settings=settings,
                performance=performance,
            )
            draft_qa = run_sequence_qa(
                context.run_dir,
                context.production,
                context.local,
                context.online,
                draft,
                quality="draft",
                settings=settings,
                performance=performance,
            )
            require_passed(draft_qa, "draft QA")
            from .creative_gates import require_text_render
            require_text_render(context.run_dir, context.run_dir, "draft")
            _localize_stage(context, draft, quality="draft", root=context.run_dir, settings=settings,
                            fps=settings.render.draft_fps, width=settings.render.draft_width, height=settings.render.draft_height)
        return write_local_production_report(context, draft, draft_qa)

    with final_staging_directory(context.run_dir) as staging:
        if compile_prompts:
            from .creative_gates import stage_creative_reviews
            stage_creative_reviews(context.run_dir, staging)
            write_compiled_artifacts(
                staging,
                context.production,
                context.script,
                local_plan=context.local,
                online_plan=context.online,
            )
            # These are compiler inputs, not newly published artifacts.
            for name in ("story-chain.json", "continuity-plan.json", "run-settings.json"):
                (staging / name).unlink(missing_ok=True)
        if not force:
            _seed_approved_draft(context.run_dir, staging)
        _stage_review_artifacts(
            context.run_dir,
            staging,
            video_plan_already_staged=compile_prompts,
        )
        with (
            performance.phase("base_output", output_id="draft")
            if performance is not None
            else nullcontext()
        ):
            draft = render_sequence_quality(
                context.run_dir,
                quality="draft",
                output_root=staging,
                force=force,
                settings=settings,
                performance=performance,
            )
            draft_qa = run_sequence_qa(
                context.run_dir,
                context.production,
                context.local,
                context.online,
                draft,
                quality="draft",
                settings=settings,
                performance=performance,
            )
            require_passed(draft_qa, "draft QA")
            from .creative_gates import require_text_render
            require_text_render(context.run_dir, staging, "draft")
            _localize_stage(context, draft, quality="draft", root=staging, settings=settings,
                            fps=settings.render.draft_fps, width=settings.render.draft_width, height=settings.render.draft_height)
        with (
            performance.phase("base_output", output_id="final")
            if performance is not None
            else nullcontext()
        ):
            final = render_sequence_quality(
                context.run_dir,
                quality="final",
                output_root=staging,
                force=force,
                settings=settings,
                performance=performance,
            )
            references = (
                create_online_references(
                    context.run_dir,
                    context.online,
                    final,
                    output_root=staging,
                )
                if create_references
                else []
            )
            final_qa = run_sequence_qa(
                context.run_dir,
                context.production,
                context.local,
                context.online,
                final,
                quality="final",
                settings=settings,
                performance=performance,
            )
            require_passed(final_qa, "final QA")
            _localize_stage(context, final, quality="final", root=staging, settings=settings)
        variants = assemble_sequence_variants(
            context.run_dir,
            context.production,
            context.local,
            context.online,
            context.variant,
            final,
            output_root=staging,
            create_references=create_references,
            variant_mode=variant_mode,
            settings=settings,
            performance=performance,
        )
        expected_relatives = _derive_owned_public_manifest(
            context,
            draft_qa,
            final_qa,
            compile_prompts=compile_prompts,
            create_references=create_references,
            variant_mode=variant_mode,
            settings=settings,
        )
        obsolete_relatives = (
            _current_owned_public_files(context.run_dir) - expected_relatives
        )
        obsolete_directories = _current_obsolete_owned_directories(
            context.run_dir, context
        )
        staged_relatives = [relative for relative, _ in _staged_manifest(staging)]
        with _preserve_publication_until_validated(
            context.run_dir,
            [*staged_relatives, *obsolete_relatives],
            directories=obsolete_directories,
        ):
            publish_staged_outputs(
                context.run_dir,
                staging,
                expected_relatives=expected_relatives,
                obsolete_relatives=obsolete_relatives,
                obsolete_directories=obsolete_directories,
            )
            _raise_validation(
                "final artifact",
                validate_run(
                    context.run_dir,
                    require_local_report=False,
                    require_pipeline_report=False,
                    settings=settings,
                ),
            )
            report = write_local_production_report(
                context,
                final,
                final_qa,
                variants,
                reference_files=references,
            )
            _raise_validation(
                "production report",
                validate_run(
                    context.run_dir,
                    require_pipeline_report=False,
                    settings=settings,
                ),
            )
            return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Produce and validate a schema-v2 local sequence video run."
    )
    parser.add_argument("run_directory", type=Path, help="schema-v2 run directory")
    parser.add_argument(
        "--quality",
        choices=("draft", "final"),
        default="draft",
        help="default: draft; stop after draft QA for review, or explicitly publish final artifacts",
    )
    parser.add_argument("--force", action="store_true", help="rerender cached sequences")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = produce_local(
            args.run_directory,
            quality=args.quality,
            force=args.force,
        )
    except (OSError, ValueError, RuntimeError) as error:
        print(f"local production failed: {error}")
        return 1
    print(
        f"local production complete: quality={report.quality} "
        f"report={args.run_directory / 'local-production-report.json'}"
    )
    if report.quality == "draft":
        print(f"draft ready for review: {args.run_directory.resolve() / 'final-draft.mp4'}")
        print("Show the draft to the user first; use --quality final after feedback.")
    return 0
