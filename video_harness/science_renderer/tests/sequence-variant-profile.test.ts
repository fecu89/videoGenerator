import {describe, expect, it} from 'vitest';

import type {SequenceRenderJob} from '../src/render-job.js';
import {
  SEQUENCE_CONTROLLER_REGISTRY,
  createSequenceRuntime,
} from '../src/sequences/sequence-registry.js';
import {
  applySequenceVariantProfile,
  layerRevealProgress,
  lightingExposure,
  parseSequenceVariantProfile,
} from '../src/sequences/variant-profile.js';
import {createSharedScene} from '../src/visuals/solar-system.js';


describe('sequence presentation variants', () => {
  it('changes camera distance while preserving its target and direction', () => {
    const patch = {
      simulationDay: 42,
      camera: {position: [3, 4, 0] as [number, number, number], target: [0, 0, 0] as [number, number, number]},
      geometryOperations: [{kind: 'orbit_and_sightline' as const, key: 'orbit', day: 42}],
    };

    const wide = applySequenceVariantProfile(patch, parseSequenceVariantProfile({camera_profile: 'wide'}));
    const close = applySequenceVariantProfile(patch, parseSequenceVariantProfile({camera_profile: 'close'}));

    expect(wide.camera?.position?.[0]).toBeCloseTo(3.45);
    expect(wide.camera?.position?.[1]).toBeCloseTo(4.6);
    expect(wide.camera?.target).toEqual([0, 0, 0]);
    expect(close.camera?.position?.[0]).toBeCloseTo(2.55);
    expect(close.camera?.position?.[1]).toBeCloseTo(3.4);
    expect(close.camera?.target).toEqual([0, 0, 0]);
    expect(wide.simulationDay).toBe(42);
    expect(wide.geometryOperations).toEqual(patch.geometryOperations);
    expect(wide.geometryOperations).not.toBe(patch.geometryOperations);
  });

  it('maps only layer reveal progress and lighting constants', () => {
    expect(layerRevealProgress(0.8, {layer_timing_profile: 'explain'})).toBeCloseTo(0.92);
    expect(layerRevealProgress(0.25, {layer_timing_profile: 'dynamic'})).toBe(0.15625);
    expect(layerRevealProgress(0.25, {})).toBe(0.25);
    expect(lightingExposure({lighting_profile: 'clear'})).toBe(1.18);
    expect(lightingExposure({lighting_profile: 'cinematic'})).toBe(0.96);
    expect(lightingExposure({})).toBe(1.1);
  });

  it('emphasizes declared display scales without adding or changing physics fields', () => {
    const patch = {
      simulationDay: 12.5,
      entityOverrides: {earth: {scale: 2, visible: true}, sun: {visible: false}},
      geometryOperations: [{kind: 'sky_track' as const, key: 'track', startDay: 1, endDay: 2, count: 5}],
    };

    const profiled = applySequenceVariantProfile(
      patch,
      parseSequenceVariantProfile({scale_profile: 'emphasis'}),
    );

    expect(profiled.entityOverrides).toEqual({earth: {scale: 2.24, visible: true}, sun: {visible: false}});
    expect(profiled.simulationDay).toBe(12.5);
    expect(profiled.geometryOperations).toEqual(patch.geometryOperations);
    expect(patch.entityOverrides.earth.scale).toBe(2);
  });

  it('rejects unknown or non-presentation profile values', () => {
    expect(() => parseSequenceVariantProfile({duration_frames: 10})).toThrow(/unknown variant profile field/);
    expect(() => parseSequenceVariantProfile({camera_profile: 'orbit'})).toThrow(/camera_profile/);
  });

  it('applies presentation profiles in runtime without changing physics or geometry', () => {
    const observedProgress: number[] = [];
    SEQUENCE_CONTROLLER_REGISTRY.set('variant-test-controller', {
      sample(context) {
        observedProgress.push(context.progress, context.layerRevealProgress!);
        return {
          geometryOperations: [{kind: 'orbit_and_sightline', key: 'orbit', day: context.simulationDay}],
          camera: {position: [3, 4, 0], target: [0, 0, 0]},
          entityOverrides: {earth: {scale: 2}},
        };
      },
    });
    const job: SequenceRenderJob = {
      job_kind: 'sequence',
      sequence_id: 'SEQ01',
      scene_graph: 'shared-science-scene',
      canonical_fps: 30,
      duration_frames: 3,
      frame_count: 3,
      output_directory: '/tmp/variant-runtime-test',
      output: {width: 320, height: 180, fps: 30},
      timeline: [{
        beat_id: 'B01', start_frame: 0, end_frame: 3,
        simulation_time_start: 7, simulation_time_end: 9,
        controller: 'variant-test-controller',
        patch_targets: ['geometry', 'camera', 'entities'],
        priority: 0, controller_options: {},
      }],
      canonical_state_cache: [
        {canonical_frame: 0, active_beat_ids: ['B01'], simulation_time: 7},
        {canonical_frame: 1, active_beat_ids: ['B01'], simulation_time: 8},
        {canonical_frame: 2, active_beat_ids: ['B01'], simulation_time: 9},
      ],
      sample_frames: [0, 1, 2],
      style: {seed: 1, earth_scale: 0.075},
      variant_profile: {
        camera_profile: 'wide', layer_timing_profile: 'explain',
        lighting_profile: 'clear', scale_profile: 'emphasis',
      },
    };

    try {
      const objects = createSharedScene({seed: 1, width: 320, height: 180});
      const runtime = createSequenceRuntime(job, objects);
      runtime.renderFrame(1);
      const sample = runtime.stateSnapshot();

      expect(observedProgress[0]).toBe(0.5);
      expect(observedProgress[1]).toBeCloseTo(0.575);
      expect(sample.simulation_time).toBe(8);
      expect(sample.geometry_operation_keys).toEqual(['orbit']);
      expect(sample.camera.position[0]).toBeCloseTo(3.45);
      expect(sample.camera.position[1]).toBeCloseTo(4.6);
      expect(sample.entity_scales.earth).toBeCloseTo(2.24);
    } finally {
      SEQUENCE_CONTROLLER_REGISTRY.delete('variant-test-controller');
    }
  });
});
