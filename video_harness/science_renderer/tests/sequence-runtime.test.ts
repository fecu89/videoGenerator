import {describe, expect, it} from 'vitest';

import {DEFAULT_PHYSICS} from '../src/math/circular-orbit.js';
import type {SequenceRenderJob} from '../src/render-job.js';
import {
  applyMergedPatch,
  applyPersistentEvents,
  canonicalFrameForOutput,
  createFrameOrderGuard,
  createSequenceState,
} from '../src/sequences/contracts.js';
import {
  SEQUENCE_CONTROLLER_REGISTRY,
  createSequenceRuntime,
} from '../src/sequences/sequence-registry.js';
import {createSharedScene} from '../src/visuals/solar-system.js';


const sequenceJob = (
  overrides: Partial<SequenceRenderJob> = {},
): SequenceRenderJob => ({
  job_kind: 'sequence',
  sequence_id: 'SEQ01',
  scene_graph: 'shared-science-scene',
  canonical_fps: 30,
  duration_frames: 2,
  frame_count: 2,
  output_directory: '/tmp/sequence-runtime-test',
  output: {width: 320, height: 180, fps: 30},
  timeline: [],
  canonical_state_cache: [
    {canonical_frame: 0, active_beat_ids: [], simulation_time: 4},
    {canonical_frame: 1, active_beat_ids: [], simulation_time: 5},
  ],
  sample_frames: [0, 1],
  style: {seed: 220826, earth_scale: 0.075, mars_scale: 0.055},
  ...overrides,
});


