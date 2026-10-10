import json
import sys
from pathlib import Path

import pytest

from video_harness.render_sources import resolve_render_source, create_source_snapshot
from video_harness.render_runtime.source_loader import load_source_symbol


def make_run(root, *, engine='blender', value=1):
    root.mkdir(parents=True, exist_ok=True)
    (root / 'scripts').mkdir(exist_ok=True)
    (root / 'assets').mkdir(exist_ok=True)
    extension = 'py' if engine == 'blender' else 'ts'
    (root / f'scripts/scene.{extension}').write_text('raise RuntimeError("host must not import scene")\n')
    (root / 'scripts/physics.py').write_text(f'count = {value}\ndef validate_job(job):\n    global count\n    count += 1\n    return count\n')
    (root / 'scripts/simulation.schema.json').write_text(json.dumps({'type': 'object'}))
    (root / 'assets/model.glb').write_bytes(b'first model')
    (root / 'simulation.json').write_text('{"preset":"run-scene"}')
    manifest = {'schema_version': 1, 'simulation_schema': 'scripts/simulation.schema.json',
                'graphs': {'new-graph': {'engine': engine, 'entrypoint': f'scripts/scene.{extension}:Gallery',
                'validator': 'scripts/physics.py:validate_job',
                'source_files': [f'scripts/scene.{extension}', 'scripts/physics.py'],
                'assets': ['assets/model.glb']}}}
    (root / 'render-source.json').write_text(json.dumps(manifest))
    return root


def test_run_dependencies_change_only_their_own_digest(tmp_path):
    a, b = [make_run(tmp_path / name) for name in ('a', 'b')]
    get = lambda run: resolve_render_source(run, 'new-graph', engine='blender')
    first, second = get(a).sha256, get(b).sha256
    assert first == second  # Absolute paths are not content identity.
    for name, data in [('assets/model.glb', b'new model'), ('scripts/physics.py', b'def validate_job(job): pass'),
                       ('simulation.json', b'{"preset":"run-scene","physics":{}}'),
                       ('run-settings.json', b'{"schema_version":7,"blender":{"shadow_pool_mb":512}}')]:
        old = get(a).sha256
        (a / name).write_bytes(data)
        assert get(a).sha256 != old
        assert get(b).sha256 == second


@pytest.mark.parametrize('bad', ['../outside.py', '/tmp/scene.py', 'scripts/../scene.py', 'assets/scene.py'])
def test_source_paths_cannot_escape_scripts(tmp_path, bad):
    run = make_run(tmp_path / 'run')
    path = run / 'render-source.json'
    data = json.loads(path.read_text())
    data['graphs']['new-graph']['source_files'].append(bad)
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        resolve_render_source(run, 'new-graph', engine='blender')


def test_undeclared_entry_missing_file_and_symlink_escape_are_rejected(tmp_path):
    run = make_run(tmp_path / 'run')
    scene = run / 'scripts/scene.py'
    scene.unlink()
    with pytest.raises(ValueError, match='scene.py'):
        resolve_render_source(run, 'new-graph', engine='blender')
    outside = tmp_path / 'outside.py'
    outside.write_text('pass')
    scene.symlink_to(outside)
    with pytest.raises(ValueError):
        resolve_render_source(run, 'new-graph', engine='blender')


def test_missing_manifest_is_legacy_but_malformed_manifest_is_not(tmp_path):
    assert resolve_render_source(tmp_path, 'old', engine='blender') is None
    (tmp_path / 'render-source.json').write_text('{}')
    with pytest.raises(ValueError):
        resolve_render_source(tmp_path, 'old', engine='blender')


def test_snapshot_validator_is_isolated_and_does_not_import_bpy(tmp_path):
    sources = [resolve_render_source(make_run(tmp_path / n), 'new-graph', engine='blender') for n in ('a', 'b')]
    before = 'bpy' in sys.modules
    funcs = [load_source_symbol(create_source_snapshot(s), s.spec.validator, namespace=s.namespace) for s in sources]
    assert funcs[0]({}) == 2
    assert funcs[0]({}) == 3
    assert funcs[1]({}) == 2
    assert ('bpy' in sys.modules) == before
    assert not list(tmp_path.rglob('*.pyc'))


def test_snapshot_rejects_changed_source_and_tampering(tmp_path):
    run = make_run(tmp_path / 'run')
    source = resolve_render_source(run, 'new-graph', engine='blender')
    snapshot = create_source_snapshot(source)
    (snapshot / 'assets/model.glb').write_bytes(b'tampered')
    with pytest.raises(ValueError, match='snapshot'):
        create_source_snapshot(source)
    (run / 'scripts/physics.py').write_text('changed')
    with pytest.raises(ValueError, match='changed'):
        create_source_snapshot(source)


def test_cli_inspection_creates_no_run_files(tmp_path, capsys):
    from video_harness.__main__ import main
    run = make_run(tmp_path / 'run')
    before = {str(p): p.read_bytes() for p in run.rglob('*') if p.is_file()}
    assert main(['render-source', str(run)]) == 0
    assert 'new-graph' in capsys.readouterr().out
    assert before == {str(p): p.read_bytes() for p in run.rglob('*') if p.is_file()}


def test_copy_race_cannot_publish_a_snapshot(tmp_path, monkeypatch):
    source = resolve_render_source(make_run(tmp_path/'run'), 'new-graph', engine='blender')
    original = Path.read_bytes
    count = 0
    def racing_read(path):
        nonlocal count
        if path == source.run_dir/'assets/model.glb':
            count += 1
            if count == 2:  # After the initial current-source check, during copy.
                path.write_bytes(b'changed during copy')
        return original(path)
    monkeypatch.setattr(Path,'read_bytes',racing_read)
    with pytest.raises(ValueError,match='changed'):
        create_source_snapshot(source)
    assert not (source.run_dir/'.render-cache/source-snapshots'/source.sha256).exists()


def test_undeclared_snapshot_code_cannot_be_imported(tmp_path):
    source = resolve_render_source(make_run(tmp_path/'run'), 'new-graph', engine='blender')
    snapshot = create_source_snapshot(source)
    (snapshot/'scripts/undeclared.py').write_text('x=1')
    with pytest.raises(ValueError,match='Undeclared'):
        create_source_snapshot(source)
