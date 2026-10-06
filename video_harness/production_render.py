from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from pydantic import Field

from .media import (
    EncoderSpec,
    OutputSpec,
    capture_preview_frames,
    capture_previews,
    concat_videos,
    mux_audio,
    probe_media,
    validate_media,
)
from .models import StrictModel
from .production import (
    load_production_plan,
    script_sha256,
    validate_plan_against_script,
)
from .production_models import CompositeShot, GeneratedShot, ProductionPlan, ProductionShot
from .render import parse_scene_ids
from .shot_backends import (
    CompositeBackend,
    GeneratedClipBackend,
    ShotBackendRegistry,
    ShotContext,
    ShotRenderRecord,
    ShotReviewRecord,
    SimulationBackend,
    StillMotionBackend,
)
from .storage import RunStore, atomic_write, scene_filename
from .settings import HarnessSettings
from .variant_render import assemble_variants
from .variants import (
    VariantPlan,
    all_variant_shots,
    load_variant_plan,
    validate_variant_plan,
)


class ProductionSceneResult(StrictModel):
    scene_id: int
    original_video_file: str
    video_file: str
    preview_files: list[str]


class ProductionRenderReport(StrictModel):
    status: Literal["shots_ready", "awaiting_review", "complete"]
    quality: Literal["draft", "final"]
    production_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rendered_shot_ids: list[str]
    reused_shot_ids: list[str]
    review_required_shot_ids: list[str]
    scenes: list[ProductionSceneResult]
    final_file: str | None = None
    final_original_file: str | None = None
    variant_files: list[str] = Field(default_factory=list)


def _default_registry() -> ShotBackendRegistry:
    registry = ShotBackendRegistry()
    registry.register("generated", GeneratedClipBackend())
    registry.register("simulation", SimulationBackend())
    registry.register("composite", CompositeBackend())
    registry.register("still_motion", StillMotionBackend())
    return registry


def _requires_review(shot: ProductionShot) -> bool:
    return isinstance(shot, GeneratedShot) or (
        isinstance(shot, CompositeShot) and shot.base.mode == "generated"
    )


def _find_shot(
    plan: ProductionPlan,
    shot_id: str,
    variant_plan: VariantPlan | None = None,
) -> ProductionShot:
    for scene in plan.scenes:
        for shot in scene.shots:
            if shot.shot_id == shot_id:
                return shot
    if variant_plan is not None:
        for shot in all_variant_shots(variant_plan):
            if shot.shot_id == shot_id:
                return shot
    raise ValueError(f"production-plan.json에 없는 샷입니다: {shot_id}")


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
        raise ValueError(
            "; ".join(f"{issue.code}: {issue.message}" for issue in issues)
        )
    return variant_plan


def approve_shot(
    run_dir: Path,
    shot_id: str,
    invariant_results: dict[str, bool],
    note: str = "",
) -> ShotReviewRecord:
    run_dir = run_dir.resolve()
    plan = load_production_plan(run_dir / "production-plan.json")
    variant_plan = _load_valid_variant_plan(run_dir, plan)
    shot = _find_shot(plan, shot_id, variant_plan)
    if not _requires_review(shot):
        raise ValueError(f"샷 {shot_id}은 생성 기반이 아니므로 사람 승인이 필요하지 않습니다.")
    expected = set(shot.invariants)
    supplied = set(invariant_results)
    if supplied != expected or not all(invariant_results.values()):
        missing = sorted(expected - supplied)
        failed = sorted(name for name, value in invariant_results.items() if not value)
        raise ValueError(
            f"샷 {shot_id} 불변 조건 검수가 완전하지 않습니다. "
            f"누락={missing}, 실패={failed}"
        )
    context = ShotContext(
        run_dir=run_dir,
        plan=plan,
        backend_versions={},
    )
    output = context.output_path(shot)
    if not output.is_file():
        raise FileNotFoundError(f"승인할 샷 영상이 없습니다: {output}")
    review = ShotReviewRecord(
        shot_id=shot_id,
        output_sha256=context.file_sha256(output),
        status="approved",
        invariant_results=invariant_results,
        note=note,
    )
    path = context.review_path(shot)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, review.model_dump_json(indent=2) + "\n")
    return review


