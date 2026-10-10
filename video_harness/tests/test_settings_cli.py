from __future__ import annotations

import json
import importlib
from pathlib import Path

import pytest


def settings_main(arguments: list[str]) -> int:
    return importlib.import_module("video_harness.settings_cli").main(arguments)


def test_settings_command_prints_effective_json_without_persisting(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
):
    settings_module = importlib.import_module("video_harness.settings")
    settings_file = tmp_path / "settings.json"
    settings_module.write_project_settings(
        settings_module.HarnessSettings(),
        settings_file=settings_file,
    )
    monkeypatch.setattr(settings_module, "PROJECT_SETTINGS_FILE", settings_file)

    code = settings_main([str(tmp_path)])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert code == 0
    assert payload["settings"]["pipeline"]["output_mode"] == "all"
    assert not (tmp_path / "run-settings.json").exists()


def test_refresh_requires_an_existing_run_directory(tmp_path: Path):
    with pytest.raises(SystemExit) as error:
        settings_main([str(tmp_path / "missing"), "--refresh-settings"])

    assert error.value.code == 2


def test_refresh_writes_snapshot_before_printing(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    code = settings_main([str(run_dir), "--refresh-settings"])

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert (run_dir / "run-settings.json").is_file()
    assert payload["settings"]["schema_version"] == 7
