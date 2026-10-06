import * as THREE from 'three';

import {HR_SOURCE_STARS} from '../data/hr-stars.js';
import type {SharedSceneObjects} from '../visuals/solar-system.js';
import {
  resetHrDiagram,
  setHrAxesReveal,
  setHrNamedMarkerReveal,
  setHrRadiusStage,
  setHrRegionReveal,
  setHrStarReveal,
  setHrTemperatureGuide,
} from '../visuals/hr-diagram.js';
import type {
  CameraPatch,
  SequenceController,
  SequenceControllerContext,
} from './contracts.js';


export const HR_DIAGRAM_TEMPLATES = [
  'reveal-hr-axes',
  'plot-hr-source-stars',
  'reveal-main-sequence',
  'reveal-giants-and-supergiants',
  'reveal-white-dwarfs',
  'compare-stellar-radii',
  'connect-radius-to-hr-position',
  'summarize-hr-map',
] as const;


export type HrDiagramTemplate = typeof HR_DIAGRAM_TEMPLATES[number];


export interface HrDiagramOperation {
  kind: 'hr_diagram';
  key: string;
  template: HrDiagramTemplate;
  progress: number;
  parameters: Record<string, unknown>;
}


const hrCamera = (
  template: HrDiagramTemplate,
  progress: number,
): CameraPatch => template === 'compare-stellar-radii'
  ? {position: [0, 0, 6.2 + progress * 2.2], target: [0, 0, 0]}
  : {position: [0, 0, 6.2], target: [0, 0, 0]};


const hrController = (template: HrDiagramTemplate): SequenceController => ({
  sample(context: SequenceControllerContext) {
    const progress = context.layerRevealProgress ?? context.progress;
    return {
      geometryOperations: [{
        kind: 'hr_diagram',
        key: `hr-${template}`,
        template,
        progress,
        parameters: context.controllerOptions,
      }],
      showLayers: ['hr'],
      hideLayers: ['orbitGroup', 'eclipse'],
      camera: hrCamera(template, progress),
    };
  },
});


export const HR_DIAGRAM_SEQUENCE_CONTROLLERS = new Map<
  string,
  SequenceController
>(HR_DIAGRAM_TEMPLATES.map((template) => [template, hrController(template)]));


const showChartFoundation = (objects: SharedSceneObjects): void => {
  objects.hr.chartGroup.visible = true;
  objects.hr.radiusGroup.visible = false;
  setHrAxesReveal(objects.hr, 1);
};


const showAllSourceStars = (objects: SharedSceneObjects): void => {
  setHrStarReveal(objects.hr, HR_SOURCE_STARS.length);
};


export const applyHrDiagramOperation = (
  objects: SharedSceneObjects,
  operation: HrDiagramOperation,
): void => {
  const progress = THREE.MathUtils.clamp(operation.progress, 0, 1);
  resetHrDiagram(objects.hr);

  switch (operation.template) {
    case 'reveal-hr-axes':
      setHrAxesReveal(objects.hr, progress);
      break;
    case 'plot-hr-source-stars':
      showChartFoundation(objects);
      setHrStarReveal(objects.hr, Math.floor(progress * HR_SOURCE_STARS.length));
      break;
    case 'reveal-main-sequence':
      showChartFoundation(objects);
      showAllSourceStars(objects);
      setHrRegionReveal(objects.hr, progress > 0 ? ['main_sequence'] : []);
      break;
    case 'reveal-giants-and-supergiants':
      showChartFoundation(objects);
      showAllSourceStars(objects);
      setHrRegionReveal(objects.hr, progress > 0
        ? ['main_sequence', 'red_giant', 'supergiant']
        : ['main_sequence']);
      break;
    case 'reveal-white-dwarfs':
      showChartFoundation(objects);
      showAllSourceStars(objects);
      setHrRegionReveal(objects.hr, progress > 0
        ? ['main_sequence', 'red_giant', 'supergiant', 'white_dwarf']
        : ['main_sequence', 'red_giant', 'supergiant']);
      break;
    case 'compare-stellar-radii':
      setHrRadiusStage(objects.hr, progress);
      break;
    case 'connect-radius-to-hr-position':
      showChartFoundation(objects);
      showAllSourceStars(objects);
      setHrRegionReveal(objects.hr, [
        'main_sequence',
        'red_giant',
        'supergiant',
        'white_dwarf',
      ]);
      setHrNamedMarkerReveal(objects.hr, ['sun', 'arcturus', 'antares']);
      setHrTemperatureGuide(objects.hr, progress > 0);
      break;
    case 'summarize-hr-map':
      showChartFoundation(objects);
      showAllSourceStars(objects);
      setHrRegionReveal(objects.hr, [
        'main_sequence',
        'red_giant',
        'supergiant',
        'white_dwarf',
      ]);
      setHrNamedMarkerReveal(objects.hr, [
        'antares',
        'sun',
        'sirius-b',
        'arcturus',
      ]);
      break;
  }
};
