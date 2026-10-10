import json
import os
from pathlib import Path

import pytest

from video_harness.render_sources import resolve_render_source
from video_harness.run_threejs_backend import RunThreeJSSequenceRenderBackend
from video_harness.tests.test_render_sources import make_run
from video_harness.tests.test_run_source_integration import native_job


@pytest.mark.skipif(os.environ.get('VG_REAL_THREEJS') != '1', reason='opt-in browser integration')
def test_python_host_renders_snapshot_without_shared_bundle_output(tmp_path):
    run = make_run(tmp_path/'run',engine='threejs')
    (run/'scripts/scene.ts').write_text('''
export function Gallery(job, {THREE}) {
  const scene=new THREE.Scene(); scene.background=new THREE.Color('gold');
  const camera=new THREE.PerspectiveCamera(45,2,.1,100); camera.position.z=5;
  return {scene,camera,renderFrame() {},stateSnapshot() {return {
    canonical_frame:0,simulation_time:0,visible_layers:['custom'],geometry_operation_keys:[],
    camera:{position:[0,0,5],target:[0,0,0]},entity_scales:{},state_fingerprint:'source'
  }}};
}''')
    source = resolve_render_source(run,'new-graph',engine='threejs')
    backend = RunThreeJSSequenceRenderBackend(source)
    public_bundle = backend.renderer_dir/'dist/browser.js'
    before = public_bundle.read_bytes() if public_bundle.exists() else None
    # Staging is separate from original source run, as in produce/variants.
    out = tmp_path/'staging/frames'
    report = json.loads(backend.render_frames(native_job(frames=1),out).read_text())
    assert report['backend']['actual'] == 'swiftshader'
    assert report['renderer_version'] == backend.version
    assert report['state_samples'][0]['continuity']
    assert before == (public_bundle.read_bytes() if public_bundle.exists() else None)
    job = json.loads((out/'render-job.json').read_text())
    assert Path(job['run_source_bundle']).is_relative_to(run)
    assert job['run_source_asset_urls']['assets/model.glb'].startswith('data:')
