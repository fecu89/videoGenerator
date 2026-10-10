import {mkdtemp, mkdir, writeFile, readFile, realpath} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join, resolve} from 'node:path';
import {expect, it} from 'vitest';
import {buildRunBrowserBundle} from '../src/build-run-source.js';
import {renderJob} from '../src/render-frame.js';
import type {RunSequenceRenderJob} from '../src/render-job.js';

it('builds and renders new graphs entirely under two run directories', async () => {
  const root = await realpath(await mkdtemp(join(tmpdir(), 'run-source-')));
  const images: Buffer[] = [];
  for (const [name, color] of [['a', 'red'], ['b', 'blue']]) {
    const run = join(root, name!);
    await mkdir(join(run, 'scripts'), {recursive: true});
    await writeFile(join(run, 'scripts/scene.ts'), `
      export function createRunSequence(job, {THREE}) {
        const scene = new THREE.Scene(); scene.background = new THREE.Color('${color}');
        const camera = new THREE.PerspectiveCamera(45, 2, .1, 100); camera.position.z=5;
        return {scene, camera, renderFrame() {}, stateSnapshot() {return {
          canonical_frame:0,simulation_time:0,visible_layers:['custom'],geometry_operation_keys:[],
          camera:{position:[0,0,5],target:[0,0,0]},entity_scales:{},state_fingerprint:'placeholder'
        }}};
      }`);
    const bundle = await buildRunBrowserBundle({snapshot_root: run, entrypoint: 'scripts/scene.ts',
      export_name: 'createRunSequence', output_path: join(run, '.render-cache/browser.js'),
      renderer_root: resolve('.')});
    expect(bundle.startsWith(run)).toBe(true);
    const job: RunSequenceRenderJob = {job_kind:'sequence', scene_graph:`new-${name}`, sequence_id:'seq',
      canonical_fps:30, duration_frames:1, frame_count:1, output_directory:join(run,'.render-cache/frames'),
      output:{width:160,height:80,fps:30}, timeline:[],canonical_state_cache:[],sample_frames:[0],
      physics:{},style:{custom:true},run_source_bundle:bundle,run_source_asset_urls:{}};
    const report = await renderJob(job);
    images.push(await readFile(report.frames[0]!));
    expect('state_samples' in report && report.state_samples[0]!.continuity).toBeTruthy();
  }
  expect(images[0]!.equals(images[1]!)).toBe(false);
}, 30000);

it('rejects missing entrypoint exports at build time', async () => {
  const run = await mkdtemp(join(tmpdir(), 'run-source-missing-'));
  await mkdir(join(run, 'scripts'));
  await writeFile(join(run, 'scripts/scene.ts'), 'export const wrong = 1;');
  await expect(buildRunBrowserBundle({snapshot_root:run, entrypoint:'scripts/scene.ts',
    export_name:'createRunSequence',output_path:join(run,'build/browser.js'), renderer_root:resolve('.')})).rejects.toThrow();
});
