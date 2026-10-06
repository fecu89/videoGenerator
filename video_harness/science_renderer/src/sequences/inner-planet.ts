import type {
  SequenceController,
  SequenceControllerContext,
} from './contracts.js';


const evidenceRange = (
  context: SequenceControllerContext,
): [number, number] => {
  const startDay = context.controllerOptions.evidence_start_day;
  const endDay = context.controllerOptions.evidence_end_day;
  if (typeof startDay !== 'number' || !Number.isFinite(startDay)
      || typeof endDay !== 'number' || !Number.isFinite(endDay)) {
    throw new Error(
      'Inner-planet projection requires finite evidence_start_day and evidence_end_day',
    );
  }
  if (endDay < startDay) {
    throw new Error('Inner-planet projection evidence day range must not decrease');
  }
  return [startDay, endDay];
};


const lerp = (start: number, end: number, progress: number): number =>
  start + (end - start) * Math.min(1, Math.max(0, progress));


const showInnerPlanetOvertake: SequenceController = {
  sample(context) {
    return {
      geometryOperations: [{
        kind: 'inner_planet_overtake',
        key: 'inner-planet-overtake',
        day: context.simulationDay,
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
    };
  },
};


const showInnerPlanetRetrogradeProjection: SequenceController = {
  sample(context) {
    const [startDay, finalEndDay] = evidenceRange(context);
    const endDay = lerp(startDay, finalEndDay, context.progress);
    return {
      geometryOperations: [{
        kind: 'inner_planet_projection',
        key: 'inner-planet-retrograde-projection',
        day: context.simulationDay,
        startDay,
        endDay,
        count: Math.max(2, Math.round(2 + context.progress * 30)),
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
        'innerSightline',
        'starWall',
        'innerProjectionMarker',
        'innerProjectionHistory',
      ],
      hideLayers: ['marsOrbitPath', 'sightline'],
      entityOverrides: {earth: {scale: 1.75}, mars: {visible: false}},
      camera: {position: [0, -6.5, 5.05], target: [0, 0, 0]},
    };
  },
};


const showInnerPlanetElongation: SequenceController = {
  sample(context) {
    const side = context.controllerOptions.elongation_side;
    if (side !== 'morning' && side !== 'evening') {
      throw new Error(
        'Inner-planet elongation requires elongation_side morning or evening',
      );
    }
    return {
      geometryOperations: [{
        kind: 'inner_planet_elongation',
        key: `inner-planet-${side}-elongation`,
        day: context.simulationDay,
        orbitRadius: 0.72,
        side,
      }],
      showLayers: [
        'orbitGroup',
        'innerPlanetGroup',
        'earthDirectionArrow',
        'innerPlanetDirectionArrow',
        'innerSunRay',
        'innerElongationRay',
        'innerElongationArc',
      ],
      hideLayers: [
        'marsOrbitPath',
        'sightline',
        'innerConjunctionLine',
        'innerSightline',
        'starWall',
        'innerProjectionMarker',
        'innerProjectionHistory',
      ],
      entityOverrides: {earth: {scale: 1.75}, mars: {visible: false}},
      camera: {position: [0, -4.4, 4.4], target: [0, 0, 0]},
    };
  },
};


export const INNER_PLANET_SEQUENCE_CONTROLLERS = new Map<string, SequenceController>([
  ['show-inner-planet-overtake', showInnerPlanetOvertake],
  ['show-inner-planet-retrograde-projection', showInnerPlanetRetrogradeProjection],
  ['show-inner-planet-elongation', showInnerPlanetElongation],
]);
