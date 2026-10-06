from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .settings import resolve_run_settings, settings_sha256, write_project_settings
from .pacing_presets import PACING_PRESETS, apply_pacing_preset, pacing_status


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="현재 적용되는 비밀값 없는 Video Generator 설정을 표시합니다."
    )
    parser.add_argument("run_directory", nargs="?", type=Path)
    parser.add_argument(
        "--refresh-settings",
        action="store_true",
        help="현재 프로젝트 설정으로 기존 실행 스냅샷을 다시 기록합니다.",
    )
    parser.add_argument("--preset", choices=[p["id"] for p in PACING_PRESETS], help="영상 템포를 적용해 표시합니다. 저장하려면 --save를 함께 사용합니다.")
    parser.add_argument("--save", action="store_true", help="--preset 결과를 프로젝트 설정에 저장합니다.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    run_dir = arguments.run_directory
    if arguments.refresh_settings and (run_dir is None or not run_dir.is_dir()):
        parser.error("--refresh-settings requires an existing run directory")

    if arguments.preset and (run_dir is not None or arguments.refresh_settings):
        parser.error("--preset applies to project settings only; refresh existing runs separately")
    if arguments.save and not arguments.preset:
        parser.error("--save requires --preset")

    settings = resolve_run_settings(
        run_dir,
        refresh=arguments.refresh_settings,
        persist=arguments.refresh_settings,
    )
    if arguments.preset:
        settings = apply_pacing_preset(settings, arguments.preset)
        if arguments.save:
            write_project_settings(settings)
    print(
        json.dumps(
            {
                "settings": settings.model_dump(mode="json"),
                "settings_sha256": settings_sha256(settings),
                "pacing": pacing_status(settings),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0
