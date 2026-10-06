import type {Physics} from '../types.js';
import {createSceneController} from '../scenes/scene-registry.js';
import type {TemplateName} from '../scenes/contracts.js';
import type {SharedSceneObjects} from '../visuals/solar-system.js';
import type {
  CameraPatch,
  SequenceController,
  SequenceControllerContext,
} from './contracts.js';


const ECLIPSE_TEMPLATES = [
  'monthly-cycle-hook',
  'top-view-alignment',
  'tilt-reveal',
  'new-moon-miss',
  'full-moon-miss',
  'node-crossing',
  'solar-eclipse-alignment',
  'lunar-eclipse-alignment',
  'two-condition-summary',
] as const satisfies readonly TemplateName[];


export type EclipseTemplate = typeof ECLIPSE_TEMPLATES[number];


export interface EclipseSequenceOperation {
  kind: 'eclipse_template';
  key: string;
  template: EclipseTemplate;
  progress: number;
  simulationDay: number;
  simulationDayStart: number;
  simulationDayEnd: number;
  parameters: Record<string, unknown>;
}


const lerp = (start: number, end: number, progress: number): number =>
  start + (end - start) * Math.min(1, Math.max(0, progress));


const lerpTuple = (
  start: [number, number, number],
  end: [number, number, number],
  progress: number,
): [number, number, number] => [
  lerp(start[0], end[0], progress),
  lerp(start[1], end[1], progress),
  lerp(start[2], end[2], progress),
];


const viewModeFrom = (parameters: Record<string, unknown>): string => {
  const value = parameters.view_mode;
  return typeof value === 'string' ? value : 'wide_alignment';
};


const eclipseCamera = (
  template: EclipseTemplate,
  progress: number,
  parameters: Record<string, unknown>,
): CameraPatch => {
  const viewMode = viewModeFrom(parameters);
  switch (template) {
    case 'monthly-cycle-hook':
      return {position: [7.2, -8.4, 4.6], target: [0, 0, 0]};
    case 'top-view-alignment':
      if (viewMode === 'scale_to_apparent_size') {
        const sightlineProgress = Math.min(1, progress / 0.88);
        return {
          position: lerpTuple([0, 2.8, 20], [0, -0.45, 0], sightlineProgress),
          target: lerpTuple([0, 2.8, 0], [0, 8, 0], sightlineProgress),
          fov: lerp(38, 10, sightlineProgress),
        };
      }
      return {position: [0, 2.8, 20], target: [0, 2.8, 0]};
    case 'tilt-reveal':
      return {
        position: [
          lerp(0, 7, progress),
          lerp(0, -9, progress),
          lerp(11, 5, progress),
        ],
        target: [0, 0, 0],
      };
    case 'new-moon-miss':
      return {position: [8, 1, 0], target: [0, 1, 0]};
    case 'full-moon-miss':
      return {position: [8, -1, 0], target: [0, -1, 0]};
    case 'node-crossing':
      return {position: [7.5, -8.5, 4], target: [0.8, 0, 0]};
    case 'solar-eclipse-alignment':
      if (viewMode === 'earth_close_shadow_track') {
        return {
          position: lerpTuple([2.8, -6, 2], [1.35, -0.5, 0.3], progress),
          target: lerpTuple([0.9, 0, 0], [0, 0, 0], progress),
          fov: lerp(38, 28, progress),
        };
      }
      if (viewMode === 'moon_orbit_distance_reveal') {
        return {
          position: lerpTuple([4, -8, 4.5], [0, 0, 0], progress),
          target: lerpTuple([0, 0, 0], [8, 0, 0], progress),
          fov: lerp(38, 18, progress),
        };
      }
      if (viewMode === 'observer_annular_close') {
        return {
          position: [0, 0, 0],
          target: [8, 0, 0],
          fov: lerp(10, 9, progress),
        };
      }
      return {position: [4, -15, 6], target: [2.5, 0, 0], fov: 38};
    case 'lunar-eclipse-alignment':
      if (viewMode === 'moon_close_shadow_entry') {
        const zoomProgress = Math.min(1, progress / 0.28);
        return {
          position: lerpTuple([4, -15, 6], [-2.2, -1.2, 0.25], zoomProgress),
          target: lerpTuple(
            [2.5, 0, 0],
            [-2.2, lerp(0.55, 0, progress), 0],
            zoomProgress,
          ),
          fov: lerp(38, 12, zoomProgress),
        };
      }
      if (viewMode === 'blood_moon_close_to_night_side') {
        return {
          position: lerpTuple([-2.2, -1.05, 0.2], [0.6, -5.3, 1.7], progress),
          target: lerpTuple([-2.2, 0, 0], [-0.75, 0, 0], progress),
          fov: lerp(14, 32, progress),
        };
      }
      return {position: [4, -15, 6], target: [2.5, 0, 0], fov: 38};
    case 'two-condition-summary':
      return {position: [7, -18, 9], target: [2.5, 2.5, 0]};
  }
};


const eclipseController = (template: EclipseTemplate): SequenceController => ({
  sample(context: SequenceControllerContext) {
    const progress = context.layerRevealProgress ?? context.progress;
    return {
      geometryOperations: [{
        kind: 'eclipse_template',
        key: `eclipse-${template}`,
        template,
        progress,
        simulationDay: context.simulationDay,
        simulationDayStart: context.timelineItem.simulation_time_start,
        simulationDayEnd: context.timelineItem.simulation_time_end,
        parameters: context.controllerOptions,
      }],
      showLayers: ['eclipse'],
      hideLayers: ['orbitGroup'],
      camera: eclipseCamera(template, progress, context.controllerOptions),
    };
  },
});


export const ECLIPSE_SEQUENCE_CONTROLLERS = new Map<string, SequenceController>(
  ECLIPSE_TEMPLATES.map((template) => [template, eclipseController(template)]),
);


export const applyEclipseSequenceOperation = (
  objects: SharedSceneObjects,
  physics: Physics,
  operation: EclipseSequenceOperation,
): void => {
  const controller = createSceneController(operation.template, {
    objects,
    physics,
    simulationDayStart: operation.simulationDayStart,
    simulationDayEnd: operation.simulationDayEnd,
    eclipse: {
      parameters: operation.parameters,
      rendererOptions: {},
    },
  });
  controller.update(operation.progress, operation.simulationDay);
};
