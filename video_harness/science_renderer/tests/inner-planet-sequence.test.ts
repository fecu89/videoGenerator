import {describe, expect, it} from 'vitest';

import type {SequenceRenderJob} from '../src/render-job.js';
import {
  SEQUENCE_CONTROLLER_REGISTRY,
  createSequenceRuntime,
  createSequenceSceneGraph,
} from '../src/sequences/sequence-registry.js';
import type {SequenceControllerContext} from '../src/sequences/contracts.js';
import {
  applyGeometryOperations,
  applyMergedPatch,
  createSequenceState,
} from '../src/sequences/contracts.js';
import {createSharedScene} from '../src/visuals/solar-system.js';
import {DEFAULT_PHYSICS} from '../src/math/circular-orbit.js';


const innerPlanetJob = (
  controller: string,
  controllerOptions: Record<string, unknown>,
  durationFrames = 9,
): SequenceRenderJob => ({
  job_kind: 'sequence',
  sequence_id: 'SEQ03',
  scene_graph: 'inner-planet-overtake-teaching-model-v1',
  canonical_fps: 30,
  duration_frames: durationFrames,
  frame_count: durationFrames,
  output_directory: '/tmp/inner-planet-sequence-test',
  output: {width: 320, height: 180, fps: 30},
  timeline: [{
    beat_id: 'B06',
    start_frame: 0,
    end_frame: durationFrames,
    simulation_time_start: -45,
    simulation_time_end: 45,
    controller,
    patch_targets: ['geometry', 'layers', 'entities', 'camera', 'hide_events'],
    priority: 0,
    controller_options: controllerOptions,
  }],
  canonical_state_cache: Array.from({length: durationFrames}, (_, frame) => ({
    canonical_frame: frame,
    active_beat_ids: ['B06'],
    simulation_time: -45 + (90 * frame) / Math.max(1, durationFrames - 1),
  })),
  sample_frames: [0, durationFrames - 1],
  style: {seed: 9, earth_scale: 1, mars_scale: 1},
});


const unwrappedAngles = (values: readonly number[]): number[] => {
  if (values.length === 0) return [];
  const result = [values[0]!];
  for (let index = 1; index < values.length; index += 1) {
    const delta = Math.atan2(
      Math.sin(values[index]! - values[index - 1]!),
      Math.cos(values[index]! - values[index - 1]!),
    );
    result.push(result[index - 1]! + delta);
  }
  return result;
};


