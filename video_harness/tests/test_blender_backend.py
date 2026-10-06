"""Boundary tests: framing, error propagation, dispatch and frame-time semantics."""
import importlib.util
import json
import socket
import threading
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from video_harness.sequence_models import LocalSequencePlan


@contextmanager
def server(response):
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(1)
    received = []
    def serve():
        conn, _ = listener.accept()
        with conn:
            data = b''
            while b'\0' not in data:
                data += conn.recv(1024)
            received.append(json.loads(data.split(b'\0')[0]))
            wire = json.dumps(response).encode() + b'\0'
            for i in range(0, len(wire), 7):
                conn.sendall(wire[i:i+7])
    worker = threading.Thread(target=serve, daemon=True)
    worker.start()
    try:
        yield listener.getsockname()[1], received
    finally:
        worker.join(timeout=3)
        listener.close()


def module():
    assert importlib.util.find_spec('video_harness.blender_backend') is not None, 'Blender backend is missing'
    from video_harness import blender_backend
    return blender_backend


def test_mcp_reads_fragmented_null_delimited_response():
    backend = module()
    with server({'status':'ok', 'result':{'version':'5.2.1', 'name':'태양'}}) as (port, received):
        result = backend.BlenderMCPClient(port=port).execute('result = {}')
    assert result == {'version':'5.2.1', 'name':'태양'}
    assert received == [{'type':'execute', 'code':'result = {}', 'strict_json':True}]


def test_mcp_propagates_python_errors():
    backend = module()
    with server({'status':'error', 'message':'Render failed'}) as (port, _):
        with pytest.raises(RuntimeError, match='Render failed'):
            backend.BlenderMCPClient(port=port).execute('raise ValueError()')


def test_prepare_sends_small_file_reference_for_large_timeline(tmp_path):
    # The desktop addon reads small chunks per UI tick; embedding a production
    # timeline in the command can time out before it gets executed.
    job = dict(scene_graph='stellar-spectra-blender-v1', sequence_id='SEQ01',
        frame_count=3000, duration_frames=3000, canonical_fps=30,
        output=dict(width=1920, height=1080, fps=30),
        timeline=[dict(beat_id='B01', start_frame=0, end_frame=3000,
                       controller='spectra-sun', priority=0, controller_options={})],
        canonical_state_cache=[dict(canonical_frame=i, simulation_time=i/30,
                                   active_beat_ids=['B01']) for i in range(3000)])
    destination = tmp_path/'review.blend'
    with server({'status':'ok', 'result':{'rendered':False}}) as (port, received):
        module().BlenderMCPClient(port=port).prepare_scene(job, destination)
    assert len(json.dumps(received[0]).encode()) < 4096
    assert json.loads(destination.with_suffix('.job.json').read_text()) == job
    compile(received[0]['code'], '<blender-mcp>', 'exec')


def test_explicit_blender_plan_uses_blender_and_old_plans_keep_threejs():
    from video_harness import sequence_render
    assert hasattr(sequence_render, 'backend_for_plan'), 'Plan renderer selection is missing'
    payload = dict(schema_version=1, script_sha256='a'*64, production_plan_sha256='b'*64,
                   defaults=dict(width=1920,height=1080,fps=30),sequences=[])
    legacy = LocalSequencePlan.model_validate(payload)
    assert type(sequence_render.backend_for_plan(legacy)).__name__ == 'LocalSequenceRenderBackend'
    modern = LocalSequencePlan.model_validate({**payload, 'renderer':'blender'})
    assert type(sequence_render.backend_for_plan(modern)).__name__ == 'BlenderSequenceRenderBackend'


def test_renderer_rejects_unregistered_graph_before_invoking_blender(tmp_path):
    backend = module().BlenderSequenceRenderBackend()
    with pytest.raises(ValueError, match='scene_graph'):
        backend.render_frames({'scene_graph':'typo'}, tmp_path)
    assert not (tmp_path/'render-job.json').exists()