def reject_shot(run_dir: Path, shot_id: str, note: str) -> ShotReviewRecord:
    if not note.strip():
        raise ValueError("거절 사유를 적어야 합니다.")
    run_dir = run_dir.resolve()
    plan = load_production_plan(run_dir / "production-plan.json")
    variant_plan = _load_valid_variant_plan(run_dir, plan)
    shot = _find_shot(plan, shot_id, variant_plan)
    if not _requires_review(shot):
        raise ValueError(f"샷 {shot_id}은 생성 기반이 아닙니다.")
    context = ShotContext(run_dir=run_dir, plan=plan, backend_versions={})
    output = context.output_path(shot)
    if not output.is_file():
        raise FileNotFoundError(f"거절할 샷 영상이 없습니다: {output}")
    review = ShotReviewRecord(
        shot_id=shot_id,
        output_sha256=context.file_sha256(output),
        status="rejected",
        invariant_results={name: False for name in shot.invariants},
        note=note,
    )
    path = context.review_path(shot)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, review.model_dump_json(indent=2) + "\n")
    return review


def _load_record(path: Path) -> ShotRenderRecord | None:
    if not path.is_file():
        return None
    try:
        return ShotRenderRecord.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_review(path: Path) -> ShotReviewRecord | None:
    if not path.is_file():
        return None
    try:
        return ShotReviewRecord.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _generation_inbox(shot: ProductionShot) -> str | None:
    if isinstance(shot, GeneratedShot):
        return shot.generation.inbox_file
    if (
        isinstance(shot, CompositeShot)
        and shot.base.mode == "generated"
        and shot.base.generation is not None
    ):
        return shot.base.generation.inbox_file
    return None


def _preflight_generated_inputs(
    shots: Sequence[ProductionShot],
    context: ShotContext,
) -> None:
    for shot in shots:
        relative = _generation_inbox(shot)
        if relative is None:
            continue
        path = context.safe_path(relative)
        if not path.is_file() or path.stat().st_size == 0:
            raise FileNotFoundError(f"외부 생성 클립이 없습니다: {path}")
        info = probe_media(path)
        if info.duration_seconds + 1 / context.plan.defaults.fps < shot.duration_seconds:
            raise ValueError(
                f"샷 {shot.shot_id} 원본이 짧습니다: "
                f"{info.duration_seconds:.3f}초 / {shot.duration_seconds:.3f}초"
            )


def _scene_directories(run_dir: Path, quality: str) -> tuple[Path, Path, Path]:
    base = run_dir / "videoFiles"
    if quality == "draft":
        base /= "draft"
    return base, base / "original", base / "previews"


def _write_report(run_dir: Path, report: ProductionRenderReport) -> None:
    atomic_write(
        run_dir / "production-render-report.json",
        report.model_dump_json(indent=2) + "\n",
    )


