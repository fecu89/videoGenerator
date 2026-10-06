import {describe, expect, it} from 'vitest';
import * as THREE from 'three';

import type {SequenceRenderJob} from '../src/render-job.js';
import {
  createSequenceRuntime,
  createSequenceSceneGraph,
} from '../src/sequences/sequence-registry.js';


const CONTROLLERS = [
  'reveal-hr-axes',
  'plot-hr-source-stars',
  'reveal-main-sequence',
  'reveal-giants-and-supergiants',
  'reveal-white-dwarfs',
  'compare-stellar-radii',
  'connect-radius-to-hr-position',
  'summarize-hr-map',
] as const;


const hrJob = (
  controller: string,
  durationFrames = 3,
  variantProfile: Record<string, unknown> = {},
): SequenceRenderJob => ({
  job_kind: 'sequence',
  sequence_id: 'SEQ-HR-01',
  scene_graph: 'hr-diagram-teaching-model-v1',
  canonical_fps: 30,
  duration_frames: durationFrames,
  frame_count: durationFrames,
  output_directory: '/tmp/hr-diagram-sequence-test',
  output: {width: 320, height: 180, fps: 30},
  timeline: [{
    beat_id: 'B01',
    start_frame: 0,
    end_frame: durationFrames,
    simulation_time_start: 0,
    simulation_time_end: durationFrames - 1,
    controller,
    patch_targets: ['geometry', 'layers', 'camera', 'hide_events'],
    priority: 0,
    controller_options: {},
  }],
  canonical_state_cache: Array.from({length: durationFrames}, (_, frame) => ({
    canonical_frame: frame,
    active_beat_ids: ['B01'],
    simulation_time: frame,
  })),
  sample_frames: [0, durationFrames - 1],
  style: {seed: 4, earth_scale: 0.075, mars_scale: 0.055},
  variant_profile: variantProfile,
});


const createHrObjects = () => createSequenceSceneGraph(
  'hr-diagram-teaching-model-v1',
  {seed: 4, width: 320, height: 180},
);


describe('H-R diagram teaching sequence', () => {
  it.each(CONTROLLERS)(
    'renders %s through the continuous sequence runtime',
    (controller) => {
      const objects = createHrObjects();
      const runtime = createSequenceRuntime(hrJob(controller), objects);

      runtime.renderFrame(2);

      expect(objects.hr.group.visible).toBe(true);
      expect(objects.orbitGroup.visible).toBe(false);
      expect(objects.eclipse.group.visible).toBe(false);
      expect(runtime.stateSnapshot().geometry_operation_keys).toEqual([
        `hr-${controller}`,
      ]);
    },
  );

  it('reveals the four source-backed regions cumulatively', () => {
    const expectations = [
      ['reveal-main-sequence', ['main_sequence']],
      [
        'reveal-giants-and-supergiants',
        ['main_sequence', 'red_giant', 'supergiant'],
      ],
      [
        'reveal-white-dwarfs',
        ['main_sequence', 'red_giant', 'supergiant', 'white_dwarf'],
      ],
    ] as const;

    for (const [controller, visibleCategories] of expectations) {
      const objects = createHrObjects();
      const runtime = createSequenceRuntime(hrJob(controller), objects);
      runtime.renderFrame(2);
      const visible = Object.entries(objects.hr.regions)
        .filter(([, region]) => region.visible)
        .map(([category]) => category);
      expect(visible.sort()).toEqual([...visibleCategories].sort());
    }
  });

  it('connects equal spectral type while retaining absolute-magnitude height', () => {
    const objects = createHrObjects();
    const runtime = createSequenceRuntime(
      hrJob('connect-radius-to-hr-position'),
      objects,
    );

    runtime.renderFrame(2);

    const position = objects.hr.temperatureGuide.geometry.attributes.position!;
    const arcturus = new THREE.Vector3().fromBufferAttribute(position, 0);
    const epsilonEridani = new THREE.Vector3().fromBufferAttribute(position, 1);
    expect(arcturus.x).toBeCloseTo(epsilonEridani.x, 8);
    expect(arcturus.y).toBeGreaterThan(epsilonEridani.y);
    expect(objects.hr.temperatureGuide.visible).toBe(true);
  });

  it('summarizes all source points, regions, and named markers', () => {
    const objects = createHrObjects();
    const runtime = createSequenceRuntime(hrJob('summarize-hr-map'), objects);

    runtime.renderFrame(2);

    expect(objects.hr.sourceStars.geometry.drawRange.count).toBe(30);
    expect(Object.values(objects.hr.regions).every((region) => region.visible))
      .toBe(true);
    expect(objects.hr.namedStarMarkers.children.every((marker) => marker.visible))
      .toBe(true);
  });

  it('keeps source positions byte-for-byte identical across variants', () => {
    const snapshots: number[][] = [];
    for (const profile of [
      {camera_profile: 'wide', layer_timing_profile: 'explain'},
      {camera_profile: 'close', layer_timing_profile: 'dynamic'},
    ]) {
      const objects = createHrObjects();
      const runtime = createSequenceRuntime(
        hrJob('plot-hr-source-stars', 3, profile),
        objects,
      );
      runtime.renderFrame(2);
      snapshots.push(Array.from(
        objects.hr.sourceStars.geometry.attributes.position!.array,
      ));
    }
    expect(snapshots[0]).toEqual(snapshots[1]);
  });
});
