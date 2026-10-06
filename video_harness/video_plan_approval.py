from __future__ import annotations

import argparse
import hashlib
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import Field

from .models import StrictModel
from .production_review import render_run_video_plan
from .storage import atomic_write


APPROVAL_FILENAME = "video-plan-approval.json"
_HASH_FILES = {
    "script_sha256": "script.json",
    "story_chain_sha256": "story-chain.json",
    "continuity_plan_sha256": "continuity-plan.json",
    "production_plan_sha256": "production-plan.json",
    "local_sequence_plan_sha256": "local-sequence-plan.json",
    "online_plan_sha256": "online-plan.json",
    "variant_plan_sha256": "variant-plan.json",
    "video_plan_sha256": "video-plan.md",
}


class VideoPlanApproval(StrictModel):
    schema_version: Literal[1] = 1
    source: Literal['human', 'automatic_validation'] = 'human'
    approved_at: datetime
    story_chain_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    continuity_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    script_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    production_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    local_sequence_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    online_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    variant_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    video_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def _sha256(path: Path) -> str:
    try:
        data = path.read_bytes()
    except FileNotFoundError as error:
        raise ValueError(f"영상 생성대본 승인에 필요한 파일이 없습니다: {path.name}") from error
    return hashlib.sha256(data).hexdigest()


def _current_hashes(run_dir: Path) -> dict[str, str]:
    return {
        field: _sha256(run_dir / filename)
        for field, filename in _HASH_FILES.items()
    }


def approve_video_plan(run_dir: Path, *, source: Literal['human', 'automatic_validation'] = 'human') -> VideoPlanApproval:
    from .pipeline import load_pipeline_context

    run_root = run_dir.resolve()
    from .creative_gates import require_creative_plan, require_text_plan
    require_creative_plan(run_root)
    require_text_plan(run_root)
    context = load_pipeline_context(run_root)
    review_path = run_root / "video-plan.md"
    expected = render_run_video_plan(
        run_root, context.production, context.local, context.online, context.script,
    )
    if not review_path.is_file() or review_path.read_text(encoding="utf-8") != expected:
        raise ValueError(
            "video-plan.md가 현재 계획에서 생성한 검토본과 다릅니다. "
            "plan-video를 다시 실행한 뒤 검토하세요."
        )
    record = VideoPlanApproval(
        source=source,
        approved_at=datetime.now(timezone.utc),
        **_current_hashes(run_root),
    )
    atomic_write(
        run_root / APPROVAL_FILENAME,
        record.model_dump_json(indent=2) + "\n",
    )
    return record


def prepare_video_plan(run_dir: Path) -> VideoPlanApproval:
    """Compile and validate the plan without claiming a human approved it.

    Keep an unchanged checkpoint byte-identical so reopening/reviewing does not
    invalidate a later human preview approval.
    """
    from .migration import plan_video
    run = Path(run_dir).resolve()
    plan_video(run)
    if (run / APPROVAL_FILENAME).exists():
        try:
            return require_current_video_plan_approval(run)
        except ValueError:
            pass
    return approve_video_plan(run, source='automatic_validation')


def require_current_video_plan_approval(run_dir: Path) -> VideoPlanApproval:
    run_root = run_dir.resolve()
    approval_path = run_root / APPROVAL_FILENAME
    if not approval_path.is_file():
        raise ValueError(
            "영상 계획 검증 기록이 없습니다. preview를 실행하면 계획 검증과 "
            "대표 프레임 생성 뒤 검토 웹이 열립니다."
        )
    try:
        record = VideoPlanApproval.model_validate_json(
            approval_path.read_text(encoding="utf-8")
        )
    except ValueError as error:
        raise ValueError("video-plan-approval.json 형식이 올바르지 않습니다.") from error
    current = _current_hashes(run_root)
    stale = [
        _HASH_FILES[field]
        for field, digest in current.items()
        if getattr(record, field) != digest
    ]
    if stale:
        raise ValueError(
            "영상 생성대본 승인이 오래되었습니다. 변경된 파일: "
            f"{', '.join(stale)}. preview로 계획 검증과 프리뷰를 다시 진행하세요."
        )
    from .creative_gates import require_creative_plan, require_text_plan
    require_creative_plan(run_root)
    require_text_plan(run_root)
    return record


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="검토가 끝난 현재 영상 생성대본을 렌더링용으로 승인합니다."
    )
    parser.add_argument("run_directory", type=Path, help="runs 아래의 실행 폴더")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        record = approve_video_plan(args.run_directory)
    except (OSError, ValueError) as error:
        print(f"영상 생성대본 승인 실패: {error}", file=sys.stderr)
        return 1
    print(
        "영상 생성대본 승인 완료: "
        f"{args.run_directory / APPROVAL_FILENAME} ({record.video_plan_sha256})"
    )
    return 0
