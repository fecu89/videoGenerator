import {describe, expect, it} from 'vitest';
import * as THREE from 'three';

import type {SequenceRenderJob} from '../src/render-job.js';
import {
  createSequenceRuntime,
  createSequenceSceneGraph,
} from '../src/sequences/sequence-registry.js';


const CONTROLLERS = [
  'monthly-cycle-hook',
  'top-view-alignment',
  'tilt-reveal',
  'new-moon-miss',
  'full-moon-miss',
  'node-crossing',
  'solar-eclipse-alignment',
  'lunar-eclipse-alignment',
  'two-condition-summary',
] as const;


const angularSeparationFromCamera = (
  camera: THREE.PerspectiveCamera,
  left: THREE.Vector3,
  right: THREE.Vector3,
): number => left.clone().sub(camera.position).angleTo(
  right.clone().sub(camera.position),
);


const sequenceJob = (
  controller: string,
  controllerOptions: Record<string, unknown> = {},
  durationFrames = 1,
): SequenceRenderJob => ({
  job_kind: 'sequence',
  sequence_id: 'SEQ01',
  scene_graph: 'sun-earth-moon-eclipse-teaching-model-v1',
  canonical_fps: 30,
  duration_frames: durationFrames,
  frame_count: durationFrames,
  output_directory: '/tmp/eclipse-sequence-test',
  output: {width: 320, height: 180, fps: 30},
  timeline: [{
    beat_id: 'B01',
    start_frame: 0,
    end_frame: durationFrames,
    simulation_time_start: 0,
    simulation_time_end: 0,
    controller,
    patch_targets: ['geometry', 'layers', 'camera', 'hide_events'],
    priority: 0,
    controller_options: {
      moon_orbit_inclination_degrees: 5,
      moon_orbit_radius: 2.2,
      sun_distance: 8,
      sun_longitude_degrees: controller === 'solar-eclipse-alignment'
        || controller === 'lunar-eclipse-alignment' ? 0 : 90,
      moon_longitude_degrees: 90,
      sun_longitude_start_degrees: 90,
      sun_longitude_end_degrees: 0,
      ...controllerOptions,
    },
  }],
  canonical_state_cache: Array.from({length: durationFrames}, (_, frame) => ({
    canonical_frame: frame,
    active_beat_ids: ['B01'],
    simulation_time: frame,
  })),
  sample_frames: [0, durationFrames - 1],
  style: {
    seed: 220829,
    earth_scale: 1,
    moon_scale: 1,
    sun_scale: 1,
  },
});


