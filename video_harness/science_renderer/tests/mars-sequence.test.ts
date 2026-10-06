import {describe, expect, it} from 'vitest';
import * as THREE from 'three';

import {DEFAULT_PHYSICS, orbitPosition} from '../src/math/circular-orbit.js';
import {findRetrogradeWindow} from '../src/math/retrograde.js';
import type {
  SequenceRenderJob,
  SequenceTimelineItem,
} from '../src/render-job.js';
import {
  applyMergedPatch,
  applyPersistentEvents,
  createSequenceState,
  mergeSequencePatches,
  type SequenceControllerContext,
  type SequencePatch,
} from '../src/sequences/contracts.js';
import {
  SEQUENCE_CONTROLLER_REGISTRY,
  createSequenceSceneGraph,
  createSequenceRuntime,
} from '../src/sequences/sequence-registry.js';
import {skyTrackPosition} from '../src/scenes/contracts.js';
import {createSharedScene} from '../src/visuals/solar-system.js';


const MARS_CONTROLLER_NAMES = [
  'grow-sky-track',
  'hold-completed-track',
  'continuous-sky-to-orbit-pullback',
  'show-same-direction-arrows',
  'grow-speed-trails',
  'track-local-overtake',
  'grow-cumulative-sightlines',
  'grow-projection-history',
  'mark-stationary-points',
  'add-solar-system-inset',
] as const;


const contextAt = (
  progress: number,
  overrides: Partial<SequenceControllerContext> = {},
): SequenceControllerContext => ({
  canonicalFrame: Math.round(progress * 100),
  simulationDay: -70 + progress * 140,
  progress,
  timelineItem: {
    beat_id: 'B01',
    start_frame: 0,
    end_frame: 101,
    simulation_time_start: -70,
    simulation_time_end: 70,
    controller: 'grow-sky-track',
    patch_targets: ['geometry', 'layers', 'camera'],
    priority: 0,
    controller_options: {},
  },
  controllerOptions: {},
  ...overrides,
});


const sampleMarsController = (
  name: typeof MARS_CONTROLLER_NAMES[number],
  context: SequenceControllerContext,
): SequencePatch => {
  const controller = SEQUENCE_CONTROLLER_REGISTRY.get(name);
  if (!controller) throw new Error(`missing Mars controller: ${name}`);
  return controller.sample(context);
};


const middleSequenceFixture = (): {timeline: SequenceTimelineItem[]} => ({
  timeline: [
    [-90, -70, 'show-same-direction-arrows'],
    [-70, -40, 'grow-speed-trails'],
    [-40, 20, 'track-local-overtake'],
    [20, 30, 'grow-cumulative-sightlines'],
    [30, 55, 'grow-projection-history'],
  ].map(([start, end, controller], index) => ({
    beat_id: `B0${index + 4}`,
    start_frame: index * 100,
    end_frame: (index + 1) * 100,
    simulation_time_start: start as number,
    simulation_time_end: end as number,
    controller: controller as string,
    patch_targets: ['simulation_clock', 'geometry', 'layers'],
    priority: 0,
    controller_options: {},
  })),
});


const skyTrailCoordinates = (
  objects: ReturnType<typeof createSharedScene>,
): number[] => Array.from(objects.skyTrail.geometry.attributes.position!.array);


const coordinateExtent = (coordinates: readonly number[]): number => {
  const xCoordinates = coordinates.filter((_, index) => index % 3 === 0);
  return Math.max(...xCoordinates) - Math.min(...xCoordinates);
};