@pytest.mark.parametrize('renderer', ['python', 'pyrender', 'blnder', ''])
def test_unsupported_renderer_never_silently_falls_back_to_threejs(renderer):
    from types import SimpleNamespace
    from video_harness.sequence_render import backend_for_plan

    # Also guard callers that supply a plan without Pydantic validation.
    with pytest.raises(ValueError, match='unsupported renderer'):
        backend_for_plan(SimpleNamespace(renderer=renderer, sequences=[]))
    with pytest.raises(ValueError, match='unsupported renderer'):
        backend_for_plan(SimpleNamespace(renderer=renderer, sequences=[
            SimpleNamespace(sequence_id='SEQ01', renderer=None),
            SimpleNamespace(sequence_id='SEQ02', renderer='blender'),
        ]))


def test_renderer_cache_version_changes_when_star_texture_changes(tmp_path):
    backend = module().BlenderSequenceRenderBackend()
    backend.renderer_dir = tmp_path
    (tmp_path/'scene.py').write_text('pass')
    (tmp_path/'assets').mkdir()
    texture = tmp_path/'assets'/'photosphere.png'
    texture.write_bytes(b'first texture')
    before = backend.version
    texture.write_bytes(b'updated texture')
    assert backend.version != before


def test_mixed_plan_routes_each_sequence_and_rejects_unknown_sequence():
    from video_harness.sequence_render import backend_for_plan
    from video_harness.sequence_models import LocalSequence
    from types import SimpleNamespace
    assert 'renderer' in LocalSequence.model_fields
    local=SimpleNamespace(renderer='threejs', sequences=[
        SimpleNamespace(sequence_id='SEQ01',renderer='blender'),
        SimpleNamespace(sequence_id='SEQ02',renderer=None)])
    router=backend_for_plan(local)
    assert type(router.backend_for_sequence('SEQ01')).__name__=='BlenderSequenceRenderBackend'
    assert type(router.backend_for_sequence('SEQ02')).__name__=='LocalSequenceRenderBackend'
    with pytest.raises(ValueError,match='unknown sequence'):
        router.backend_for_sequence('SEQ99')


def test_spectral_model_preserves_line_positions_and_nonmonotonic_hydrogen():
    assert importlib.util.find_spec('video_harness.blender_renderer.spectra') is not None
    from video_harness.blender_renderer.spectra import line_strengths, canonical_frame
    cool, warm, hot = [line_strengths(t) for t in (3500,9000,35000)]
    assert warm['hydrogen'] > hot['hydrogen']
    assert warm['hydrogen'] > cool['hydrogen']
    assert hot['helium_ionized'] > cool['helium_ionized']
    assert cool['molecules'] > hot['molecules']
    assert canonical_frame(1, 12, 30, 100) == 2
    assert canonical_frame(39, 12, 30, 100) == 97
    assert canonical_frame(40, 12, 30, 100) == 99


def test_blender_simulation_loads_without_fake_planet_parameters(tmp_path):
    from video_harness.models import ScriptArtifact
    from video_harness.simulation import load_simulation
    script = ScriptArtifact.model_validate(dict(selected_topic=dict(title='x',reason='x'),
        story_engine={k:'x' for k in ('common_belief','contradiction','obvious_answer','constraint','actual_answer','mechanism','payoff')},
        scenes=[dict(scene_id=1,title='별',narration='별입니다.',narrative_role='HOOK',visual_subject='별')]))
    payload = dict(schema_version=1,preset='stellar-spectra-blender',
        output=dict(width=1920,height=1080,fps=30,video_codec='h264',audio_codec='aac'),
        physics=dict(model='schematic-stellar-spectra'),style=dict(seed=20260915),
        scenes=[dict(scene_id=1)])
    (tmp_path/'simulation.json').write_text(json.dumps(payload))
    config = load_simulation(tmp_path, script)
    assert config.physics.model == 'schematic-stellar-spectra'
    assert not hasattr(config.physics, 'mars_period_days')


@pytest.mark.skipif(__import__('os').environ.get('VG_REAL_BLENDER') != '1', reason='opt-in native smoke')
@pytest.mark.parametrize('controller', ['spectra-compare','spectra-absorption','spectra-hydrogen',
    'spectra-intro','spectra-distance','spectra-dispersion','spectra-temperature-question',
    'spectra-atmosphere','spectra-elements',
    'spectra-atom','spectra-hot','spectra-cool','spectra-disambiguate','spectra-classify',
    'spectra-subtype','spectra-sun'])
