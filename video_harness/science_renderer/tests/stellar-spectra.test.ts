import {mkdtemp, readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {describe, expect, it} from 'vitest';
import {renderJob, type SequenceRenderJob} from '../src/render-frame.js';
import {strengths} from '../src/sequences/stellar-spectra.js';

describe('stellar spectra diagrams', () => {
  it('preserves the hot/cool ambiguity and the other diagnostic lines',()=>{
    const hot=strengths(35000),a=strengths(9000),cool=strengths(3200);
    expect(a.h).toBeGreaterThan(hot.h);expect(a.h).toBeGreaterThan(cool.h);
    expect(hot.he).toBeGreaterThan(cool.he);expect(cool.molecule).toBeGreaterThan(hot.molecule);
    expect(()=>strengths(0)).toThrow();
  });
  it.each(['spectra-dispersion','spectra-temperature-question','spectra-elements',
    'spectra-hot','spectra-cool','spectra-classify','spectra-subtype'])(
    'renders %s through the real Three.js path', async (controller) => {
    const directory=await mkdtemp(join(tmpdir(),'stellar-three-'));
    const job: SequenceRenderJob={job_kind:'sequence',sequence_id:'SEQ02',
      scene_graph:'stellar-spectra-threejs-v1',canonical_fps:3,duration_frames:3,
      frame_count:3,output_directory:directory,output:{width:480,height:270,fps:3},
      timeline:[{beat_id:'B03',start_frame:0,end_frame:3,simulation_time_start:0,
        simulation_time_end:1,controller,priority:0,
        patch_targets:['geometry','camera','layers'],controller_options:{}}],
      canonical_state_cache:[0,1,2].map(i=>({canonical_frame:i,simulation_time:i/3,active_beat_ids:['B03']})),
      sample_frames:[0,1,2],style:{seed:20260915,earth_scale:1}};
    const report=await renderJob(job);
    expect(report.backend.actual).toBe('swiftshader');
    expect(report.state_samples.map(s=>s.canonical_frame)).toEqual([0,1,2]);
    expect(report.state_samples[2]!.visible_layers).toContain(controller);
    const first=await readFile(report.frames[0]!);
    const last=await readFile(report.frames[2]!);
    expect(first.equals(last)).toBe(false);
    expect(last.length).toBeGreaterThan(5000);
  },30000);
});
