"""Preview → draft → final: each stage is unlocked only by a hash-bound human approval."""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from pydantic import Field
from .creative_gates import text_policy_of
from .models import StrictModel
from .storage import atomic_write
from .video_plan_approval import APPROVAL_FILENAME

PREVIEW_APPROVAL = 'preview-approval.json'
DRAFT_APPROVAL = 'draft-approval.json'
PREVIEW_REPORT = 'preview-report.json'
DRAFT_QA = 'videoFiles/sequences/draft/qa-report.json'
_HEX = r'^[0-9a-f]{64}$'


class PreviewApproval(StrictModel):
    schema_version: Literal[1] = 1
    approved_at: datetime
    video_plan_approval_sha256: str = Field(pattern=_HEX)
    preview_report_sha256: str = Field(pattern=_HEX)
    renderer_versions: dict[str, str]


class DraftApproval(StrictModel):
    schema_version: Literal[1] = 1
    approved_at: datetime
    preview_approval_sha256: str = Field(pattern=_HEX)
    final_draft_sha256: str = Field(pattern=_HEX)
    draft_qa_sha256: str = Field(pattern=_HEX)


def _sha(path: Path, stage: str) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError as error:
        raise ValueError(f'{stage} 승인에 필요한 파일이 없습니다: {path.name}') from error


def current_renderer_versions(run: Path) -> dict[str, str]:
    from .sequence_plans import load_local_sequence_plan
    from .sequence_render import backend_for_plan
    local = load_local_sequence_plan(run / 'local-sequence-plan.json')
    backend = backend_for_plan(local, run_dir=run)
    versions: dict[str, str] = {}
    for sequence in local.sequences:
        chosen = backend.backend_for_sequence(sequence.sequence_id) if hasattr(backend, 'backend_for_sequence') else backend
        versions[sequence.sequence_id] = getattr(chosen, 'version', type(chosen).__name__)
    return versions


def _preview_state(run: Path) -> dict:
    report_path = run / PREVIEW_REPORT
    report = json.loads(report_path.read_text(encoding='utf-8')) if report_path.is_file() else {}
    return dict(video_plan_approval_sha256=_sha(run / APPROVAL_FILENAME, '프리뷰'),
                preview_report_sha256=_sha(report_path, '프리뷰'),
                renderer_versions=report.get('renderer_versions', {}))


def _require_gate_passed(run: Path, name: str, stage: str) -> None:
    path = run / f'{name}.json'
    status = json.loads(path.read_text(encoding='utf-8')).get('status') if path.is_file() else None
    if status not in ('passed', 'skipped'):
        raise ValueError(f'{stage} 승인 불가: {name}.json이 통과 상태가 아닙니다 ({status}).')


def _require_current_plan(run: Path, report: dict, stage: str, source: str) -> None:
    current = _sha(run / 'local-sequence-plan.json', stage)
    if report.get('local_sequence_plan_sha256') != current:
        raise ValueError(f'{stage} 승인 불가: {source}가 현재 계획과 다릅니다. 다시 렌더한 뒤 제시·승인하세요.')


def approve_preview(run_dir: Path) -> PreviewApproval:
    run = Path(run_dir).resolve()
    state = _preview_state(run)
    report = json.loads((run / PREVIEW_REPORT).read_text(encoding='utf-8'))
    _require_current_plan(run, report, '프리뷰', PREVIEW_REPORT)
    _require_gate_passed(run, 'text-preview-gate', '프리뷰')
    if state['renderer_versions'] != current_renderer_versions(run):
        raise ValueError('프리뷰 이후 렌더러 소스가 바뀌었습니다. preview를 다시 실행하세요.')
    record = PreviewApproval(approved_at=datetime.now(timezone.utc), **state)
    atomic_write(run / PREVIEW_APPROVAL, record.model_dump_json(indent=2) + '\n')
    return record


