"""Representative-frame preview: render, contact sheet, text gate — before any full draft."""
from __future__ import annotations
import argparse
import json
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal
from .models import StrictModel
from .production import script_sha256
from .sequence_models import LocalSequence, LocalSequencePlan
from .sequence_plans import load_local_sequence_plan
from .sequence_render import backend_for_plan, build_sequence_job, _output_boundary, load_simulation
from .pacing_presets import render_pacing_values
from .settings import HarnessSettings, resolve_run_settings
from .storage import RunStore, atomic_write
from .video_plan_approval import prepare_video_plan

PREVIEW_DIR = Path('previews') / 'preview'
REPORT_NAME = 'preview-report.json'
SHEET_COLUMNS = 4


class PreviewSequence(StrictModel):
    sequence_id: str
    sample_frames: list[int]
    roles: dict[str, str]
    frames: list[str]
    state_samples: list[dict[str, object]]


class PreviewReport(StrictModel):
    schema_version: Literal[1] = 1
    width: int
    height: int
    fps: int
    local_sequence_plan_sha256: str
    renderer_versions: dict[str, str]
    sequences: list[PreviewSequence]
    contact_sheet_file: str


def transition_boundaries(local: LocalSequencePlan, continuity: Mapping[str, object]) -> dict[str, list[int]]:
    beats = {b.beat_id: (s.sequence_id, b) for s in local.sequences for b in s.timeline}
    result: dict[str, list[int]] = {s.sequence_id: [] for s in local.sequences}
    for t in continuity.get('transitions', []):
        if t.get('mode') == 'cut' or t.get('to_beat') not in beats:
            continue
        sid, beat = beats[t['to_beat']]
        result[sid].append(beat.start_frame)
    return {k: sorted(set(v)) for k, v in result.items()}