def test_native_blender_writes_pngs_editable_scene_and_truthful_state(tmp_path,controller):
    from PIL import Image, ImageStat
    from video_harness.sequence_qa import SequenceStateReport
    job=dict(scene_graph='stellar-spectra-blender-v1', sequence_id='SEQ01',
        frame_count=3,duration_frames=3,canonical_fps=3,
        output=dict(width=320,height=180,fps=3),
        timeline=[dict(beat_id='B01',start_frame=0,end_frame=3,controller=controller,
            priority=0,controller_options={})],
        canonical_state_cache=[dict(canonical_frame=i,simulation_time=i/3,active_beat_ids=['B01']) for i in range(3)],
        style=dict(seed=10),physics=dict(model='schematic-stellar-spectra'))
    report_path=module().BlenderSequenceRenderBackend().render_frames(job,tmp_path)
    report=SequenceStateReport.model_validate_json(report_path.read_text())
    assert report.backend.actual=='blender_eevee'
    assert [s.canonical_frame for s in report.state_samples]==[0,1,2]
    assert len({s.state_fingerprint for s in report.state_samples})==3
    assert (tmp_path/'scene.blend').stat().st_size > 10000
    for frame in report.frames:
        im=Image.open(frame).convert('RGB')
        assert im.size==(320,180)
        assert max(ImageStat.Stat(im).stddev)>10


def test_backend_checks_only_requested_sample_frames(tmp_path, monkeypatch):
    import video_harness.blender_backend as backend_module
    backend = backend_module.BlenderSequenceRenderBackend()
    job = {'job_kind': 'sequence', 'sequence_id': 'SEQ01', 'scene_graph': 'shared-science-scene',
           'canonical_fps': 10, 'duration_frames': 10, 'frame_count': 10, 'sample_frames': [2, 7],
           'output': {'width': 16, 'height': 9, 'fps': 10}, 'timeline': [], 'canonical_state_cache': [],
           'physics': {}, 'style': {}}
    monkeypatch.setattr(backend_module, 'validate_blender_job', lambda _job: None)
    monkeypatch.setattr(backend_module, 'blender_binary', lambda: Path('/bin/echo'))

    def fake_run(cmd, stdout, stderr):
        cache = Path(cmd[-1]).parent
        for index in (2, 7):
            (cache / f'frame-{index:06d}.png').write_bytes(b'x')
        (cache / 'scene.blend').write_bytes(b'blend')
        (cache / 'frame-report.json').write_text(json.dumps({
            'frames': [str(cache / 'frame-000002.png'), str(cache / 'frame-000007.png')],
            'frame_count': 2, 'sample_frames': [2, 7], 'backend': {'actual': 'blender_eevee'}}))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(backend_module.subprocess, 'run', fake_run)
    report = json.loads(backend.render_frames(job, tmp_path / 'cache').read_text())
    assert report['sample_frames'] == [2, 7]


def test_callout_and_worker_sources_compile_without_bpy():
    import ast
    root = Path(__file__).resolve().parents[1] / 'blender_renderer'
    for name in ('callout.py', 'worker.py'):
        ast.parse((root / name).read_text(encoding='utf-8'))


def test_worker_updates_view_layer_before_callouts_and_layer_uses_camera_matrix():
    root = Path(__file__).resolve().parents[1] / 'blender_renderer'
    worker = (root / 'worker.py').read_text(encoding='utf-8')
    assert worker.index("view_layers[0].update()") < worker.index("callouts.update(frame)")
    layer = (root / 'callout.py').read_text(encoding='utf-8')
    assert 'camera.matrix_world.inverted()' in layer
    assert 'rotation_euler.to_quaternion().inverted()' not in layer


def test_continuity_capture_records_font_objects_with_kind():
    root = Path(__file__).resolve().parents[1] / 'blender_renderer'
    source = (root / 'continuity_capture.py').read_text(encoding='utf-8')
    assert "'FONT'" in source and "row['kind']" in source
