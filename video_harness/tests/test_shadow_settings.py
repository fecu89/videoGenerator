import json

import pytest

from video_harness.settings import HarnessSettings, resolve_run_settings, settings_sha256, write_settings_snapshot
from video_harness.settings_catalog import settings_catalog


def test_new_run_freezes_2gb_and_exposes_advanced_control(tmp_path):
    settings = HarnessSettings()
    write_settings_snapshot(tmp_path, settings)
    restored = resolve_run_settings(tmp_path)
    assert restored.schema_version == 7
    assert restored.blender.shadow_pool_mb == 2048
    control = next(c for c in settings_catalog() if c.key == 'blender.shadow_pool_mb')
    assert control.advanced
    assert '2048' in [o.value for o in control.options]
    with pytest.raises(ValueError):
        HarnessSettings(blender={'shadow_pool_mb': 2000})


def test_v6_keeps_historical_hash_and_snapshot_bytes(tmp_path):
    (tmp_path / 'run-settings.json').write_text('{"schema_version":6}')
    before = (tmp_path / 'run-settings.json').read_bytes()
    settings = resolve_run_settings(tmp_path)
    assert not hasattr(settings, 'blender')
    assert settings_sha256(settings) == '1a83ee8dc1f349f8ab1896a10544c3899267397a7e12bd5a2bb6c5ad49753dfc'
    assert (tmp_path / 'run-settings.json').read_bytes() == before
