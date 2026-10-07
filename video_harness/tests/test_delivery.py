import sys
from pathlib import Path
from types import SimpleNamespace

from video_harness import delivery


def test_absent_hook_is_optional_for_production_but_explicit_delivery_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(delivery, 'HOOK', tmp_path / 'missing.py')
    assert delivery.run_delivery(tmp_path, automatic=True) == 0
    assert delivery.run_delivery(tmp_path) == 1


def test_hook_gets_explicit_arguments_without_shell_or_secrets(tmp_path, monkeypatch):
    hook = tmp_path / 'delivery.py'
    hook.write_text('# local hook')
    monkeypatch.setattr(delivery, 'HOOK', hook)
    calls = []
    monkeypatch.setattr(delivery.subprocess, 'run', lambda command, **kwargs: calls.append((command, kwargs)) or SimpleNamespace(returncode=7))
    assert delivery.run_delivery(tmp_path / 'run with spaces', automatic=True) == 7
    assert calls[0][0] == [sys.executable, str(hook), '--action', 'upload', '--run-dir', str(tmp_path / 'run with spaces'), '--automatic']
    assert not calls[0][1].get('shell', False)


def test_authorize_profile_and_plan_commands(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(delivery, 'run_delivery', lambda run, **kwargs: calls.append((run, kwargs)) or 0)
    assert delivery.main(['--authorize', '--profile', 'en']) == 0
    assert calls[-1] == (None, {'action': 'authorize', 'profile': 'en'})
    assert delivery.main([str(tmp_path), '--plan']) == 0
    assert calls[-1][1]['action'] == 'plan'