describe('persistent sequence runtime', () => {
  it('keeps shown layers until an explicit hide event', () => {
    const state = createSequenceState();
    applyPersistentEvents(state, {showLayers: ['skyTrail']});
    applyPersistentEvents(state, {});
    expect(Array.from(state.visibleLayers)).toEqual(['skyTrail']);
    applyPersistentEvents(state, {hideLayers: ['skyTrail']});
    expect(Array.from(state.visibleLayers)).toEqual([]);
  });

  it('maps 15fps draft frames onto the 30fps canonical timeline', () => {
    expect(canonicalFrameForOutput(10, 15, 30, 400)).toBe(20);
    expect(canonicalFrameForOutput(250, 15, 30, 400)).toBe(399);
  });

  it('rejects rendering frames out of order', () => {
    const guard = createFrameOrderGuard();
    guard.accept(0);
    guard.accept(1);
    expect(() => guard.accept(0)).toThrow(/increasing order/);
  });

  it('applies explicit hides after geometry operations can reveal a layer', () => {
    const objects = createSharedScene({seed: 1, width: 320, height: 180});
    const state = createSequenceState();

    applyMergedPatch(
      objects,
      state,
      {
        simulationDay: 0,
        geometryOperations: [{kind: 'direction_arrows', key: 'arrows'}],
        showLayers: ['earthDirectionArrow'],
        hideLayers: ['earthDirectionArrow'],
      },
      DEFAULT_PHYSICS,
    );

    expect(objects.earthDirectionArrow.visible).toBe(false);
    expect(state.visibleLayers.has('earthDirectionArrow')).toBe(false);
  });

  it('rejects an unknown shown layer before mutating persistent state', () => {
    const objects = createSharedScene({seed: 1, width: 320, height: 180});
    const state = createSequenceState(['orbitGroup']);

    expect(() => applyMergedPatch(
      objects,
      state,
      {
        simulationDay: 0,
        showLayers: ['skyTrail', 'not-a-layer'],
      },
      DEFAULT_PHYSICS,
    )).toThrow('unknown sequence layer: not-a-layer');

    expect([...state.visibleLayers]).toEqual(['orbitGroup']);
    expect(objects.skyTrail.visible).toBe(true);
  });

  it('rejects an unknown hidden layer before mutating persistent state', () => {
    const objects = createSharedScene({seed: 1, width: 320, height: 180});
    const state = createSequenceState(['orbitGroup', 'skyTrail']);

    expect(() => applyMergedPatch(
      objects,
      state,
      {
        simulationDay: 0,
        hideLayers: ['skyTrail', 'not-a-layer'],
      },
      DEFAULT_PHYSICS,
    )).toThrow('unknown sequence layer: not-a-layer');

    expect([...state.visibleLayers]).toEqual(['orbitGroup', 'skyTrail']);
    expect(objects.skyTrail.visible).toBe(true);
  });

  it('sorts simultaneous controllers by priority and beat id before merging', () => {
    SEQUENCE_CONTROLLER_REGISTRY.set('test-low', {
      sample: () => ({
        geometryOperations: [{kind: 'direction_arrows', key: 'low'}],
        camera: {position: [1, 2, 3], target: [0, 0, 0]},
        entityOverrides: {earth: {scale: 2}},
      }),
    });
    SEQUENCE_CONTROLLER_REGISTRY.set('test-high', {
      sample: () => ({
        geometryOperations: [{kind: 'direction_arrows', key: 'high'}],
        camera: {position: [4, 5, 6], target: [1, 0, 0]},
        entityOverrides: {earth: {scale: 3}},
      }),
    });
    const objects = createSharedScene({seed: 1, width: 320, height: 180});
    const job = sequenceJob({
      duration_frames: 1,
      frame_count: 1,
      timeline: [
        {
          beat_id: 'B02',
          start_frame: 0,
          end_frame: 1,
          simulation_time_start: 0,
          simulation_time_end: 0,
          controller: 'test-high',
          patch_targets: ['geometry', 'camera', 'entities'],
          priority: 2,
          controller_options: {},
        },
        {
          beat_id: 'B01',
          start_frame: 0,
          end_frame: 1,
          simulation_time_start: 0,
          simulation_time_end: 0,
          controller: 'test-low',
          patch_targets: ['geometry', 'camera', 'entities'],
          priority: 1,
          controller_options: {},
        },
      ],
      canonical_state_cache: [
        {canonical_frame: 0, active_beat_ids: ['B02', 'B01'], simulation_time: 9},
      ],
      sample_frames: [0],
    });

    try {
      const runtime = createSequenceRuntime(job, objects);
      runtime.renderFrame(0);
      const snapshot = runtime.stateSnapshot();

      expect(snapshot.simulation_time).toBe(9);
      expect(snapshot.geometry_operation_keys).toEqual(['low', 'high']);
      expect(snapshot.camera).toEqual({position: [4, 5, 6], target: [1, 0, 0]});
      expect(snapshot.entity_scales.earth).toBe(3);
    } finally {
      SEQUENCE_CONTROLLER_REGISTRY.delete('test-low');
      SEQUENCE_CONTROLLER_REGISTRY.delete('test-high');
    }
  });

  it('rejects a canonical cache with missing frames', () => {
    const objects = createSharedScene({seed: 1, width: 320, height: 180});
    const job = sequenceJob({
      canonical_state_cache: [
        {canonical_frame: 0, active_beat_ids: [], simulation_time: 0},
        {canonical_frame: 2, active_beat_ids: [], simulation_time: 1},
      ],
    });

    expect(() => createSequenceRuntime(job, objects)).toThrow(/exactly 0/);
  });

  it('rejects a canonical cache whose simulation time decreases', () => {
    const objects = createSharedScene({seed: 1, width: 320, height: 180});
    const job = sequenceJob({
      canonical_state_cache: [
        {canonical_frame: 0, active_beat_ids: [], simulation_time: 2},
        {canonical_frame: 1, active_beat_ids: [], simulation_time: 1},
      ],
    });

    expect(() => createSequenceRuntime(job, objects)).toThrow(/simulation time/);
  });

  it('rejects an inactive timeline item with an unknown controller', () => {
    const objects = createSharedScene({seed: 1, width: 320, height: 180});
    const job = sequenceJob({
      timeline: [{
        beat_id: 'B01',
        start_frame: 0,
        end_frame: 2,
        simulation_time_start: 4,
        simulation_time_end: 5,
        controller: 'not-a-controller',
        patch_targets: ['geometry'],
        priority: 0,
        controller_options: {},
      }],
    });

    expect(() => createSequenceRuntime(job, objects)).toThrow(
      'unknown sequence controller: not-a-controller',
    );
  });

  it('rejects an unknown beat on a canonical frame skipped by draft output', () => {
    const objects = createSharedScene({seed: 1, width: 320, height: 180});
    const job = sequenceJob({
      frame_count: 1,
      output: {width: 320, height: 180, fps: 15},
      canonical_state_cache: [
        {canonical_frame: 0, active_beat_ids: [], simulation_time: 4},
        {canonical_frame: 1, active_beat_ids: ['B99'], simulation_time: 5},
      ],
      sample_frames: [0],
    });

    expect(() => createSequenceRuntime(job, objects)).toThrow(
      'canonical cache names unknown beat: B99',
    );
  });

  it('rejects duplicate active beat ids in one canonical cache entry', () => {
    SEQUENCE_CONTROLLER_REGISTRY.set('test-known', {sample: () => ({})});
    const objects = createSharedScene({seed: 1, width: 320, height: 180});
    const job = sequenceJob({
      timeline: [{
        beat_id: 'B01',
        start_frame: 0,
        end_frame: 2,
        simulation_time_start: 4,
        simulation_time_end: 5,
        controller: 'test-known',
        patch_targets: ['geometry'],
        priority: 0,
        controller_options: {},
      }],
      canonical_state_cache: [
        {canonical_frame: 0, active_beat_ids: ['B01', 'B01'], simulation_time: 4},
        {canonical_frame: 1, active_beat_ids: [], simulation_time: 5},
      ],
    });

    try {
      expect(() => createSequenceRuntime(job, objects)).toThrow(
        'canonical cache repeats active beat: B01',
      );
    } finally {
      SEQUENCE_CONTROLLER_REGISTRY.delete('test-known');
    }
  });
});