const seq01DraftBoundaryJob = (): SequenceRenderJob => {
  const timeline: SequenceTimelineItem[] = [
    {
      beat_id: 'B01',
      start_frame: 0,
      end_frame: 184,
      simulation_time_start: -70,
      simulation_time_end: 70,
      controller: 'grow-sky-track',
      patch_targets: ['geometry', 'layers', 'camera', 'hide_events'],
      priority: 0,
      controller_options: {},
    },
    {
      beat_id: 'B02',
      start_frame: 184,
      end_frame: 188,
      simulation_time_start: 70,
      simulation_time_end: 70,
      controller: 'hold-completed-track',
      patch_targets: ['geometry', 'layers', 'camera'],
      priority: 0,
      controller_options: {evidence_start_day: -70, evidence_end_day: 70},
      hold_intent: 'Preserve the completed apparent track during silence.',
    },
    {
      beat_id: 'B03',
      start_frame: 188,
      end_frame: 393,
      simulation_time_start: 70,
      simulation_time_end: 90,
      controller: 'continuous-sky-to-orbit-pullback',
      patch_targets: ['geometry', 'layers', 'camera', 'hide_events'],
      priority: 0,
      controller_options: {},
    },
  ];
  const simulationTime = (frame: number, beat: SequenceTimelineItem): number => {
    const progress = (frame - beat.start_frame)
      / Math.max(1, beat.end_frame - beat.start_frame - 1);
    return beat.simulation_time_start
      + (beat.simulation_time_end - beat.simulation_time_start) * progress;
  };
  return {
    job_kind: 'sequence',
    sequence_id: 'SEQ01',
    scene_graph: 'mars-retrograde-teaching-model-v2',
    canonical_fps: 30,
    duration_frames: 393,
    frame_count: 197,
    output_directory: '/tmp/mars-seq01-draft-boundary',
    output: {width: 320, height: 180, fps: 15},
    timeline,
    canonical_state_cache: Array.from({length: 393}, (_, canonicalFrame) => {
      const beat = timeline.find((item) =>
        canonicalFrame >= item.start_frame && canonicalFrame < item.end_frame,
      )!;
      return {
        canonical_frame: canonicalFrame,
        active_beat_ids: [beat.beat_id],
        simulation_time: simulationTime(canonicalFrame, beat),
      };
    }),
    sample_frames: [91, 92, 94],
    style: {seed: 7319, earth_scale: 0.075, mars_scale: 0.055},
  };
};


