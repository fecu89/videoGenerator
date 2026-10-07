"""Optional private delivery hook; provider code and credentials stay outside Git."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HOOK = PROJECT_ROOT / '.local-integrations' / 'delivery.py'


def run_delivery(run_dir: Path | None, *, action: str = 'upload', automatic: bool = False, profile: str | None = None) -> int:
    if not HOOK.is_file():
        if automatic:
            return 0
        print('로컬 전달 모듈이 없습니다: .local-integrations/delivery.py')
        return 1
    command = [sys.executable, str(HOOK), '--action', action]
    if run_dir is not None:
        command.extend(['--run-dir', str(Path(run_dir).resolve())])
    if automatic:
        command.append('--automatic')
    if profile:
        command.extend(['--profile', profile])
    # No shell and no credentials on the command line. The hook owns authentication.
    return subprocess.run(command, cwd=PROJECT_ROOT, check=False).returncode


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='선택적인 로컬 모듈로 완성 영상을 전달합니다.')
    parser.add_argument('run_directory', type=Path, nargs='?')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--plan', action='store_true', help='전달할 파일·제목·설명만 확인')
    group.add_argument('--authorize', action='store_true', help='로컬 전달 모듈 최초 인증')
    parser.add_argument('--profile', help='로컬 전달 모듈의 인증 프로필')
    args = parser.parse_args(argv)
    if not args.authorize and args.run_directory is None:
        parser.error('실행 폴더가 필요합니다.')
    try:
        return run_delivery(args.run_directory, action='authorize' if args.authorize else 'plan' if args.plan else 'upload', profile=args.profile)
    except OSError:
        print('로컬 전달 모듈을 실행하지 못했습니다. 파일과 실행 환경을 확인하세요.')
        return 1
