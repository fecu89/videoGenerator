import {createHash} from 'node:crypto';
import {mkdtemp, readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

import {describe, expect, it} from 'vitest';

import {
  renderJob,
  type LegacyRenderJob,
  type SequenceRenderJob,
} from '../src/render-frame.js';


describe('headless fixed-frame rendering', () => {
  it(
    'renders distinct first and last PNG frames at the requested size',
    async () => {
      const outputDirectory = await mkdtemp(join(tmpdir(), 'science-render-'));
      const job: LegacyRenderJob = {
        scene_id: 6,
        title: '지구가_앞지른다',
        template: 'earth-overtake',
        simulation_day_start: -35,
        simulation_day_end: 35,
        duration_seconds: 1,
        frame_count: 2,
        output_directory: outputDirectory,
        output: {width: 320, height: 180, fps: 2},
        physics: {
          earth_period_days: 365,
          mars_period_days: 687,
          earth_orbit_radius: 1,
          mars_orbit_radius: 1.52,
          opposition_day: 0,
        },
        style: {seed: 220826, earth_scale: 0.075, mars_scale: 0.055},
      };

      const report = await renderJob(job);
      const first = await readFile(report.frames[0]!);
      const last = await readFile(report.frames[1]!);

      expect(report.frame_count).toBe(2);
      expect(report.backend.renderer).not.toBe('');
      expect(['metal', 'swiftshader']).toContain(report.backend.actual);
      expect(report.timings.frame_count).toBe(report.frame_count);
      expect(report.timings.total_ms).toBeGreaterThan(0);
      expect(report.timings.initialization_ms).toBeGreaterThan(0);
      expect(report.timings.capture_ms).toBeCloseTo(
        report.timings.canvas_encode_capture_ms + report.timings.browser_to_node_transfer_ms,
        5,
      );
      expect(report.browser_version).toMatch(/^\d+\./u);
      expect(report.capture_timing_mode).toBe('split');
      expect(report.capture_method).toMatch(/^(locator|data-url|blob-array-buffer|blob-base64|loopback-blob)-png$/u);
      expect(report.capture_transport_bytes).toBeGreaterThan(first.length + last.length);
      expect(report.backend.requested).toBe('swiftshader');
      expect(report.backend.actual).toBe('swiftshader');
      expect(first.length).toBeGreaterThan(1000);
      expect(last.length).toBeGreaterThan(1000);
      expect(createHash('sha256').update(first).digest('hex')).not.toBe(
        createHash('sha256').update(last).digest('hex'),
      );
    },
    30_000,
  );

  it.skipIf(process.platform !== 'darwin')(
    'keeps explicit Metal jobs selectable and attested',
    async () => {
      const outputDirectory = await mkdtemp(join(tmpdir(), 'science-render-metal-'));
      const job: LegacyRenderJob = {
        renderer_backend: 'metal',
        scene_id: 6,
        title: 'metal-opt-in',
        template: 'earth-overtake',
        simulation_day_start: 0,
        simulation_day_end: 1,
        duration_seconds: 1,
        frame_count: 1,
        output_directory: outputDirectory,
        output: {width: 160, height: 90, fps: 1},
        physics: {
          earth_period_days: 365,
          mars_period_days: 687,
          earth_orbit_radius: 1,
          mars_orbit_radius: 1.52,
          opposition_day: 0,
        },
        style: {seed: 220826, earth_scale: 0.075, mars_scale: 0.055},
      };

      const report = await renderJob(job);

      expect(report.backend.requested).toBe('metal');
      expect(report.backend.actual).toBe('metal');
    },
    30_000,
  );

  it(
    'renders an eclipse job without Mars physics',
    async () => {
      const outputDirectory = await mkdtemp(join(tmpdir(), 'eclipse-render-'));
      const job = {
        scene_id: 7,
        title: '일식정렬',
        template: 'solar-eclipse-alignment',
        simulation_day_start: -6,
        simulation_day_end: 0,
        duration_seconds: 1,
        frame_count: 2,
        output_directory: outputDirectory,
        output: {width: 320, height: 180, fps: 2},
        style: {seed: 5107, earth_scale: 1, moon_scale: 1, sun_scale: 1},
        eclipse: {
          parameters: {
            moon_orbit_inclination_degrees: 5,
            moon_orbit_radius: 2.2,
            sun_distance: 8,
            sun_longitude_degrees: 0,
            moon_longitude_start_degrees: -6,
            moon_longitude_end_degrees: 0,
          },
          renderer_options: {show_umbra: true},
        },
      } as unknown as LegacyRenderJob;

      const report = await renderJob(job);
      const first = await readFile(report.frames[0]!);
      const last = await readFile(report.frames[1]!);

      expect(report.frame_count).toBe(2);
      expect(first.length).toBeGreaterThan(1000);
      expect(last.length).toBeGreaterThan(1000);
      expect(createHash('sha256').update(first).digest('hex')).not.toBe(
        createHash('sha256').update(last).digest('hex'),
      );
    },
    30_000,
  );

  it(
    'renders one shared sequence graph and reports ordered state samples',
    async () => {
      const outputDirectory = await mkdtemp(join(tmpdir(), 'sequence-render-'));
      const job: SequenceRenderJob = {
        job_kind: 'sequence',
        sequence_id: 'SEQ01',
        scene_graph: 'shared-science-scene',
        canonical_fps: 30,
        duration_frames: 2,
        frame_count: 2,
        output_directory: outputDirectory,
        output: {width: 320, height: 180, fps: 30},
        timeline: [],
        canonical_state_cache: [
          {canonical_frame: 0, active_beat_ids: [], simulation_time: 0},
          {canonical_frame: 1, active_beat_ids: [], simulation_time: 1},
        ],
        sample_frames: [0, 1],
        style: {seed: 220826, earth_scale: 0.075, mars_scale: 0.055},
      };

      const report = await renderJob(job);

      expect(report.sequence_id).toBe('SEQ01');
      expect(report.frame_count).toBe(2);
      expect(report.state_samples.map((sample) => sample.canonical_frame)).toEqual([0, 1]);
      expect(report.state_samples.map((sample) => sample.simulation_time)).toEqual([0, 1]);
      expect(report.state_samples.every((sample) => sample.state_fingerprint.length > 0))
        .toBe(true);
    },
    30_000,
  );
});