describe('continuous Mars retrograde controllers', () => {
  it('registers exactly the ten approved Mars controller names', () => {
    expect(
      MARS_CONTROLLER_NAMES.filter((name) =>
        SEQUENCE_CONTROLLER_REGISTRY.has(name),
      ),
    ).toEqual(MARS_CONTROLLER_NAMES);
  });

  it('removes the completed sky frame when the orbit scene starts', () => {
    const grow = sampleMarsController('grow-sky-track', contextAt(0.99));
    const pullback = sampleMarsController(
      'continuous-sky-to-orbit-pullback',
      contextAt(0.01),
    );
    const state = createSequenceState();
    applyPersistentEvents(state, grow);
    applyPersistentEvents(state, pullback);
    expect(state.visibleLayers.has('skyGroup')).toBe(false);
    expect(state.visibleLayers.has('skyTrail')).toBe(false);
    expect(state.visibleLayers.has('skyMarker')).toBe(false);
  });

  it('adds projection history without hiding accumulated sightlines', () => {
    const sightlines = sampleMarsController(
      'grow-cumulative-sightlines',
      contextAt(1, {
        controllerOptions: {evidence_start_day: -55, evidence_end_day: -20},
      }),
    );
    const projection = sampleMarsController(
      'grow-projection-history',
      contextAt(0, {
        controllerOptions: {evidence_start_day: -55, evidence_end_day: 35},
      }),
    );
    expect(sightlines.showLayers).toContain('sightlineHistory');
    expect(projection.hideLayers ?? []).not.toContain('sightlineHistory');
  });

  it('uses forward-only physical time for the middle sequence', () => {
    const times = middleSequenceFixture().timeline.flatMap((beat) => [
      beat.simulation_time_start,
      beat.simulation_time_end,
    ]);
    expect(times).toEqual(times.slice().sort((a, b) => a - b));
  });

  it('separates earlier sightline evidence from the forward physical day', () => {
    const patch = sampleMarsController('grow-cumulative-sightlines', contextAt(1, {
      simulationDay: 30,
      timelineItem: {
        ...contextAt(1).timelineItem,
        simulation_time_start: 20,
        simulation_time_end: 30,
        controller: 'grow-cumulative-sightlines',
      },
      controllerOptions: {evidence_start_day: -55, evidence_end_day: -20},
    }));

    expect(patch.simulationDay).toBeUndefined();
    expect(patch.geometryOperations).toEqual([
      {kind: 'orbit_and_sightline', key: 'physical-sightline', day: 30,
        extendToProjection: true},
      {kind: 'cumulative_sightlines', key: 'sightline-evidence',
        startDay: -55, endDay: -20, revealedCount: 6},
    ]);
  });

  it('keeps a fixed cumulative evidence range while revealing a prefix', () => {
    const options = {evidence_start_day: -55, evidence_end_day: -20};
    const atStart = sampleMarsController('grow-cumulative-sightlines', contextAt(0, {
      simulationDay: 20,
      controllerOptions: options,
    }));
    const atEnd = sampleMarsController('grow-cumulative-sightlines', contextAt(1, {
      simulationDay: 30,
      controllerOptions: options,
    }));
    const startEvidence = atStart.geometryOperations?.find(
      (operation) => operation.kind === 'cumulative_sightlines',
    );
    const endEvidence = atEnd.geometryOperations?.find(
      (operation) => operation.kind === 'cumulative_sightlines',
    );

    expect(startEvidence).toEqual({
      kind: 'cumulative_sightlines',
      key: 'sightline-evidence',
      startDay: -55,
      endDay: -20,
      revealedCount: 1,
    });
    expect(endEvidence).toEqual({
      kind: 'cumulative_sightlines',
      key: 'sightline-evidence',
      startDay: -55,
      endDay: -20,
      revealedCount: 6,
    });
  });

  it('reveals more fixed sightlines without moving earlier endpoints', () => {
    const objects = createSharedScene({seed: 7319, width: 1920, height: 1080});
    const state = createSequenceState();
    const options = {evidence_start_day: -55, evidence_end_day: -20};
    const visibleLines = (): THREE.Line[] => objects.sightlineHistory.children
      .filter((child) => child.visible) as THREE.Line[];
    const endpoints = (): number[][] => visibleLines().map((line) =>
      Array.from(line.geometry.attributes.position!.array),
    );

    for (const [progress, expectedCount] of [[0, 1], [0.5, 3], [1, 6]] as const) {
      const before = endpoints();
      const patch = sampleMarsController('grow-cumulative-sightlines', contextAt(
        progress,
        {simulationDay: 20 + progress * 10, controllerOptions: options},
      ));
      applyMergedPatch(
        objects,
        state,
        mergeSequencePatches(20 + progress * 10, [patch]),
        DEFAULT_PHYSICS,
      );

      expect(visibleLines()).toHaveLength(expectedCount);
      expect(endpoints().slice(0, before.length)).toEqual(before);
    }
  });

  it('keeps the completed track geometry but hides it at the next scene boundary', () => {
    const objects = createSequenceSceneGraph('mars-retrograde-teaching-model-v2', {
      seed: 7319,
      width: 320,
      height: 180,
    });
    const runtime = createSequenceRuntime(seq01DraftBoundaryJob(), objects);

    runtime.renderFrame(91); // canonical 182, the last sampled B01 draft frame
    const growing = skyTrailCoordinates(objects);
    runtime.renderFrame(92); // canonical 184, first B02 frame; canonical 183 is skipped
    const held = skyTrailCoordinates(objects);
    runtime.renderFrame(94); // canonical 188, first B03 frame
    const pullback = skyTrailCoordinates(objects);

    expect(new Set(held.map((value) => value.toFixed(8))).size).toBeGreaterThan(8);
    expect(coordinateExtent(held)).toBeGreaterThanOrEqual(
      coordinateExtent(growing) * 0.98,
    );
    expect(pullback).toEqual(held);
    expect(objects.skyGroup.visible).toBe(false);
    expect(objects.skyTrail.visible).toBe(false);
    expect(objects.skyMarker.visible).toBe(false);
  });

  it.each([
    ['missing', {}],
    ['start only', {evidence_start_day: -55}],
    ['end only', {evidence_end_day: -20}],
    ['string', {evidence_start_day: -55, evidence_end_day: 'bad'}],
    ['NaN', {evidence_start_day: -55, evidence_end_day: Number.NaN}],
    ['infinity', {evidence_start_day: -55, evidence_end_day: Number.POSITIVE_INFINITY}],
  ])('rejects %s historical evidence options', (_label, controllerOptions) => {
    expect(() => sampleMarsController('grow-projection-history', contextAt(0.5, {
      controllerOptions,
    }))).toThrow(
      'Mars controller grow-projection-history requires finite evidence_start_day and evidence_end_day',
    );
  });

  it('rejects a reversed historical evidence pair', () => {
    expect(() => sampleMarsController('mark-stationary-points', contextAt(0.5, {
      controllerOptions: {evidence_start_day: 70, evidence_end_day: -70},
    }))).toThrow(
      'Mars controller mark-stationary-points evidence day range must not decrease',
    );
  });

  it('accepts an explicit finite zero-width historical evidence pair', () => {
    const patch = sampleMarsController('grow-projection-history', contextAt(0.5, {
      controllerOptions: {evidence_start_day: -20, evidence_end_day: -20},
    }));
    expect(patch.geometryOperations).toContainEqual({
      kind: 'projection_history',
      key: 'projection-evidence',
      startDay: -20,
      endDay: -20,
      count: 17,
    });
  });

  it.each([
    'hold-completed-track',
    'grow-cumulative-sightlines',
    'grow-projection-history',
    'mark-stationary-points',
    'add-solar-system-inset',
  ] as const)('requires explicit evidence options for %s', (controller) => {
    expect(() => sampleMarsController(controller, contextAt(0.5))).toThrow(
      `Mars controller ${controller} requires finite evidence_start_day and evidence_end_day`,
    );
  });

  it('keeps physical Mars forward while stationary markers use historical proof', () => {
    const objects = createSharedScene({seed: 7319, width: 1920, height: 1080});
    const state = createSequenceState();
    const patch = sampleMarsController('mark-stationary-points', contextAt(0.5, {
      simulationDay: 60,
      controllerOptions: {evidence_start_day: -70, evidence_end_day: 70},
    }));

    applyMergedPatch(
      objects,
      state,
      mergeSequencePatches(60, [patch]),
      DEFAULT_PHYSICS,
    );

    const physicalMars = orbitPosition('mars', 60, DEFAULT_PHYSICS);
    expect(objects.mars.position.toArray()).toEqual([
      physicalMars.x,
      physicalMars.y,
      physicalMars.z,
    ]);
    const window = findRetrogradeWindow(DEFAULT_PHYSICS, -70, 70);
    const start = skyTrackPosition(window.startDay, DEFAULT_PHYSICS);
    const end = skyTrackPosition(window.endDay, DEFAULT_PHYSICS);
    expect(objects.stationMarkerStart.position.x).toBeCloseTo(start.x, 8);
    expect(objects.stationMarkerEnd.position.x).toBeCloseTo(end.x, 8);
  });

  it('marks the two stationary points progressively instead of freezing B09', () => {
    const options = {evidence_start_day: -70, evidence_end_day: 70};
    const atStart = sampleMarsController('mark-stationary-points', contextAt(0, {
      controllerOptions: options,
    }));
    const atMiddle = sampleMarsController('mark-stationary-points', contextAt(0.5, {
      controllerOptions: options,
    }));
    const atEnd = sampleMarsController('mark-stationary-points', contextAt(1, {
      controllerOptions: options,
    }));

    expect(atStart.entityOverrides).toEqual({
      stationMarkerStart: {scale: 0.2},
      stationMarkerEnd: {scale: 0.2},
    });
    expect(atMiddle.entityOverrides).toEqual({
      stationMarkerStart: {scale: 1},
      stationMarkerEnd: {scale: 0.2},
    });
    expect(atEnd.entityOverrides).toEqual({
      stationMarkerStart: {scale: 1},
      stationMarkerEnd: {scale: 1},
    });
  });

  it('draws the apparent track left-right-left in the north-ecliptic view', () => {
    const objects = createSharedScene({seed: 220826, width: 1920, height: 1080});
    const state = createSequenceState();
    const markerX = (day: number): number => {
      const progress = (day + 70) / 140;
      const patch = sampleMarsController('grow-sky-track', contextAt(progress, {
        simulationDay: day,
      }));
      applyMergedPatch(
        objects,
        state,
        mergeSequencePatches(day, [patch]),
        DEFAULT_PHYSICS,
      );
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

  it('preserves inset group transforms when the following patch omits them', () => {
    const objects = createSharedScene({seed: 7319, width: 1920, height: 1080});
    const state = createSequenceState();
    const inset = sampleMarsController('add-solar-system-inset', contextAt(0.5, {
      controllerOptions: {evidence_start_day: -70, evidence_end_day: 70},
    }));
    applyMergedPatch(
      objects,
      state,
      mergeSequencePatches(80, [inset]),
      DEFAULT_PHYSICS,
    );
    const orbitPositionBefore = objects.orbitGroup.position.clone();
    const orbitScaleBefore = objects.orbitGroup.scale.clone();
    const skyPositionBefore = objects.skyGroup.position.clone();
    const skyScaleBefore = objects.skyGroup.scale.clone();

    const hold = sampleMarsController('hold-completed-track', contextAt(1, {
      controllerOptions: {evidence_start_day: -70, evidence_end_day: 70},
    }));
    applyMergedPatch(
      objects,
      state,
      mergeSequencePatches(90, [hold]),
      DEFAULT_PHYSICS,
    );

    expect(objects.orbitGroup.position).toEqual(orbitPositionBefore);
    expect(objects.orbitGroup.scale).toEqual(orbitScaleBefore);
    expect(objects.skyGroup.position).toEqual(skyPositionBefore);
    expect(objects.skyGroup.scale).toEqual(skyScaleBefore);
  });

  it('initializes the Mars graph with canonical groups and optional layers hidden', () => {
    const objects = createSequenceSceneGraph('mars-retrograde-teaching-model-v2', {
      seed: 7319,
      width: 1920,
      height: 1080,
    });

    expect(objects.orbitGroup.position.toArray()).toEqual([0, 0, 0]);
    expect(objects.orbitGroup.scale.toArray()).toEqual([1, 1, 1]);
    expect(objects.skyGroup.position.toArray()).toEqual([0, 0, 0]);
    expect(objects.skyGroup.scale.toArray()).toEqual([1, 1, 1]);
    expect(objects.orbitGroup.visible).toBe(true);
    expect(objects.sightline.visible).toBe(true);
    for (const optional of [
      objects.skyGroup,
      objects.projectionMarker,
      objects.starWall,
      objects.skyTrail,
      objects.earthTrail,
      objects.marsTrail,
      objects.projectionHistory,
      objects.sightlineHistory,
      objects.earthDirectionArrow,
      objects.marsDirectionArrow,
      objects.stationMarkerStart,
      objects.stationMarkerEnd,
    ]) {
      expect(optional.visible).toBe(false);
    }
  });

  it('rejects a Mars controller write outside its declared patch targets', () => {
    const objects = createSequenceSceneGraph('mars-retrograde-teaching-model-v2', {
      seed: 7319,
      width: 320,
      height: 180,
    });
    const job: SequenceRenderJob = {
      job_kind: 'sequence',
      sequence_id: 'SEQ01',
      scene_graph: 'mars-retrograde-teaching-model-v2',
      canonical_fps: 30,
      duration_frames: 1,
      frame_count: 1,
      output_directory: '/tmp/mars-patch-targets',
      output: {width: 320, height: 180, fps: 30},
      timeline: [{
        beat_id: 'B01',
        start_frame: 0,
        end_frame: 1,
        simulation_time_start: -70,
        simulation_time_end: -70,
        controller: 'grow-sky-track',
        patch_targets: ['geometry'],
        priority: 0,
        controller_options: {},
      }],
      canonical_state_cache: [{
        canonical_frame: 0,
        active_beat_ids: ['B01'],
        simulation_time: -70,
      }],
      sample_frames: [0],
      style: {seed: 7319, earth_scale: 0.075, mars_scale: 0.055},
    };

    const runtime = createSequenceRuntime(job, objects);
    expect(() => runtime.renderFrame(0)).toThrow(
      'sequence controller grow-sky-track writes undeclared patch target: layers',
    );
  });
});
