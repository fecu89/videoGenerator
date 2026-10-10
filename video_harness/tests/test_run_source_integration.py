import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from video_harness.blender_backend import blender_binary
from video_harness.render_sources import resolve_render_source
from video_harness.run_blender_backend import RunBlenderSequenceRenderBackend, ConfiguredBlenderSequenceRenderBackend
from video_harness.settings import HarnessSettings, write_settings_snapshot
from video_harness.sequence_qa import SequenceStateReport
from video_harness.tests.test_render_sources import make_run


def native_run(run, pool=2048):
    make_run(run)
    scripts = Path(__file__).with_name('fixtures') / 'run-render-source/scripts'
    for name in ('scene.py', 'physics.py'):
        shutil.copyfile(scripts / name, run / 'scripts' / name)
    write_settings_snapshot(run, HarnessSettings(blender={'shadow_pool_mb': pool}))
    return run


def native_job(*, width=320, height=180, lights=4, frames=3):
    return dict(job_kind='sequence',scene_graph='new-graph',sequence_id='SEQ01',frame_count=frames,
        duration_frames=frames,canonical_fps=30,output=dict(width=width,height=height,fps=30),
        sample_frames=list(range(frames)),physics={'lights':lights},style={},
        timeline=[dict(beat_id='B01',start_frame=0,end_frame=frames,controller='run-animation',priority=0,controller_options={})],
        canonical_state_cache=[dict(canonical_frame=i,simulation_time=i/30,active_beat_ids=['B01']) for i in range(frames)])


@pytest.mark.skipif(os.environ.get('VG_REAL_BLENDER') != '1', reason='opt-in native Blender verification')
def test_native_two_runs_render_rebuild_without_changing_git(tmp_path):
    subprocess.run(['git','init','-q',str(tmp_path)],check=True)
    (tmp_path / '.gitignore').write_text('runs/\n')
    (tmp_path / 'harness.py').write_text('# shared\n')
    subprocess.run(['git','add','.'],cwd=tmp_path,check=True)
    (tmp_path / 'harness.py').write_text('# existing user change\n')
    status = lambda: subprocess.check_output(['git','status','--porcelain=v1','--untracked-files=all'],cwd=tmp_path)
    before = status()
    for name in ('a', 'b'):
        run = native_run(tmp_path / 'runs' / name)
        if name == 'b':
            scene = run/'scripts/scene.py'
            scene.write_text(scene.read_text().replace('range(6)', 'range(4)'))
        for turn in range(2):
            source = resolve_render_source(run,'new-graph',engine='blender')
            backend = RunBlenderSequenceRenderBackend(source)
            target = run / '.render-cache' / f'render-{turn}'
            report = SequenceStateReport.model_validate_json(backend.render_frames(native_job(),target).read_text())
            assert report.blender_settings == {'shadow_pool_mb':2048}
            assert len({s.state_fingerprint for s in report.state_samples}) == 3
            assert report.backend.actual == 'blender_eevee'
            output = subprocess.check_output([str(blender_binary()),'--background',str(target/'scene.blend'),
                '--python-exit-code','1','--python-expr',
                "import bpy; print('SHADOW_POOL_CHECK='+bpy.context.scene.eevee.shadow_pool_size)"],text=True)
            assert 'SHADOW_POOL_CHECK=2048' in output
            (run/'scripts/scene.py').write_text((run/'scripts/scene.py').read_text().replace('canonical_frame * .025','canonical_frame * .04'))
        shutil.rmtree(run / '.render-cache')
        assert (run / 'scripts/scene.py').is_file()
    assert status() == before


@pytest.mark.skipif(os.environ.get('VG_REAL_BLENDER') != '1', reason='opt-in native Blender verification')
def test_new_builtin_scene_saves_requested_pool(tmp_path):
    job = native_job(frames=1)
    job.update(scene_graph='stellar-spectra-blender-v1',style={'seed':10},physics={'model':'schematic-stellar-spectra'})
    job['timeline'][0]['controller'] = 'spectra-sun'
    report = json.loads(ConfiguredBlenderSequenceRenderBackend(settings=HarnessSettings()).render_frames(job,tmp_path).read_text())
    assert report['blender_settings'] == {'shadow_pool_mb':2048}


@pytest.mark.skipif(os.environ.get('VG_REAL_BLENDER') != '1', reason='opt-in native Blender verification')
def test_bad_run_scene_exits_nonzero_without_report(tmp_path):
    run = native_run(tmp_path/'run')
    (run/'scripts/scene.py').write_text('raise RuntimeError("intentional scene failure")')
    source = resolve_render_source(run,'new-graph',engine='blender')
    with pytest.raises(RuntimeError,match='intentional scene failure'):
        RunBlenderSequenceRenderBackend(source).render_frames(native_job(),run/'.render-cache/bad')
    assert not (run/'.render-cache/bad/frame-report.json').exists()


@pytest.mark.skipif(os.environ.get('VG_REAL_BLENDER') != '1', reason='opt-in native Blender verification')
def test_mcp_two_scenes_keep_logical_anchor_names_in_one_process(tmp_path):
    class CaptureClient:
        def __init__(self): self.codes = []
        def execute(self, code):
            self.codes.append(code)
            return {'rendered':False}
    client = CaptureClient()
    for name in ('a','b'):
        run = native_run(tmp_path/name)
        (run/'scripts/scene.py').write_text('''
from render_runtime.blender_base import BlenderGalleryBase
class Gallery(BlenderGalleryBase):
    def build(self):
        self.animated.append(self.rect('Anchor', 0, 0, 2, 2, (.3,.7,.9)))
''')
        source = resolve_render_source(run,'new-graph',engine='blender')
        job = native_job(frames=1)
        job['timeline'][0]['controller_options']={'labels':[{'text':'대상','anchor':'Anchor','kind':'word','side':'right','emphasis':'none'}]}
        RunBlenderSequenceRenderBackend(source).prepare_scene(job, run/'editable.blend', client)
    script = tmp_path/'mcp-test.py'
    script.write_text('\n'.join(client.codes)+"\nprint('TWO_SCENES_OK')\n")
    result = subprocess.run([str(blender_binary()),'--background','--factory-startup','--python-exit-code','1',
                             '--python',str(script)],capture_output=True,text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'TWO_SCENES_OK' in result.stdout
    assert all((tmp_path/name/'editable.blend').is_file() for name in ('a','b'))