describe('Sun Earth Moon eclipse sequence', () => {
  it('keeps the eclipse Earth visible when the orbital Earth uses its small scale', () => {
    const objects = createSequenceSceneGraph(
      'sun-earth-moon-eclipse-teaching-model-v1',
      {seed: 220829, width: 320, height: 180, earthScale: 0.075},
    );
    objects.earth.geometry.computeBoundingSphere();
    objects.eclipse.earth.geometry.computeBoundingSphere();

    expect(objects.earth.geometry.boundingSphere!.radius).toBeCloseTo(0.075, 6);
    expect(objects.eclipse.earth.geometry.boundingSphere!.radius).toBeCloseTo(0.23, 6);
  });

  it.each(CONTROLLERS)(
    'renders %s through the continuous sequence runtime',
    (controller) => {
      const objects = createSequenceSceneGraph(
        'sun-earth-moon-eclipse-teaching-model-v1',
        {seed: 220829, width: 320, height: 180},
      );
      const runtime = createSequenceRuntime(sequenceJob(controller), objects);

      runtime.renderFrame(0);

      expect(objects.eclipse.group.visible).toBe(true);
      expect(objects.orbitGroup.visible).toBe(false);
      expect(runtime.stateSnapshot().geometry_operation_keys).toEqual([
        `eclipse-${controller}`,
      ]);
      expect(runtime.stateSnapshot().camera.position).not.toEqual([0, 0, 5.2]);
    },
  );

  it('pushes into Earth while the umbra and penumbra track across its surface', () => {
    const objects = createSequenceSceneGraph(
      'sun-earth-moon-eclipse-teaching-model-v1',
      {seed: 220829, width: 320, height: 180},
    );
    const runtime = createSequenceRuntime(sequenceJob(
      'solar-eclipse-alignment',
      {view_mode: 'earth_close_shadow_track'},
      3,
    ), objects);

    runtime.renderFrame(0);
    const startCameraDistance = objects.camera.position.distanceTo(
      objects.eclipse.earth.position,
    );
    const umbra = objects.eclipse.group.getObjectByName('earth-umbra-spot');
    const penumbra = objects.eclipse.group.getObjectByName('earth-penumbra-spot');
    expect(umbra?.visible).toBe(true);
    expect(penumbra?.visible).toBe(true);
    const startShadowY = umbra!.position.y;

    runtime.renderFrame(2);

    expect(objects.eclipse.sun.visible).toBe(false);
    expect(objects.camera.position.distanceTo(objects.eclipse.earth.position))
      .toBeLessThan(startCameraDistance);
    expect(objects.camera.position.x).toBeGreaterThan(
      Math.abs(objects.camera.position.y),
    );
    expect(umbra!.position.y).toBeGreaterThan(startShadowY);
    expect(penumbra!.scale.x).toBeGreaterThan(umbra!.scale.x);
    expect(Math.abs(umbra!.position.y)).toBeLessThanOrEqual(0.08);
    expect(penumbra!.scale.x).toBeLessThanOrEqual(0.11);
    expect(objects.eclipse.shadowHitMarker.visible).toBe(false);
  });

  it('renders distinct widening penumbra volumes in both wide eclipse alignments', () => {
    for (const controller of [
      'solar-eclipse-alignment',
      'lunar-eclipse-alignment',
    ]) {
      const objects = createSequenceSceneGraph(
        'sun-earth-moon-eclipse-teaching-model-v1',
        {seed: 220829, width: 320, height: 180},
      );
      const runtime = createSequenceRuntime(sequenceJob(
        controller,
        {view_mode: 'wide_alignment', sun_longitude_degrees: 0},
        3,
      ), objects);

      runtime.renderFrame(2);

      const prefix = controller.startsWith('solar') ? 'moon' : 'earth';
      const outline = objects.eclipse.group.getObjectByName(
        `${prefix}-penumbra-outline`,
      ) as THREE.LineSegments | undefined;
      expect(outline?.visible).toBe(true);
      expect(objects.eclipse.group.getObjectByName(
        `${prefix}-penumbra-fill`,
      )?.visible).toBe(true);
      const positions = outline!.geometry.attributes.position!;
      const startWidth = new THREE.Vector3().fromBufferAttribute(positions, 0)
        .distanceTo(new THREE.Vector3().fromBufferAttribute(positions, 2));
      const endWidth = new THREE.Vector3().fromBufferAttribute(positions, 1)
        .distanceTo(new THREE.Vector3().fromBufferAttribute(positions, 3));
      expect(endWidth).toBeGreaterThan(startWidth);
    }
  });

  it('reveals the summary penumbra only with the rest of the shadow geometry', () => {
    const objects = createSequenceSceneGraph(
      'sun-earth-moon-eclipse-teaching-model-v1',
      {seed: 220829, width: 320, height: 180},
    );
    const runtime = createSequenceRuntime(sequenceJob(
      'two-condition-summary',
      {},
      3,
    ), objects);

    runtime.renderFrame(0);
    expect(objects.eclipse.moonUmbra.visible).toBe(false);
    expect(objects.eclipse.moonPenumbra.visible).toBe(false);
    expect(objects.eclipse.moonPenumbraFill.visible).toBe(false);

    runtime.renderFrame(2);
    expect(objects.eclipse.moonUmbra.visible).toBe(true);
    expect(objects.eclipse.moonPenumbra.visible).toBe(true);
    expect(objects.eclipse.moonPenumbraFill.visible).toBe(true);
  });

  it('moves from the top-view scale comparison into the Earth sightline', () => {
    const objects = createSequenceSceneGraph(
      'sun-earth-moon-eclipse-teaching-model-v1',
      {seed: 220829, width: 320, height: 180},
    );
    const runtime = createSequenceRuntime(sequenceJob(
      'top-view-alignment',
      {view_mode: 'scale_to_apparent_size', sun_longitude_degrees: 90},
      11,
    ), objects);

    runtime.renderFrame(0);
    const topViewZ = objects.camera.position.z;
    runtime.renderFrame(9);

    expect(objects.eclipse.earth.visible).toBe(false);
    expect(objects.eclipse.moon.position.x).toBeCloseTo(0, 6);
    expect(objects.eclipse.moon.position.y).toBeGreaterThan(0);
    expect(objects.camera.position.z).toBeLessThan(topViewZ);
    expect(objects.camera.userData.sequenceTarget).toEqual([0, 8, 0]);
    expect(objects.camera.fov).toBeLessThanOrEqual(12);
    expect(angularSeparationFromCamera(
      objects.camera,
      objects.eclipse.moon.position,
      objects.eclipse.sun.position,
    )).toBeLessThan(0.006);
  });

  it('reveals a mildly eccentric lunar orbit and moves the Moon toward apogee', () => {
    const objects = createSequenceSceneGraph(
      'sun-earth-moon-eclipse-teaching-model-v1',
      {seed: 220829, width: 320, height: 180},
    );
    const runtime = createSequenceRuntime(sequenceJob(
      'solar-eclipse-alignment',
      {
        view_mode: 'moon_orbit_distance_reveal',
        moon_orbit_eccentricity: 0.0549,
        distance_difference_visual_emphasis: 1.5,
      },
      5,
    ), objects);

    runtime.renderFrame(0);
    const startMoonDistance = objects.eclipse.moon.position.length();
    const startApparentMoonRadius = 0.12 / startMoonDistance;
    const startCamera = objects.camera.position.clone();
    const positions = objects.eclipse.moonOrbit.geometry.attributes.position;
    expect(positions).toBeDefined();
    const xValues = Array.from(
      {length: positions!.count},
      (_, index) => positions!.getX(index),
    );
    expect(Math.max(...xValues)).toBeGreaterThan(Math.abs(Math.min(...xValues)));

    runtime.renderFrame(4);

    expect(objects.eclipse.moonOrbit.visible).toBe(false);
    expect(objects.eclipse.sun.visible).toBe(true);
    expect(objects.eclipse.moon.position.length()).toBeGreaterThan(startMoonDistance);
    expect(objects.eclipse.moon.scale.x).toBe(1);
    expect(objects.camera.position.distanceTo(startCamera)).toBeGreaterThan(1);
    expect(0.12 / objects.eclipse.moon.position.length())
      .toBeLessThan(startApparentMoonRadius);
    const target = new THREE.Vector3(...objects.camera.userData.sequenceTarget);
    expect(objects.camera.userData.sequenceTarget).toEqual([8, 0, 0]);
    expect(angularSeparationFromCamera(
      objects.camera,
      objects.eclipse.moon.position,
      target,
    )).toBeLessThan(THREE.MathUtils.degToRad(objects.camera.fov / 2));
    const moonSunSeparation = angularSeparationFromCamera(
      objects.camera,
      objects.eclipse.moon.position,
      objects.eclipse.sun.position,
    );
    expect(moonSunSeparation).toBeGreaterThan(0.01);
    const halfVerticalFov = THREE.MathUtils.degToRad(objects.camera.fov / 2);
    expect(moonSunSeparation + 0.12 / objects.camera.position.distanceTo(
      objects.eclipse.moon.position,
    )).toBeLessThan(halfVerticalFov);
    expect(0.48 / objects.camera.position.distanceTo(objects.eclipse.sun.position))
      .toBeLessThan(halfVerticalFov);
  });

  it('finishes the annular eclipse from an Earth-observer sightline', () => {
    const objects = createSequenceSceneGraph(
      'sun-earth-moon-eclipse-teaching-model-v1',
      {seed: 220829, width: 320, height: 180},
    );
    const runtime = createSequenceRuntime(sequenceJob(
      'solar-eclipse-alignment',
      {
        view_mode: 'observer_annular_close',
        moon_orbit_eccentricity: 0.0549,
      },
      3,
    ), objects);

    runtime.renderFrame(0);
    const startFov = objects.camera.fov;
    runtime.renderFrame(2);

    expect(objects.eclipse.earth.visible).toBe(false);
    expect(objects.eclipse.sun.visible).toBe(true);
    expect(objects.eclipse.moon.visible).toBe(true);
    expect(objects.camera.userData.sequenceTarget).toEqual([8, 0, 0]);
    expect(objects.camera.fov).toBeLessThanOrEqual(10);
    expect(objects.camera.fov).toBeLessThan(startFov);
    const sunAngularRadius = 0.48 / objects.camera.position.distanceTo(
      objects.eclipse.sun.position,
    );
    const moonAngularRadius = 0.12 / objects.camera.position.distanceTo(
      objects.eclipse.moon.position,
    );
    expect(moonAngularRadius).toBeLessThan(sunAngularRadius);
    expect(angularSeparationFromCamera(
      objects.camera,
      objects.eclipse.moon.position,
      objects.eclipse.sun.position,
    )).toBeLessThan(0.001);
  });

  it('tracks the Moon into Earth shadow, then reveals the night-side context', () => {
    const entryObjects = createSequenceSceneGraph(
      'sun-earth-moon-eclipse-teaching-model-v1',
      {seed: 220829, width: 320, height: 180},
    );
    const entryRuntime = createSequenceRuntime(sequenceJob(
      'lunar-eclipse-alignment',
      {view_mode: 'moon_close_shadow_entry', sun_longitude_degrees: 0},
      5,
    ), entryObjects);
    const entryMaterial = entryObjects.eclipse.moon.material as THREE.MeshStandardMaterial;

    entryRuntime.renderFrame(0);
    expect(entryObjects.camera.position.distanceTo(entryObjects.eclipse.moon.position))
      .toBeGreaterThan(10);
    const startColor = entryMaterial.color.getHex();
    expect(Math.abs(entryObjects.eclipse.moon.position.y)).toBeGreaterThan(0.47);

    entryRuntime.renderFrame(2);
    expect(Math.abs(entryObjects.eclipse.moon.position.y)).toBeLessThan(0.3);
    expect(entryMaterial.color.getHex()).not.toBe(startColor);

    entryRuntime.renderFrame(4);

    expect(entryObjects.eclipse.sun.visible).toBe(false);
    expect(entryObjects.eclipse.earthUmbraFill.visible).toBe(true);
    expect(entryMaterial.color.getHex()).not.toBe(startColor);
    expect(entryObjects.camera.fov).toBeLessThanOrEqual(16);

    const bloodObjects = createSequenceSceneGraph(
      'sun-earth-moon-eclipse-teaching-model-v1',
      {seed: 220829, width: 320, height: 180},
    );
    const bloodRuntime = createSequenceRuntime(sequenceJob(
      'lunar-eclipse-alignment',
      {view_mode: 'blood_moon_close_to_night_side'},
      3,
    ), bloodObjects);

    bloodRuntime.renderFrame(0);
    const closeDistance = bloodObjects.camera.position.distanceTo(
      bloodObjects.eclipse.moon.position,
    );
    bloodRuntime.renderFrame(2);

    const bloodMaterial = bloodObjects.eclipse.moon.material as THREE.MeshStandardMaterial;
    expect(bloodMaterial.color.r).toBeGreaterThan(bloodMaterial.color.b);
    expect(bloodObjects.camera.position.distanceTo(bloodObjects.eclipse.moon.position))
      .toBeGreaterThan(closeDistance);
    expect(bloodObjects.eclipse.earth.visible).toBe(true);
  });
});