def representative_output_frames(sequence: LocalSequence, boundaries: Sequence[int], *, canonical_fps: int, output_fps: int, half_window_seconds: float = 0.5) -> list[int]:
    last = _output_boundary(sequence.duration_frames, output_fps=output_fps, canonical_fps=canonical_fps) - 1
    window = round(canonical_fps * half_window_seconds)
    wanted = [(b.start_frame + b.end_frame) // 2 for b in sequence.timeline]
    for beat in sequence.timeline:
        for progress in beat.controller_options.get('preview_sample_progress', []):
            if not isinstance(progress, (int, float)) or not 0 <= progress <= 1:
                raise ValueError('preview_sample_progress must be between 0 and 1')
            wanted.append(round(beat.start_frame + (beat.end_frame - beat.start_frame - 1) * progress))
    for boundary in boundaries:
        wanted.extend((boundary - window, boundary, boundary + window))
    frames = {min(max(_output_boundary(max(0, f), output_fps=output_fps, canonical_fps=canonical_fps), 0), last) for f in wanted}
    return sorted(frames)


def frame_roles(sequence: LocalSequence, boundaries: Sequence[int], *, canonical_fps: int, output_fps: int) -> dict[str, str]:
    roles: dict[str, str] = {}
    for b in sequence.timeline:
        roles[str(_output_boundary((b.start_frame + b.end_frame) // 2, output_fps=output_fps, canonical_fps=canonical_fps))] = f'{b.beat_id} centre'
    starts = {b.start_frame: b.beat_id for b in sequence.timeline}
    for boundary in boundaries:
        roles.setdefault(str(_output_boundary(boundary, output_fps=output_fps, canonical_fps=canonical_fps)), f'boundary into {starts.get(boundary, "?")}')
    return roles


def _contact_sheet(frames: Sequence[Path], destination: Path) -> None:
    staging = destination.parent / (destination.stem + '-tiles')
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    for index, frame in enumerate(frames):
        shutil.copyfile(frame, staging / f'tile-{index:04d}.png')
    rows = max(1, -(-len(frames) // SHEET_COLUMNS))
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-framerate', '1', '-i', str(staging / 'tile-%04d.png'),
                    '-vf', f'tile={SHEET_COLUMNS}x{rows}:padding=4:color=black', '-frames:v', '1', str(destination)], check=True)
    shutil.rmtree(staging, ignore_errors=True)


def _backend_version_for(active, sequence: LocalSequence) -> str:
    chosen = active.backend_for_sequence(sequence.sequence_id) if hasattr(active, 'backend_for_sequence') else active
    return getattr(chosen, 'version', type(chosen).__name__)


def render_preview(run_dir: Path, *, settings: HarnessSettings | None = None, backend=None) -> PreviewReport:
    run = Path(run_dir).resolve()
    prepare_video_plan(run)
    settings = settings or resolve_run_settings(run)
    store = RunStore.open(run)
    local = load_local_sequence_plan(run / 'local-sequence-plan.json')
    continuity = json.loads((run / 'continuity-plan.json').read_text(encoding='utf-8'))
    simulation = load_simulation(run, store.read_script())
    active = backend or backend_for_plan(local, run_dir=run, settings=settings)
    active.check_dependencies()
    width, height, fps = settings.render.draft_width, settings.render.draft_height, settings.render.draft_fps
    boundaries = transition_boundaries(local, continuity)
    out_root = run / PREVIEW_DIR
    shutil.rmtree(out_root, ignore_errors=True)
    out_root.mkdir(parents=True)
    sequences: list[PreviewSequence] = []
    versions: dict[str, str] = {}
    all_frames: list[Path] = []
    for sequence in local.sequences:
        cache_dir = run / '.render-cache' / 'sequences' / 'preview' / sequence.sequence_id
        shutil.rmtree(cache_dir, ignore_errors=True)
        sample = representative_output_frames(sequence, boundaries[sequence.sequence_id], canonical_fps=local.defaults.fps, output_fps=fps)
        job = build_sequence_job(sequence, width=width, height=height, output_fps=fps, canonical_fps=local.defaults.fps,
                                 cache_dir=cache_dir, simulation=simulation, sample_frames=sample,
                                 camera_transition_seconds=getattr(getattr(settings, "local_video", None), "camera_transition_seconds", None),
                                 pacing=render_pacing_values(settings))
        report = json.loads(Path(active.render_frames(job, cache_dir)).read_text(encoding='utf-8'))
        seq_dir = out_root / sequence.sequence_id
        seq_dir.mkdir(parents=True)
        copied: list[Path] = []
        for source in report['frames']:
            target = seq_dir / Path(source).name
            shutil.copyfile(source, target)
            copied.append(target)
            all_frames.append(target)
        _contact_sheet(copied, out_root / f'{sequence.sequence_id}-contact-sheet.png')
        current_version = _backend_version_for(active, sequence)
        rendered_version = report.get('renderer_version', current_version)
        if rendered_version != current_version:
            raise ValueError('Render source changed before preview publication; regenerate the preview')
        versions[sequence.sequence_id] = rendered_version
        sequences.append(PreviewSequence(sequence_id=sequence.sequence_id, sample_frames=sample,
            roles=frame_roles(sequence, boundaries[sequence.sequence_id], canonical_fps=local.defaults.fps, output_fps=fps),
            frames=[str(p.relative_to(run)) for p in copied], state_samples=report['state_samples']))
    sheet = out_root / 'contact-sheet.png'
    _contact_sheet(all_frames, sheet)
    result = PreviewReport(width=width, height=height, fps=fps, local_sequence_plan_sha256=script_sha256(run / 'local-sequence-plan.json'),
                           renderer_versions=versions, sequences=sequences, contact_sheet_file=str(sheet.relative_to(run)))
    atomic_write(run / REPORT_NAME, result.model_dump_json(indent=2) + '\n')
    from .creative_gates import require_text_render
    require_text_render(run, run, 'preview')
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='대표 프레임(비트 중앙, 전환 전·중·후)만 렌더해 접촉 시트와 text 게이트로 검토합니다. 초본 전에 실행합니다.')
    parser.add_argument('run_directory', type=Path)
    parser.add_argument('--no-ui', action='store_true', help='렌더 후 검토 웹을 열지 않습니다(자동 검사용).')
    parser.add_argument('--port', type=int, default=0, help='검토 웹 포트(기본: 사용 가능한 포트).')
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    from .preview_ui import update_regeneration
    update_regeneration(args.run_directory, 'rendering', '수정된 장면의 프리뷰를 렌더링하고 있습니다.')
    try:
        report = render_preview(args.run_directory)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        update_regeneration(args.run_directory, 'failed', str(error))
        print(f'프리뷰 실패: {error}', file=sys.stderr)
        return 1
    update_regeneration(args.run_directory, 'completed', '새 프리뷰가 준비되었습니다.')
    print(f'프리뷰 완료: {args.run_directory / report.contact_sheet_file}')
    if not args.no_ui:
        from .preview_ui import serve_review
        return serve_review(args.run_directory, port=args.port)
    print("preview-ui로 대본·영상대본·이미지를 함께 검토하고 수정 의견 또는 프리뷰 승인을 받으세요.")
    return 0
