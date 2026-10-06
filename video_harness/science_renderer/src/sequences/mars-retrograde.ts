import type {
  SequenceController,
  SequenceControllerContext,
  SequencePatch,
} from './contracts.js';


const evidenceRange = (
  context: SequenceControllerContext,
  controller: string,
): [number, number] => {
  const options = context.controllerOptions;
  const hasStart = Object.prototype.hasOwnProperty.call(options, 'evidence_start_day');
  const hasEnd = Object.prototype.hasOwnProperty.call(options, 'evidence_end_day');
  const startDay = options.evidence_start_day;
  const endDay = options.evidence_end_day;
  if (!hasStart || !hasEnd
      || typeof startDay !== 'number' || !Number.isFinite(startDay)
      || typeof endDay !== 'number' || !Number.isFinite(endDay)) {
    throw new Error(
      `Mars controller ${controller} requires finite evidence_start_day and evidence_end_day`,
    );
  }
  if (endDay < startDay) {
    throw new Error(
      `Mars controller ${controller} evidence day range must not decrease`,
    );
  }
  return [startDay, endDay];
};


const lerp = (start: number, end: number, progress: number): number =>
  start + (end - start) * Math.min(1, Math.max(0, progress));


const growSkyTrack: SequenceController = {
  sample(context) {
    return {
      geometryOperations: [{
        kind: 'sky_track',
        key: 'apparent-sky-track',
        startDay: context.timelineItem.simulation_time_start,
        endDay: context.simulationDay,
        count: Math.max(3, Math.round(3 + context.progress * 61)),
      }],
      showLayers: ['skyGroup', 'skyTrail', 'skyMarker'],
      hideLayers: ['orbitGroup', 'sightline'],
      camera: {position: [0, 0, 4.25], target: [0, 0, 0]},
    };
  },
};


const holdCompletedTrack: SequenceController = {
  sample(context) {
    const [startDay, endDay] = evidenceRange(context, 'hold-completed-track');
    return {
      geometryOperations: [{
        kind: 'sky_track',
        key: 'completed-sky-track',
        startDay,
        endDay,
        count: 64,
      }],
      showLayers: ['skyGroup', 'skyTrail', 'skyMarker'],
      camera: {position: [0, 0, 4.25], target: [0, 0, 0]},
    };
  },
};


const continuousSkyToOrbitPullback: SequenceController = {
  sample(context) {
    return {
      geometryOperations: [{
        kind: 'orbit_and_sightline',
        key: 'pullback-physical-orbits',
        day: context.simulationDay,
      }],
      showLayers: ['orbitGroup', 'sightline'],
      hideLayers: ['skyGroup', 'skyTrail', 'skyMarker'],
      camera: {
        position: [
          0,
          lerp(0, -4.1, context.progress),
          lerp(4.25, 3.2, context.progress),
        ],
        target: [0, 0, 0],
      },
    };
  },
};


const showSameDirectionArrows: SequenceController = {
  sample(context) {
    return {
      geometryOperations: [
        {kind: 'orbit_and_sightline', key: 'same-direction-orbits',
          day: context.simulationDay},
        {kind: 'direction_arrows', key: 'same-direction-arrows'},
      ],
      showLayers: ['orbitGroup', 'earthDirectionArrow', 'marsDirectionArrow'],
      hideLayers: ['sightline'],
      entityOverrides: {earth: {scale: 1.55}, mars: {scale: 1.7}},
      camera: {position: [0, 0, 4.15], target: [0, 0, 0]},
    };
  },
};


const growSpeedTrails: SequenceController = {
  sample(context) {
    return {
      geometryOperations: [
        {kind: 'orbit_and_sightline', key: 'speed-orbits', day: context.simulationDay},
        {
          kind: 'motion_trails',
          key: 'speed-trails',
          startDay: context.timelineItem.simulation_time_start,
          endDay: context.simulationDay,
          count: 18,
        },
      ],
      showLayers: ['orbitGroup', 'earthTrail', 'marsTrail'],
      entityOverrides: {earth: {scale: 1.65}, mars: {scale: 1.8}},
      camera: {position: [0, -4.25, 3.25], target: [0, 0, 0]},
    };
  },
};


const trackLocalOvertake: SequenceController = {
  sample(context) {
    return {
      geometryOperations: [
        {kind: 'orbit_and_sightline', key: 'local-overtake-orbits',
          day: context.simulationDay},
        {
          kind: 'motion_trails',
          key: 'local-overtake-trails',
          startDay: context.timelineItem.simulation_time_start,
          endDay: context.simulationDay,
          count: 24,
        },
      ],
      showLayers: ['orbitGroup', 'earthTrail', 'marsTrail'],
      entityOverrides: {
        sun: {visible: false},
        earth: {scale: 2.25},
        mars: {scale: 2.45},
      },
      camera: {position: [0, -2.6, 2], target: [0.4, 0, 0]},
    };
  },
};