def require_current_preview_approval(run_dir: Path) -> None:
    run = Path(run_dir).resolve()
    path = run / PREVIEW_APPROVAL
    if not path.is_file():
        raise ValueError("프리뷰 승인이 없습니다. preview-ui에서 프리뷰 승인 버튼을 누르거나, 사용자가 '프리뷰승인'이라고 답한 뒤 approve-preview를 실행하세요.")
    record = PreviewApproval.model_validate_json(path.read_text(encoding='utf-8'))
    state = _preview_state(run)
    if record.renderer_versions != current_renderer_versions(run):
        raise ValueError('프리뷰 승인 이후 렌더러 소스가 바뀌었습니다. preview와 프리뷰 승인을 다시 진행하세요.')
    stale = [k for k in ('video_plan_approval_sha256', 'preview_report_sha256') if getattr(record, k) != state[k]]
    if stale:
        raise ValueError(f'프리뷰 승인이 오래되었습니다({", ".join(stale)}). preview를 다시 실행하고 다시 제시·승인하세요.')


def _draft_state(run: Path) -> dict:
    return dict(preview_approval_sha256=_sha(run / PREVIEW_APPROVAL, '초본'),
                final_draft_sha256=_sha(run / 'final-draft.mp4', '초본'),
                draft_qa_sha256=_sha(run / DRAFT_QA, '초본'))


def approve_draft(run_dir: Path) -> DraftApproval:
    run = Path(run_dir).resolve()
    require_current_preview_approval(run)
    qa_path = run / DRAFT_QA
    qa = json.loads(qa_path.read_text(encoding='utf-8')) if qa_path.is_file() else {}
    if qa.get('status') != 'passed':
        raise ValueError(f"초본 승인 불가: 초본 QA가 통과 상태가 아닙니다 ({qa.get('status')}).")
    _require_current_plan(run, qa, '초본', DRAFT_QA)
    _require_gate_passed(run, 'text-draft-gate', '초본')
    record = DraftApproval(approved_at=datetime.now(timezone.utc), **_draft_state(run))
    atomic_write(run / DRAFT_APPROVAL, record.model_dump_json(indent=2) + '\n')
    return record


def require_current_draft_approval(run_dir: Path) -> None:
    run = Path(run_dir).resolve()
    require_current_preview_approval(run)
    path = run / DRAFT_APPROVAL
    if not path.is_file():
        raise ValueError("초본 승인이 없습니다. final-draft.mp4를 제시하고 사용자가 정확히 '초본승인'이라고 답한 뒤 approve-draft를 실행하세요.")
    record = DraftApproval.model_validate_json(path.read_text(encoding='utf-8'))
    state = _draft_state(run)
    stale = [k for k in state if getattr(record, k) != state[k]]
    if stale:
        raise ValueError(f'초본 승인이 오래되었습니다({", ".join(stale)}). 초본을 다시 제시하고 승인받으세요.')


def require_stage_approval(run_dir: Path, quality: Literal['draft', 'final']) -> None:
    run = Path(run_dir)
    if text_policy_of(run) == 'legacy':
        return
    if quality == 'draft':
        require_current_preview_approval(run)
    else:
        require_current_draft_approval(run)


def _main(stage: str, argv: Sequence[str] | None) -> int:
    phrase, action, filename = {
        'preview': ('프리뷰승인', approve_preview, PREVIEW_APPROVAL),
        'draft': ('초본승인', approve_draft, DRAFT_APPROVAL),
    }[stage]
    parser = argparse.ArgumentParser(description=f"사용자가 정확히 '{phrase}'이라고 답한 현재 {stage} 결과를 해시로 묶어 승인합니다.")
    parser.add_argument('run_directory', type=Path)
    args = parser.parse_args(argv)
    try:
        action(args.run_directory)
    except (OSError, ValueError) as error:
        print(f'{phrase} 기록 실패: {error}', file=sys.stderr)
        return 1
    print(f'{phrase} 기록 완료: {args.run_directory / filename}')
    return 0


def preview_main(argv: Sequence[str] | None = None) -> int:
    return _main('preview', argv)


def draft_main(argv: Sequence[str] | None = None) -> int:
    return _main('draft', argv)
