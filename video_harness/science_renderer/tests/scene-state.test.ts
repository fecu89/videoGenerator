import {describe, expect, it} from 'vitest';
import * as THREE from 'three';

import {DEFAULT_PHYSICS} from '../src/math/circular-orbit.js';
import {SCENE_REGISTRY, createSceneController} from '../src/scenes/scene-registry.js';
import type {ControllerContext, TemplateName} from '../src/scenes/contracts.js';
import {generateStarPositions} from '../src/visuals/star-field.js';
import {
  createSequenceSceneGraph,
  createSequenceRuntime,
} from '../src/sequences/sequence-registry.js';
import type {SequenceRenderJob} from '../src/render-job.js';
import {
  createSharedScene,
  type SharedSceneObjects,
} from '../src/visuals/solar-system.js';


const TEMPLATE_NAMES = [
  'sky-orbit-reveal',
  'retrograde-track',
  'moving-observer',
  'sightline-angle',
  'speed-comparison',
  'earth-overtake',
  'projection-proof',
  'return-to-direct',
  'same-direction-arrows',
  'local-overtake',
  'cumulative-sightlines',
  'stationary-points',
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


const eclipseContext = (
  objects: SharedSceneObjects,
  template: TemplateName,
): ControllerContext => ({
  objects,
  physics: DEFAULT_PHYSICS,
  simulationDayStart: template === 'node-crossing' ? -15 : 80,
  simulationDayEnd: template === 'node-crossing' ? 15 : 100,
  eclipse: {
    parameters: {
      moon_orbit_inclination_degrees: 5,
      moon_orbit_radius: 2.2,
      sun_distance: 8,
      sun_longitude_degrees: template === 'solar-eclipse-alignment' ? 0 : 90,
      moon_longitude_start_degrees:
        template === 'node-crossing' ? -15 : template === 'solar-eclipse-alignment' ? -6 : 80,
      moon_longitude_end_degrees:
        template === 'node-crossing' ? 15 : template === 'solar-eclipse-alignment' ? 0 : 100,
    },
    rendererOptions: {},
  },
});


const projectBody = (
  objects: SharedSceneObjects,
  body: THREE.Object3D,
): THREE.Vector3 => {
  objects.scene.updateMatrixWorld(true);
  objects.camera.updateMatrixWorld(true);
  objects.camera.updateProjectionMatrix();
  return new THREE.Vector3()
    .setFromMatrixPosition(body.matrixWorld)
    .project(objects.camera);
};


const projectPoint = (
  objects: SharedSceneObjects,
  point: THREE.Vector3,
): THREE.Vector3 => {
  objects.scene.updateMatrixWorld(true);
  objects.camera.updateMatrixWorld(true);
  objects.camera.updateProjectionMatrix();
  return point.clone().project(objects.camera);
};


const expectInsideFrame = (point: THREE.Vector3, margin = 0.95): void => {
  expect(Math.abs(point.x)).toBeLessThan(margin);
  expect(Math.abs(point.y)).toBeLessThan(margin);
  expect(point.z).toBeGreaterThan(-1);
  expect(point.z).toBeLessThan(1);
};


describe('shared scene state', () => {
  it('does not reset Mars group transforms at runtime initialization', () => {
    const objects = createSequenceSceneGraph('mars-retrograde-teaching-model-v2', {
      seed: 7319,
      width: 1920,
      height: 1080,
    });
    objects.orbitGroup.position.set(-1.75, -0.45, 0);
    objects.orbitGroup.scale.setScalar(0.3);
    objects.skyGroup.position.set(1.5, 0.55, 0.1);
    objects.skyGroup.scale.setScalar(0.58);
    const job: SequenceRenderJob = {
      job_kind: 'sequence',
      sequence_id: 'SEQ03',
      scene_graph: 'mars-retrograde-teaching-model-v2',
      canonical_fps: 30,
      duration_frames: 1,
      frame_count: 1,
      output_directory: '/tmp/mars-scene-state',
      output: {width: 1920, height: 1080, fps: 30},
      timeline: [],
      canonical_state_cache: [
        {canonical_frame: 0, active_beat_ids: [], simulation_time: 90},
      ],
      sample_frames: [0],
      style: {seed: 7319, earth_scale: 0.075, mars_scale: 0.055},
    };

    createSequenceRuntime(job, objects);

    expect(objects.orbitGroup.position.toArray()).toEqual([-1.75, -0.45, 0]);
    expect(objects.orbitGroup.scale.toArray()).toEqual([0.3, 0.3, 0.3]);
    expect(objects.skyGroup.position.toArray()).toEqual([1.5, 0.55, 0.1]);
    expect(objects.skyGroup.scale.toArray()).toEqual([0.58, 0.58, 0.58]);
  });

  it('registers every approved Mars template in order', () => {
    expect([...SCENE_REGISTRY.keys()]).toEqual(TEMPLATE_NAMES);
  });

  it('isolates every eclipse template from the legacy Mars orbit group', () => {
    for (const template of TEMPLATE_NAMES.slice(12)) {
      const objects = createSharedScene({seed: 5100, width: 1920, height: 1080});
      const controller = createSceneController(
        template,
        eclipseContext(objects, template),
      );

      controller.update(0.5, 90);

      expect(objects.eclipse.group.visible, template).toBe(true);
      expect(objects.orbitGroup.visible, template).toBe(false);
    }
  });

  it('generates the same fixed stars from the same seed', () => {
    expect(generateStarPositions(220826, 12)).toEqual(
      generateStarPositions(220826, 12),
    );
    expect(generateStarPositions(220826, 12)).not.toEqual(
      generateStarPositions(220827, 12),
    );
  });

  it('keeps physical Mars moving forward during the projection proof', () => {
    const objects = createSharedScene({seed: 220826, width: 1920, height: 1080});
    const controller = createSceneController('projection-proof', {
      objects,
      physics: DEFAULT_PHYSICS,
      simulationDayStart: -35,
      simulationDayEnd: 35,
    });

    controller.update(0.25, -17.5);
    const marsBefore = Math.atan2(objects.mars.position.y, objects.mars.position.x);
    const projectionBefore = Math.atan2(
      objects.projectionMarker.position.y,
      objects.projectionMarker.position.x,
    );
    controller.update(0.75, 17.5);
    const marsAfter = Math.atan2(objects.mars.position.y, objects.mars.position.x);
    const projectionAfter = Math.atan2(
      objects.projectionMarker.position.y,
      objects.projectionMarker.position.x,
    );

    expect(marsAfter).toBeGreaterThan(marsBefore);
    expect(projectionAfter).toBeLessThan(projectionBefore);
  });

  it('moves the projection-proof camera enough to avoid a frozen wide shot', () => {
    const objects = createSharedScene({seed: 220826, width: 1920, height: 1080});
    const controller = createSceneController('projection-proof', {
      objects,
      physics: DEFAULT_PHYSICS,
      simulationDayStart: -35,
      simulationDayEnd: 35,
    });

    controller.update(0.1, -28);
    const before = objects.camera.position.clone();
    controller.update(0.9, 28);

    expect(objects.camera.position.distanceTo(before)).toBeGreaterThan(1);
  });

  it('does not move the seeded star background when controllers update', () => {
    const objects = createSharedScene({seed: 220826, width: 1920, height: 1080});
    const positions = Array.from(objects.stars.geometry.attributes.position!.array);
    const controller = createSceneController('earth-overtake', {
      objects,
      physics: DEFAULT_PHYSICS,
      simulationDayStart: -35,
      simulationDayEnd: 35,
    });

    controller.update(0, -35);
    controller.update(1, 35);

    expect(Array.from(objects.stars.geometry.attributes.position!.array)).toEqual(
      positions,
    );
  });

  it('keeps already plotted sky positions fixed while the retrograde track grows', () => {
    const objects = createSharedScene({seed: 220826, width: 1920, height: 1080});
    const controller = createSceneController('retrograde-track', {
      objects,
      physics: DEFAULT_PHYSICS,
      simulationDayStart: -70,
      simulationDayEnd: 70,
    });

    controller.update(0.5, 0);
    const firstX = objects.skyTrail.geometry.attributes.position!.getX(0);
    controller.update(1, 70);

    expect(objects.skyTrail.geometry.attributes.position!.getX(0)).toBeCloseTo(firstX, 6);
  });

  it('shows direct-retrograde-direct motion as left-right-left on the northern sky', () => {
    const objects = createSharedScene({seed: 220826, width: 1920, height: 1080});
    const controller = createSceneController('retrograde-track', {
      objects,
      physics: DEFAULT_PHYSICS,
      simulationDayStart: -70,
      simulationDayEnd: 70,
    });
    const markerX = (day: number) => {
      controller.update((day + 70) / 140, day);
      return objects.skyMarker.position.x;
    };

    const dayMinus70 = markerX(-70);
    const dayMinus36 = markerX(-36);
    const day0 = markerX(0);
    const day36 = markerX(36);
    const day70 = markerX(70);

    expect(dayMinus36).toBeLessThan(dayMinus70);
    expect(day0).toBeGreaterThan(dayMinus36);
    expect(day36).toBeGreaterThan(day0);
    expect(day70).toBeLessThan(day36);
  });

  it('shows explicit same-direction arrows for both planetary orbits', () => {
    const objects = createSharedScene({seed: 7319, width: 1920, height: 1080});
    const controller = createSceneController('same-direction-arrows', {
      objects,
      physics: DEFAULT_PHYSICS,
      simulationDayStart: -60,
      simulationDayEnd: -30,
    });

    controller.update(0.5, -45);

    expect(objects.earthDirectionArrow.visible).toBe(true);
    expect(objects.marsDirectionArrow.visible).toBe(true);
    expectInsideFrame(projectBody(objects, objects.earth));
    expectInsideFrame(projectBody(objects, objects.mars));
  });

  it('uses a three-quarter camera for the speed comparison', () => {
    const objects = createSharedScene({seed: 7319, width: 1920, height: 1080});
    const controller = createSceneController('speed-comparison', {
      objects,
      physics: DEFAULT_PHYSICS,
      simulationDayStart: -90,
      simulationDayEnd: -25,
    });

    controller.update(0.5, -57.5);

    expect(Math.abs(objects.camera.position.y)).toBeGreaterThan(3);
    expect(objects.camera.position.z).toBeLessThan(4);
  });

  it('frames the local overtake with both planets comfortably visible', () => {
    const objects = createSharedScene({seed: 7319, width: 1920, height: 1080});
    const controller = createSceneController('local-overtake', {
      objects,
      physics: DEFAULT_PHYSICS,
      simulationDayStart: -35,
      simulationDayEnd: 35,
    });

    for (const [progress, day] of [[0, -35], [0.5, 0], [1, 35]] as const) {
      controller.update(progress, day);
      expectInsideFrame(projectBody(objects, objects.earth), 0.82);
      expectInsideFrame(projectBody(objects, objects.mars), 0.82);
    }
    expect(objects.sun.visible).toBe(false);
  });

  it('draws several cumulative sightlines to the fixed star wall', () => {
    const objects = createSharedScene({seed: 7319, width: 1920, height: 1080});
    const controller = createSceneController('cumulative-sightlines', {
      objects,
      physics: DEFAULT_PHYSICS,
      simulationDayStart: -55,
      simulationDayEnd: -20,
    });

    controller.update(1, -20);

    expect(objects.starWall.visible).toBe(true);
    expect(objects.sightlineHistory.visible).toBe(true);
    expect(objects.sightlineHistory.children.filter((child) => child.visible).length)
      .toBeGreaterThanOrEqual(5);
  });

  it('shows two stationary-point rings without replaying a growing track', () => {
    const objects = createSharedScene({seed: 7319, width: 1920, height: 1080});
    const controller = createSceneController('stationary-points', {
      objects,
      physics: DEFAULT_PHYSICS,
      simulationDayStart: -70,
      simulationDayEnd: 70,
    });

    controller.update(0, -70);
    const initialCount = objects.skyTrail.geometry.attributes.position!.count;
    controller.update(1, 70);

    expect(objects.stationMarkerStart.visible).toBe(true);
    expect(objects.stationMarkerEnd.visible).toBe(true);
    expect(objects.skyTrail.geometry.attributes.position!.count).toBe(initialCount);
    expect(initialCount).toBeGreaterThanOrEqual(48);
  });

  it('moves the camera from the first stationary point to the second', () => {
    const objects = createSharedScene({seed: 7319, width: 1920, height: 1080});
    const controller = createSceneController('stationary-points', {
      objects,
      physics: DEFAULT_PHYSICS,
      simulationDayStart: -70,
      simulationDayEnd: 70,
    });

    controller.update(0, -70);
    const firstTargetPosition = objects.camera.position.clone();
    controller.update(1, 70);

    expect(objects.camera.position.distanceTo(firstTargetPosition)).toBeGreaterThan(1);
  });

  it('leaves the sky repeat quickly during the sky-to-orbit reveal', () => {
    const objects = createSharedScene({seed: 7319, width: 1920, height: 1080});
    const controller = createSceneController('sky-orbit-reveal', {
      objects,
      physics: DEFAULT_PHYSICS,
      simulationDayStart: -70,
      simulationDayEnd: 20,
    });

    controller.update(0.2, -52);

    expect(objects.orbitGroup.visible).toBe(true);
    expect(objects.skyGroup.visible).toBe(false);
  });

  it('combines the physical orbit and apparent sky track in the payoff', () => {
    const objects = createSharedScene({seed: 7319, width: 1920, height: 1080});
    const controller = createSceneController('return-to-direct', {
      objects,
      physics: DEFAULT_PHYSICS,
      simulationDayStart: 35,
      simulationDayEnd: 75,
    });

    controller.update(0.5, 55);

    expect(objects.orbitGroup.visible).toBe(true);
    expect(objects.skyGroup.visible).toBe(true);
    expect(objects.projectionHistory.visible).toBe(true);
  });

  it('keeps the off-season new-Moon shadow above Earth', () => {
    const objects = createSharedScene({seed: 5104, width: 1920, height: 1080});
    const controller = createSceneController(
      'new-moon-miss' as TemplateName,
      eclipseContext(objects, 'new-moon-miss' as TemplateName),
    );

    controller.update(0.5, 90);

    const eclipse = (
      objects as SharedSceneObjects & {
        eclipse?: {
          moon: {position: {z: number}};
          moonShadow: {geometry: {attributes: {position?: {getZ(index: number): number}}}};
        };
      }
    ).eclipse;
    expect(eclipse).toBeDefined();
    if (!eclipse) return;
    expect(eclipse.moon.position.z).toBeGreaterThan(0.19);
    expect(eclipse.moonShadow.geometry.attributes.position!.getZ(1)).toBeGreaterThan(
      0.19,
    );
    expect(objects.eclipse.earth.scale.x).toBeLessThanOrEqual(0.55);
    expect(objects.eclipse.moon.scale.x).toBeLessThanOrEqual(0.7);

    const positions = objects.eclipse.moonShadow.geometry.attributes.position!;
    const start = new THREE.Vector3(
      positions.getX(0),
      positions.getY(0),
      positions.getZ(0),
    );
    const end = new THREE.Vector3(
      positions.getX(1),
      positions.getY(1),
      positions.getZ(1),
    );
    const atEarthPlane = start.clone().lerp(end, -start.y / (end.y - start.y));
    const earthScreen = projectBody(objects, objects.eclipse.earth);
    const shadowScreen = projectPoint(objects, atEarthPlane);
    expect(shadowScreen.y - earthScreen.y).toBeGreaterThan(0.045);
  });

  it('shows the full Moon below the Earth-shadow axis outside eclipse season', () => {
    const objects = createSharedScene({seed: 5105, width: 1920, height: 1080});
    const context = eclipseContext(objects, 'full-moon-miss' as TemplateName);
    context.simulationDayStart = 260;
    context.simulationDayEnd = 280;
    context.eclipse!.parameters.moon_longitude_start_degrees = 260;
    context.eclipse!.parameters.moon_longitude_end_degrees = 280;
    const controller = createSceneController('full-moon-miss', context);

    controller.update(0.5, 270);

    const moonScreen = projectBody(objects, objects.eclipse.moon);
    const axisScreen = projectPoint(
      objects,
      new THREE.Vector3(objects.eclipse.moon.position.x, objects.eclipse.moon.position.y, 0),
    );
    expect(objects.eclipse.earth.scale.x).toBeLessThanOrEqual(0.55);
    expect(objects.eclipse.moon.scale.x).toBeLessThanOrEqual(0.7);
    expect(axisScreen.y - moonScreen.y).toBeGreaterThan(0.045);
  });

  it('puts the Moon exactly on the ecliptic while it crosses a node', () => {
    const objects = createSharedScene({seed: 5106, width: 1920, height: 1080});
    const controller = createSceneController(
      'node-crossing' as TemplateName,
      eclipseContext(objects, 'node-crossing' as TemplateName),
    );

    controller.update(0.5, 0);

    const eclipse = (
      objects as SharedSceneObjects & {eclipse?: {moon: {position: {z: number}}}}
    ).eclipse;
    expect(eclipse).toBeDefined();
    if (!eclipse) return;
    expect(eclipse.moon.position.z).toBeCloseTo(0, 12);
  });

  it('keeps the Sun Moon and Earth inside the solar-eclipse frame in that order', () => {
    const objects = createSharedScene({seed: 5107, width: 1920, height: 1080});
    const controller = createSceneController(
      'solar-eclipse-alignment' as TemplateName,
      eclipseContext(objects, 'solar-eclipse-alignment' as TemplateName),
    );

    controller.update(1, 0);
    const eclipse = objects.eclipse;
    const screen = [eclipse.sun, eclipse.moon, eclipse.earth].map((body) =>
      projectBody(objects, body),
    );

    for (const point of screen) {
      expectInsideFrame(point);
    }
    expect(screen[0]!.x).toBeGreaterThan(screen[1]!.x);
    expect(screen[1]!.x).toBeGreaterThan(screen[2]!.x);
  });

  it('uses a readable teaching scale for the Moon without changing its orbit', () => {
    const objects = createSharedScene({seed: 5107, width: 1920, height: 1080});
    const earthGeometry = objects.eclipse.earth.geometry as THREE.SphereGeometry;
    const moonGeometry = objects.eclipse.moon.geometry as THREE.SphereGeometry;
    earthGeometry.computeBoundingSphere();
    moonGeometry.computeBoundingSphere();

    const earthRadius = earthGeometry.boundingSphere!.radius;
    const moonRadius = moonGeometry.boundingSphere!.radius;

    expect(moonRadius / earthRadius).toBeGreaterThanOrEqual(0.5);
    expect(objects.eclipse.moon.position.length()).toBeCloseTo(0, 12);
  });

  it('shows a filled umbra cone when the solar-eclipse alignment reaches Earth', () => {
    const objects = createSharedScene({seed: 5107, width: 1920, height: 1080});
    const controller = createSceneController(
      'solar-eclipse-alignment' as TemplateName,
      eclipseContext(objects, 'solar-eclipse-alignment' as TemplateName),
    );

    controller.update(1, 0);

    expect(objects.eclipse.moonUmbraFill.visible).toBe(true);
    expect(objects.eclipse.moonUmbraFill.scale.y).toBeGreaterThan(3);
    expect(objects.eclipse.shadowHitMarker.visible).toBe(true);
  });

  it('keeps the Sun Earth and Moon visible in the top-view explanation', () => {
    const objects = createSharedScene({seed: 5102, width: 1920, height: 1080});
    const controller = createSceneController(
      'top-view-alignment' as TemplateName,
      eclipseContext(objects, 'top-view-alignment' as TemplateName),
    );

    controller.update(0.5, 90);

    for (const body of [objects.eclipse.sun, objects.eclipse.earth, objects.eclipse.moon]) {
      expectInsideFrame(projectBody(objects, body), 0.82);
    }
  });

  it('keeps the Sun Earth and Moon visible in lunar-eclipse order', () => {
    const objects = createSharedScene({seed: 5108, width: 1920, height: 1080});
    const context = eclipseContext(objects, 'lunar-eclipse-alignment' as TemplateName);
    context.simulationDayStart = 174;
    context.simulationDayEnd = 180;
    context.eclipse!.parameters.moon_longitude_start_degrees = 174;
    context.eclipse!.parameters.moon_longitude_end_degrees = 180;
    context.eclipse!.parameters.sun_longitude_degrees = 0;
    const controller = createSceneController('lunar-eclipse-alignment', context);

    controller.update(1, 180);
    const screen = [objects.eclipse.sun, objects.eclipse.earth, objects.eclipse.moon].map(
      (body) => projectBody(objects, body),
    );

    for (const point of screen) expectInsideFrame(point, 0.9);
    expect(screen[0]!.x).toBeGreaterThan(screen[1]!.x);
    expect(screen[1]!.x).toBeGreaterThan(screen[2]!.x);
  });

  it('keeps both endpoints of the two-condition summary comfortably framed', () => {
    const objects = createSharedScene({seed: 5109, width: 1920, height: 1080});
    const context = eclipseContext(objects, 'two-condition-summary' as TemplateName);
    context.eclipse!.parameters.sun_longitude_start_degrees = 90;
    context.eclipse!.parameters.sun_longitude_end_degrees = 0;
    const controller = createSceneController('two-condition-summary', context);

    for (const [progress, day] of [[0, 90], [1, 0]] as const) {
      controller.update(progress, day);
      for (const body of [objects.eclipse.sun, objects.eclipse.earth, objects.eclipse.moon]) {
        expectInsideFrame(projectBody(objects, body), 0.82);
      }
    }
  });
});