describe('inner-planet overtake sequence', () => {
  it('registers the deterministic inner-planet overtake controller', () => {
    expect(SEQUENCE_CONTROLLER_REGISTRY.has('show-inner-planet-overtake')).toBe(true);
  });

  it('registers a reusable inner-planet teaching scene graph', () => {
    expect(() => createSequenceSceneGraph('inner-planet-overtake-teaching-model-v1', {
      seed: 9,
      width: 320,
      height: 180,
    })).not.toThrow();
  });

  it('owns the inner orbit geometry and hides the outer-planet path', () => {
    const controller = SEQUENCE_CONTROLLER_REGISTRY.get('show-inner-planet-overtake')!;
    const context: SequenceControllerContext = {
      canonicalFrame: 15,
      simulationDay: 0,
      progress: 0.5,
      timelineItem: {
        beat_id: 'B09',
        start_frame: 0,
        end_frame: 31,
        simulation_time_start: -60,
        simulation_time_end: 60,
        controller: 'show-inner-planet-overtake',
        patch_targets: ['geometry', 'layers', 'entities', 'camera', 'hide_events'],
        priority: 0,
        controller_options: {},
      },
      controllerOptions: {},
    };

    expect(controller.sample(context)).toEqual({
      geometryOperations: [{
        kind: 'inner_planet_overtake',
        key: 'inner-planet-overtake',
        day: 0,
        orbitRadius: 0.72,
        periodDays: 224.7,
        conjunctionDay: 0,
      }],
      showLayers: [
        'orbitGroup',
        'innerPlanetGroup',
        'earthDirectionArrow',
        'innerPlanetDirectionArrow',
        'innerConjunctionLine',
      ],
      hideLayers: ['marsOrbitPath', 'sightline'],
      entityOverrides: {earth: {scale: 1.75}, mars: {visible: false}},
      camera: {position: [0, -4.4, 4.4], target: [0, 0, 0]},
    });
  });

  it('provides dedicated inner-planet geometry instead of reusing Mars', () => {
    const objects = createSharedScene({seed: 9, width: 320, height: 180});
    const innerObjects = objects as unknown as Record<string, unknown>;

    expect(innerObjects.innerPlanet).toBeDefined();
    expect(innerObjects.innerPlanetGroup).toBeDefined();
    expect(innerObjects.innerPlanetDirectionArrow).toBeDefined();
    expect(innerObjects.innerConjunctionLine).toBeDefined();
  });

  it('places the inner planet between the Sun and Earth at inferior conjunction', () => {
    const objects = createSharedScene({seed: 9, width: 320, height: 180});

    applyGeometryOperations(objects, DEFAULT_PHYSICS, [{
      kind: 'inner_planet_overtake',
      key: 'inner-planet-overtake',
      day: 0,
      orbitRadius: 0.72,
      periodDays: 224.7,
      conjunctionDay: 0,
    }]);

    expect(objects.innerPlanet.position.toArray()).toEqual([0.72, 0, 0]);
    expect(objects.earth.position.toArray()).toEqual([1, 0, 0]);
    expect(objects.innerPlanet.position.length()).toBeLessThan(
      objects.earth.position.length(),
    );
  });

  it('renders the inner-planet layers while removing Mars from the comparison', () => {
    const objects = createSharedScene({seed: 9, width: 320, height: 180});
    const state = createSequenceState();

    applyMergedPatch(objects, state, {
      simulationDay: 0,
      geometryOperations: [{
        kind: 'inner_planet_overtake',
        key: 'inner-planet-overtake',
        day: 0,
        orbitRadius: 0.72,
        periodDays: 224.7,
        conjunctionDay: 0,
      }],
      showLayers: [
        'orbitGroup',
        'innerPlanetGroup',
        'earthDirectionArrow',
        'innerPlanetDirectionArrow',
        'innerConjunctionLine',
      ],
      hideLayers: ['marsOrbitPath', 'sightline'],
      entityOverrides: {mars: {visible: false}},
    }, DEFAULT_PHYSICS);

    expect(objects.innerPlanetGroup.visible).toBe(true);
    expect(objects.innerPlanetDirectionArrow.visible).toBe(true);
    expect(objects.innerConjunctionLine.visible).toBe(true);
    expect(objects.mars.visible).toBe(false);
    expect(objects.marsOrbitPath.visible).toBe(false);
  });

  it('projects the Earth-to-inner-planet sightline onto fixed stars and shows reversal', () => {
    const objects = createSequenceSceneGraph(
      'inner-planet-overtake-teaching-model-v1',
      {seed: 9, width: 320, height: 180},
    );
    const runtime = createSequenceRuntime(innerPlanetJob(
      'show-inner-planet-retrograde-projection',
      {evidence_start_day: -45, evidence_end_day: 45},
    ), objects);

    runtime.renderFrame(8);

    expect(objects.innerSightline.visible).toBe(true);
    expect(objects.innerProjectionMarker.visible).toBe(true);
    expect(objects.innerProjectionHistory.visible).toBe(true);
    expect(objects.starWall.visible).toBe(true);

    const linePositions = objects.innerSightline.geometry.attributes.position!;
    expect(linePositions.getX(0)).toBeCloseTo(objects.earth.position.x, 6);
    expect(linePositions.getY(0)).toBeCloseTo(objects.earth.position.y, 6);
    expect(linePositions.getZ(0)).toBeCloseTo(objects.earth.position.z, 6);
    expect(objects.innerProjectionMarker.position.length()).toBeCloseTo(4.6, 5);

    const history = objects.innerProjectionHistory.geometry.attributes.position!;
    const angles = unwrappedAngles(Array.from(
      {length: history.count},
      (_, index) => Math.atan2(history.getY(index), history.getX(index)),
    ));
    const deltas = angles.slice(1).map((angle, index) => angle - angles[index]!);
    expect(deltas.some((delta) => delta < -1e-4)).toBe(true);
    expect(deltas.some((delta) => delta > 1e-4)).toBe(true);
  });

  it.each([
    ['morning', -1],
    ['evening', 1],
  ] as const)(
    'draws the %s maximum-elongation wedge at the orbit tangent',
    (side, expectedOrientation) => {
      const objects = createSequenceSceneGraph(
        'inner-planet-overtake-teaching-model-v1',
        {seed: 9, width: 320, height: 180},
      );
      const runtime = createSequenceRuntime(innerPlanetJob(
        'show-inner-planet-elongation',
        {elongation_side: side},
        1,
      ), objects);

      runtime.renderFrame(0);

      expect(objects.innerSunRay.visible).toBe(true);
      expect(objects.innerElongationRay.visible).toBe(true);
      expect(objects.innerElongationArc.visible).toBe(true);
      const sunToPlanet = objects.innerPlanet.position.clone();
      const planetToEarth = objects.earth.position.clone()
        .sub(objects.innerPlanet.position);
      expect(sunToPlanet.dot(planetToEarth)).toBeCloseTo(0, 6);

      const earthToSun = objects.earth.position.clone().multiplyScalar(-1);
      const earthToPlanet = objects.innerPlanet.position.clone()
        .sub(objects.earth.position);
      expect(earthToSun.angleTo(earthToPlanet)).toBeCloseTo(
        Math.asin(0.72),
        6,
      );
      expect(Math.sign(earthToSun.cross(earthToPlanet).z))
        .toBe(expectedOrientation);
      expect(objects.innerElongationArc.geometry.attributes.position!.count)
        .toBeGreaterThan(2);
    },
  );
});