def render_production(
    run_dir: Path,
    quality: Literal["draft", "final"] = "draft",
    scene_ids: set[int] | None = None,
    force: bool = False,
    shots_only: bool = False,
    registry: ShotBackendRegistry | None = None,
    settings: HarnessSettings | None = None,
) -> ProductionRenderReport:
    from .creative_gates import require_legacy_render_gate
    require_legacy_render_gate(run_dir, quality)

    run_dir = run_dir.resolve()
    settings = settings or HarnessSettings()
    encoder = EncoderSpec(
        preset=settings.render.x264_preset,
        crf=settings.render.x264_crf,
    )
    store = RunStore.open(run_dir)
    store.ensure_production_directories()
    script = store.read_script()
    plan_path = run_dir / "production-plan.json"
    plan = load_production_plan(plan_path)
    plan_issues = validate_plan_against_script(plan, script, run_dir / "script.json", run_dir)
    if plan_issues:
        raise ValueError(
            "; ".join(f"{issue.code}: {issue.message}" for issue in plan_issues)
        )
    variant_plan = _load_valid_variant_plan(run_dir, plan)

    known_ids = {scene.scene_id for scene in plan.scenes}
    selected_ids = scene_ids if scene_ids is not None else known_ids
    unknown = selected_ids - known_ids
    if unknown:
        raise ValueError(f"production-plan.json에 없는 씬 번호입니다: {sorted(unknown)}")
    selected_scenes = [scene for scene in plan.scenes if scene.scene_id in selected_ids]
    selected_shots = [shot for scene in selected_scenes for shot in scene.shots]
    if variant_plan is not None:
        selected_shots.extend(
            item.shot
            for item in variant_plan.alternate_shots
            if item.scene_id in selected_ids
        )

    script_by_id = {scene.scene_id: scene for scene in script.scenes}
    for scene in selected_scenes:
        script_scene = script_by_id[scene.scene_id]
        if not script_scene.audio_file:
            raise ValueError(f"씬 {scene.scene_id} audio_file이 없습니다.")
        audio = store.path(script_scene.audio_file)
        if not audio.is_file() or audio.stat().st_size == 0:
            raise FileNotFoundError(audio)

    active_registry = registry or _default_registry()
    backend_versions = {
        mode: backend.version for mode, backend in active_registry.backends.items()
    }
    context = ShotContext(
        run_dir=run_dir,
        plan=plan,
        backend_versions=backend_versions,
        encoder=encoder,
    )
    _preflight_generated_inputs(selected_shots, context)

    rendered_ids: list[str] = []
    reused_ids: list[str] = []
    for shot in selected_shots:
        record = _load_record(context.record_path(shot))
        if not force and record is not None and context.can_reuse(shot, record):
            reused_ids.append(shot.shot_id)
        else:
            active_registry.get(shot.render_mode).render(shot, context)
            rendered_ids.append(shot.shot_id)
        capture_previews(
            context.output_path(shot),
            context.safe_path(f"shotFiles/previews/{shot.shot_id}"),
            settings.render.preview_interval_seconds,
        )

    review_required: list[str] = []
    for shot in selected_shots:
        if not _requires_review(shot):
            continue
        review = _load_review(context.review_path(shot))
        if review is None or not context.is_review_approved(shot, review):
            review_required.append(shot.shot_id)

    base_report = {
        "quality": quality,
        "production_plan_sha256": script_sha256(plan_path),
        "rendered_shot_ids": rendered_ids,
        "reused_shot_ids": reused_ids,
        "review_required_shot_ids": review_required,
        "scenes": [],
    }
    if shots_only or review_required:
        report = ProductionRenderReport(
            status="awaiting_review" if review_required else "shots_ready",
            **base_report,
        )
        _write_report(run_dir, report)
        if review_required and not shots_only:
            raise ValueError(
                "생성 기반 샷 검수가 필요합니다: " + ", ".join(review_required)
            )
        return report

    base_dir, original_dir, preview_root = _scene_directories(run_dir, quality)
    base_dir.mkdir(parents=True, exist_ok=True)
    original_dir.mkdir(parents=True, exist_ok=True)
    scene_results: list[ProductionSceneResult] = []
    for production_scene in selected_scenes:
        script_scene = script_by_id[production_scene.scene_id]
        original = original_dir / scene_filename(script_scene, ".mp4")
        narrated = base_dir / scene_filename(script_scene, ".mp4")
        spec = OutputSpec(
            width=plan.defaults.width,
            height=plan.defaults.height,
            fps=plan.defaults.fps,
            duration_seconds=production_scene.duration_seconds,
        )
        shot_paths = [context.output_path(shot) for shot in production_scene.shots]
        if force or not original.is_file():
            info = concat_videos(
                shot_paths,
                original,
                expected_duration=production_scene.duration_seconds,
                require_audio=False,
                encoder=encoder,
            )
            validate_media(info, spec, require_audio=False)
        else:
            validate_media(probe_media(original), spec, require_audio=False)
        audio = store.path(script_scene.audio_file)
        if force or not narrated.is_file():
            mux_audio(original, audio, narrated, spec, encoder=encoder)
        else:
            validate_media(probe_media(narrated, require_audio=True), spec, require_audio=True)

        timestamps = [
            index * settings.render.preview_interval_seconds
            for index in range(
                math.ceil(
                    production_scene.duration_seconds
                    / settings.render.preview_interval_seconds
                )
            )
        ]
        preview_dir = preview_root / Path(scene_filename(script_scene, ".mp4")).stem
        previews = capture_preview_frames(
            original,
            preview_dir,
            timestamps,
            [f"{round(value * 1000):04d}ms.png" for value in timestamps],
        )
        scene_results.append(
            ProductionSceneResult(
                scene_id=production_scene.scene_id,
                original_video_file=original.relative_to(run_dir).as_posix(),
                video_file=narrated.relative_to(run_dir).as_posix(),
                preview_files=[path.relative_to(run_dir).as_posix() for path in previews],
            )
        )

    final_file: str | None = None
    final_original_file: str | None = None
    variant_files: list[str] = []
    full_render = scene_ids is None and selected_ids == known_ids
    if full_render:
        all_script_scenes = [script_by_id[scene.scene_id] for scene in plan.scenes]
        narrated_paths = [base_dir / scene_filename(scene, ".mp4") for scene in all_script_scenes]
        original_paths = [original_dir / scene_filename(scene, ".mp4") for scene in all_script_scenes]
        transition = plan.defaults.scene_transition
        transition_seconds = (
            transition.duration_seconds if transition.mode == "dip_to_black" else 0.0
        )
        transition_fade_seconds = (
            transition.fade_seconds if transition.mode == "dip_to_black" else 0.0
        )
        transition_frames = (
            max(4, round(transition_seconds * plan.defaults.fps))
            if transition_seconds > 0
            else 0
        )
        transition_total = (
            max(0, len(plan.scenes) - 1)
            * transition_frames
            / plan.defaults.fps
        )
        original_total_duration = sum(
            probe_media(path).duration_seconds for path in original_paths
        ) + transition_total
        narrated_total_duration = sum(
            probe_media(path, require_audio=True).duration_seconds
            for path in narrated_paths
        ) + transition_total
        final_path = run_dir / ("final-draft.mp4" if quality == "draft" else "final.mp4")
        original_final = run_dir / (
            "video-only-draft.mp4" if quality == "draft" else "video-only.mp4"
        )
        if force or not original_final.is_file():
            concat_videos(
                original_paths,
                original_final,
                expected_duration=original_total_duration,
                require_audio=False,
                transition_seconds=transition_seconds,
                transition_fade_seconds=transition_fade_seconds,
                encoder=encoder,
            )
        if force or not final_path.is_file():
            concat_videos(
                narrated_paths,
                final_path,
                expected_duration=narrated_total_duration,
                require_audio=True,
                transition_seconds=transition_seconds,
                transition_fade_seconds=transition_fade_seconds,
                encoder=encoder,
            )
        final_file = final_path.relative_to(run_dir).as_posix()
        final_original_file = original_final.relative_to(run_dir).as_posix()
        if variant_plan is not None:
            manifest = assemble_variants(
                run_dir=run_dir,
                quality=quality,
                production_plan=plan,
                variant_plan=variant_plan,
                context=context,
                script_by_id=script_by_id,
                balanced_scene_dir=base_dir,
                balanced_original_dir=original_dir,
                balanced_final=final_path,
                balanced_original_final=original_final,
                force=force,
            )
            variant_files = [item.final_file for item in manifest.variants]

    report = ProductionRenderReport(
        status="complete",
        quality=quality,
        production_plan_sha256=script_sha256(plan_path),
        rendered_shot_ids=rendered_ids,
        reused_shot_ids=reused_ids,
        review_required_shot_ids=[],
        scenes=scene_results,
        final_file=final_file,
        final_original_file=final_original_file,
        variant_files=variant_files,
    )
    _write_report(run_dir, report)
    return report


