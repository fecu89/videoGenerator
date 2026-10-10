import json
from types import SimpleNamespace

import pytest

from video_harness.render_runtime.blender_settings import apply_blender_settings
from video_harness.render_sources import resolve_render_source
from video_harness.run_blender_backend import RunBlenderSequenceRenderBackend, ConfiguredBlenderSequenceRenderBackend
from video_harness.settings import HarnessSettings
from video_harness.tests.test_render_sources import make_run


def test_shadow_setting_applied_to_actual_scene_or_fails_explicitly():
    scene = SimpleNamespace(render=SimpleNamespace(engine='BLENDER_EEVEE'), eevee=SimpleNamespace(shadow_pool_size='512'))
    assert apply_blender_settings(scene, {'shadow_pool_mb': 2048}) == {'shadow_pool_mb': 2048}
    assert scene.eevee.shadow_pool_size == '2048'
    with pytest.raises(RuntimeError, match='Shadow Pool'):
        apply_blender_settings(SimpleNamespace(render=scene.render, eevee=object()), {'shadow_pool_mb': 2048})


def test_run_backend_host_validation_does_not_load_scene_and_mcp_uses_same_snapshot(tmp_path):
    source = resolve_render_source(make_run(tmp_path / 'run'), 'new-graph', engine='blender')
    backend = RunBlenderSequenceRenderBackend(source, settings=HarnessSettings())
    job = {'scene_graph': 'new-graph', 'sequence_id': 'seq'}
    prepared = backend.prepare_job(job)
    assert prepared['blender_settings']['shadow_pool_mb'] == 2048
    assert prepared['run_source']['entrypoint'] == 'scripts/scene.py:Gallery'
    class Client:
        def execute(self, code):
            self.code = code
            return {'rendered': False}
    client = Client()
    backend.prepare_scene(job, tmp_path / 'mcp/scene.blend', client)
    mcp_job = json.loads((tmp_path / 'mcp/scene.job.json').read_text())
    assert mcp_job['run_source'] == prepared['run_source']
    assert 'build_gallery' in client.code


def test_changed_source_refuses_to_render_with_old_backend(tmp_path):
    source = resolve_render_source(make_run(tmp_path / 'run'), 'new-graph', engine='blender')
    backend = RunBlenderSequenceRenderBackend(source, settings=HarnessSettings())
    before = backend.version
    (source.run_dir / 'assets/model.glb').write_bytes(b'new GLB')
    assert backend.version != before
    with pytest.raises(ValueError, match='changed'):
        backend.prepare_job({'scene_graph': 'new-graph'})


def test_new_builtin_execution_has_settings_bound_version():
    a = ConfiguredBlenderSequenceRenderBackend(settings=HarnessSettings())
    b = ConfiguredBlenderSequenceRenderBackend(settings=HarnessSettings(blender={'shadow_pool_mb': 512}))
    assert a.version != b.version
