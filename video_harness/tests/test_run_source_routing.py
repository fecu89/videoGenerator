import json
from types import SimpleNamespace

import pytest

from video_harness.sequence_render import backend_for_plan, _physics_payload, _style_payload
from video_harness.simulation import load_simulation
from video_harness.tests.test_render_sources import make_run
from video_harness.tests.test_simulation import make_script, simulation_payload


def test_unregistered_graph_and_legacy_can_share_engine(tmp_path):
    run = make_run(tmp_path / 'run')
    plan = SimpleNamespace(renderer='blender', sequences=[
        SimpleNamespace(sequence_id='custom', renderer=None, scene_graph='new-graph'),
        SimpleNamespace(sequence_id='builtin', renderer=None, scene_graph='stellar-spectra-blender-v1')])
    backend = backend_for_plan(plan, run_dir=run)
    assert type(backend.backend_for_sequence('custom')).__name__ == 'RunBlenderSequenceRenderBackend'
    assert type(backend.backend_for_sequence('builtin')).__name__ == 'ConfiguredBlenderSequenceRenderBackend'
    (run / 'run-settings.json').write_text('{"schema_version":6}')
    assert type(backend_for_plan(plan, run_dir=run).backend_for_sequence('builtin')).__name__ == 'BlenderSequenceRenderBackend'


def test_generic_simulation_validates_run_schema_and_scene_ids(tmp_path):
    run = make_run(tmp_path / 'run')
    data = simulation_payload(1)
    data.update(preset='run-scene', physics={'speed': 2}, style={'color': 'gold'}, scenes=[{'scene_id': 1}])
    schema = {'type': 'object', 'properties': {'physics': {'type': 'object',
              'properties': {'speed': {'type': 'number', 'exclusiveMinimum': 0}}, 'required': ['speed']}}}
    (run / 'scripts/simulation.schema.json').write_text(json.dumps(schema))
    (run / 'simulation.json').write_text(json.dumps(data))
    simulation = load_simulation(run, make_script(1))
    assert _physics_payload(simulation) == {'speed': 2}
    assert _style_payload(simulation) == {'color': 'gold'}
    with pytest.raises(ValueError, match='scenes must match'):
        load_simulation(run, make_script(2))
    data['physics']['speed'] = -1
    (run / 'simulation.json').write_text(json.dumps(data))
    with pytest.raises(ValueError, match='speed'):
        load_simulation(run, make_script(1))


def test_run_text_policy_blocks_direct_text_in_declared_sources(tmp_path):
    from video_harness.render_sources import run_source_policy_issues, resolve_render_source
    run = make_run(tmp_path / 'run')
    (run / 'scripts/scene.py').write_text('self.text("title", 0, 0)')
    source = resolve_render_source(run, 'new-graph', engine='blender')
    assert any('CalloutLayer' in issue for issue in run_source_policy_issues(source))


def write_approval_plan(run):
    from video_harness.settings import HarnessSettings, write_settings_snapshot
    write_settings_snapshot(run, HarnessSettings(local_video={'text_policy':'keywords'}))
    sequence = {'sequence_id':'SEQ01','scene_ids':[1],'duration_frames':3,'render_mode':'simulation',
                'scene_graph':'new-graph','scene_spans':[{'scene_id':1,'start_frame':0,'end_frame':3,
                'audio_start_frame':0,'audio_end_frame':3,'tail_silence_frames':0}],
                'timeline':[{'beat_id':'B01','start_frame':0,'end_frame':3,'simulation_time_start':0,
                'simulation_time_end':1,'controller':'run','patch_targets':['geometry']}]}
    plan = {'schema_version':1,'renderer':'blender','script_sha256':'a'*64,'production_plan_sha256':'b'*64,
            'defaults':{'width':1920,'height':1080,'fps':30},'sequences':[sequence]}
    (run/'local-sequence-plan.json').write_text(json.dumps(plan))
    (run/'video-plan-approval.json').write_text('{"approved":true}')
    (run/'text-preview-gate.json').write_text('{"status":"passed"}')


def test_source_asset_simulation_and_settings_edits_invalidate_only_their_run(tmp_path):
    from video_harness import stage_approvals as stage
    from video_harness.production import script_sha256
    runs = [make_run(tmp_path/n) for n in ('a','b')]
    for run in runs:
        write_approval_plan(run)
        (run/'preview-report.json').write_text(json.dumps({'renderer_versions':stage.current_renderer_versions(run),
            'local_sequence_plan_sha256':script_sha256(run/'local-sequence-plan.json')}))
        stage.approve_preview(run)
    a,b = runs
    baseline = stage.current_renderer_versions(b)
    for name, update in [
        ('scripts/physics.py',lambda data:data+'\n# new calculation\n'),
        ('assets/model.glb',lambda data:data+'new GLB bytes'),
        ('simulation.json',lambda data:'{"preset":"run-scene","physics":{"speed":2}}'),
        ('run-settings.json',lambda data:data.replace('2048','512')),
    ]:
        path=a/name
        path.write_text(update(path.read_text()))
        with pytest.raises(ValueError,match='렌더러'):
            stage.require_current_preview_approval(a)
        stage.require_current_preview_approval(b)
        assert stage.current_renderer_versions(b) == baseline