def build_render_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="production-plan.json의 샷을 렌더하고 씬·합본 영상을 만듭니다."
    )
    parser.add_argument("run_directory", type=Path)
    parser.add_argument("--quality", choices=("draft", "final"), default="draft")
    parser.add_argument("--scenes", type=parse_scene_ids)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--shots-only", action="store_true", help="샷과 미리보기만 생성")
    return parser


def render_main(argv: Sequence[str] | None = None) -> int:
    args = build_render_parser().parse_args(argv)
    try:
        report = render_production(
            args.run_directory,
            quality=args.quality,
            scene_ids=args.scenes,
            force=args.force,
            shots_only=args.shots_only,
        )
    except Exception as error:
        print(f"제작 렌더 실패: {error}", file=sys.stderr)
        return 1
    print(report.model_dump_json(indent=2))
    return 0


def _parse_invariant(value: str) -> tuple[str, bool]:
    name, separator, raw = value.rpartition("=")
    if not separator or raw.lower() not in {"true", "false"} or not name.strip():
        raise argparse.ArgumentTypeError("불변 조건은 '문장=true' 또는 '문장=false' 형식입니다.")
    return name.strip(), raw.lower() == "true"


def build_review_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="생성 기반 샷의 불변 조건을 검수해 승인 또는 거절합니다.")
    parser.add_argument("run_directory", type=Path)
    parser.add_argument("shot_id")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--approve", action="store_true")
    action.add_argument("--reject", action="store_true")
    parser.add_argument("--invariant", action="append", type=_parse_invariant, default=[])
    parser.add_argument("--note", default="")
    return parser


def review_main(argv: Sequence[str] | None = None) -> int:
    args = build_review_parser().parse_args(argv)
    try:
        if args.reject:
            record = reject_shot(args.run_directory, args.shot_id, args.note)
        else:
            plan = load_production_plan(args.run_directory / "production-plan.json")
            variant_plan = _load_valid_variant_plan(args.run_directory.resolve(), plan)
            shot = _find_shot(plan, args.shot_id, variant_plan)
            supplied = dict(args.invariant)
            results = supplied or {name: True for name in shot.invariants}
            record = approve_shot(
                args.run_directory,
                args.shot_id,
                results,
                args.note,
            )
    except Exception as error:
        print(f"샷 검수 실패: {error}", file=sys.stderr)
        return 1
    print(record.model_dump_json(indent=2))
    return 0
