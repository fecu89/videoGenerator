from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from video_harness.pipeline import build_parser as build_produce_parser


PROJECT_DIR = Path(__file__).resolve().parents[2]


def run_harness(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "video_harness", *args],
        cwd=PROJECT_DIR,
        text=True,
        capture_output=True,
        check=False,
    )


def test_voice_subcommand_exposes_help():
    result = run_harness("voice", "--help")

    assert result.returncode == 0
    assert "VoxCPM2" not in result.stdout
    assert "Qwen3-TTS" in result.stdout
    assert "--voxcpm-voice" not in result.stdout
    assert "--speed-mode" not in result.stdout
    assert "--voice-identifier" not in result.stdout


def test_validate_subcommand_exposes_help():
    result = run_harness("validate", "--help")

    assert result.returncode == 0
    assert "실행 폴더" in result.stdout


def test_render_subcommand_exposes_help():
    result = run_harness("render", "--help")

    assert result.returncode == 0
    assert "과학" in result.stdout


def test_migrate_production_subcommand_exposes_help():
    result = run_harness("migrate-production", "--help")

    assert result.returncode == 0
    assert "production-plan.json" in result.stdout


def test_plan_video_subcommand_exposes_help():
    result = run_harness("plan-video", "--help")

    assert result.returncode == 0
    assert "프롬프트" in result.stdout


def test_approve_video_plan_subcommand_exposes_help():
    result = run_harness("approve-video-plan", "--help")

    assert result.returncode == 0
    assert "영상 생성대본" in result.stdout


def test_render_production_subcommand_exposes_help():
    result = run_harness("render-production", "--help")

    assert result.returncode == 0
    assert "샷" in result.stdout


def test_review_shot_subcommand_exposes_help():
    result = run_harness("review-shot", "--help")

    assert result.returncode == 0
    assert "승인" in result.stdout


def test_produce_local_subcommand_exposes_help():
    result = run_harness("produce-local", "--help")

    assert result.returncode == 0
    assert "local" in result.stdout.lower()
    assert "--quality" in result.stdout
    assert "--force" in result.stdout


def test_produce_subcommand_exposes_settings_aware_options():
    result = run_harness("produce", "--help")

    assert result.returncode == 0
    assert "--output-mode" in result.stdout
    assert "--variant-mode" in result.stdout
    assert "--refresh-settings" in result.stdout


def test_produce_omits_cli_overrides_until_user_supplies_them():
    args = build_produce_parser().parse_args(["runs/example"])

    assert args.output_mode is None
    assert args.variant_mode is None
    assert args.quality == "draft"
    assert args.force is False


def test_produce_local_defaults_to_draft_and_allows_explicit_final():
    from video_harness.produce_local import build_parser

    assert build_parser().parse_args(["runs/example"]).quality == "draft"
    assert build_parser().parse_args(["runs/example", "--quality", "final"]).quality == "final"


def test_settings_subcommand_exposes_help():
    result = run_harness("settings", "--help")

    assert result.returncode == 0
    assert "--refresh-settings" in result.stdout


def test_settings_ui_subcommand_exposes_local_server_options():
    result = run_harness("settings-ui", "--help")

    assert result.returncode == 0
    assert "--port" in result.stdout
    assert "--no-open" in result.stdout
    assert "127.0.0.1" in result.stdout


def test_unknown_subcommand_is_rejected():
    result = run_harness("unknown")

    assert result.returncode == 2
    assert "voice" in result.stderr
    assert "blender" in result.stderr
    assert "validate" in result.stderr
    assert "render" in result.stderr
    assert "migrate-production" in result.stderr
    assert "plan-video" in result.stderr
    assert "render-production" in result.stderr
    assert "review-shot" in result.stderr
    assert "produce-local" in result.stderr
    assert "produce" in result.stderr
    assert "settings" in result.stderr
    assert "settings-ui" in result.stderr


def test_preview_subcommand_exposes_help():
    result = run_harness("preview", "--help")

    assert result.returncode == 0
    assert "대표 프레임" in result.stdout


def test_stage_approval_subcommands_expose_help():
    for name, phrase in (("approve-preview", "프리뷰승인"), ("approve-draft", "초본승인")):
        result = run_harness(name, "--help")
        assert result.returncode == 0 and phrase in result.stdout


def test_translate_scaffold_subcommand_exposes_help():
    result = run_harness("translate-scaffold", "--help")

    assert result.returncode == 0
    assert "번역" in result.stdout


def test_voice_subcommand_exposes_target_language():
    result = run_harness("voice", "--help")

    assert result.returncode == 0
    assert "--target-language" in result.stdout