const growCumulativeSightlines: SequenceController = {
  sample(context) {
    const [startDay, endDay] = evidenceRange(
      context,
      'grow-cumulative-sightlines',
    );
    const revealedCount = 1 + Math.floor(
      Math.min(1, Math.max(0, context.progress)) * 5,
    );
    return {
      geometryOperations: [
        {kind: 'orbit_and_sightline', key: 'physical-sightline',
          day: context.simulationDay, extendToProjection: true},
        {kind: 'cumulative_sightlines', key: 'sightline-evidence',
          startDay, endDay, revealedCount},
      ],
      showLayers: [
        'orbitGroup',
        'sightline',
        'sightlineHistory',
        'starWall',
        'projectionMarker',
      ],
      entityOverrides: {
        sun: {visible: true},
        earth: {scale: 1.45},
        mars: {scale: 1.55},
      },
      camera: {position: [0, -6.5, 5.05], target: [0, 0, 0]},
    };
  },
};


const growProjectionHistory: SequenceController = {
  sample(context) {
    const [startDay, finalEndDay] = evidenceRange(
      context,
      'grow-projection-history',
    );
    const endDay = lerp(startDay, finalEndDay, context.progress);
    return {
      geometryOperations: [
        {kind: 'orbit_and_sightline', key: 'projection-physical-sightline',
          day: context.simulationDay, extendToProjection: true},
        {kind: 'projection_history', key: 'projection-evidence',
          startDay, endDay, count: Math.max(2, Math.round(2 + context.progress * 30))},
      ],
      showLayers: [
        'orbitGroup',
        'sightline',
        'starWall',
        'projectionMarker',
        'projectionHistory',
      ],
      entityOverrides: {
        sun: {visible: true},
        earth: {scale: 1.55},
        mars: {scale: 1.7},
      },
      camera: {
        position: [
          lerp(-0.8, 1, context.progress),
          lerp(-7.3, -5.7, context.progress),
          lerp(6, 4.5, context.progress),
        ],
        target: [0, 0, 0],
      },
    };
  },
};


const markStationaryPoints: SequenceController = {
  sample(context) {
    const [startDay, endDay] = evidenceRange(context, 'mark-stationary-points');
    return {
      geometryOperations: [
        {kind: 'sky_track', key: 'stationary-proof-track',
          startDay, endDay, count: 64},
        {kind: 'stationary_markers', key: 'stationary-proof-markers',
          startDay, endDay},
      ],
      showLayers: [
        'skyGroup',
        'skyTrail',
        'stationMarkerStart',
        'stationMarkerEnd',
      ],
      hideLayers: ['orbitGroup', 'sightline', 'skyMarker'],
      entityOverrides: {
        stationMarkerStart: {scale: lerp(0.2, 1, context.progress * 2)},
        stationMarkerEnd: {scale: lerp(0.2, 1, (context.progress - 0.5) * 2)},
      },
      camera: {position: [0, 0, 4.25], target: [0, 0, 0]},
    };
  },
};


const addSolarSystemInset: SequenceController = {
  sample(context) {
    const [startDay, endDay] = evidenceRange(context, 'add-solar-system-inset');
    return {
      geometryOperations: [
        {kind: 'orbit_and_sightline', key: 'inset-physical-orbits',
          day: context.simulationDay, extendToProjection: true},
        {kind: 'sky_track', key: 'inset-completed-track',
          startDay, endDay, count: 64},
        {kind: 'stationary_markers', key: 'inset-stationary-markers',
          startDay, endDay},
      ],
      showLayers: [
        'orbitGroup',
        'sightline',
        'projectionMarker',
        'skyGroup',
        'skyTrail',
        'stationMarkerStart',
        'stationMarkerEnd',
      ],
      entityOverrides: {
        sun: {visible: true},
        earth: {scale: 5},
        mars: {scale: 5.5},
        projectionMarker: {scale: 3},
      },
      groupTransforms: {
        orbitGroup: {position: [-1.75, -0.45, 0], scale: 0.3},
        skyGroup: {position: [1.5, 0.55, 0.1], scale: 0.58},
      },
      camera: {position: [0, 0, 5.2], target: [0, 0, 0]},
    };
  },
};


export const MARS_SEQUENCE_CONTROLLERS = new Map<string, SequenceController>([
  ['grow-sky-track', growSkyTrack],
  ['hold-completed-track', holdCompletedTrack],
  ['continuous-sky-to-orbit-pullback', continuousSkyToOrbitPullback],
  ['show-same-direction-arrows', showSameDirectionArrows],
  ['grow-speed-trails', growSpeedTrails],
  ['track-local-overtake', trackLocalOvertake],
  ['grow-cumulative-sightlines', growCumulativeSightlines],
  ['grow-projection-history', growProjectionHistory],
  ['mark-stationary-points', markStationaryPoints],
  ['add-solar-system-inset', addSolarSystemInset],
]);
