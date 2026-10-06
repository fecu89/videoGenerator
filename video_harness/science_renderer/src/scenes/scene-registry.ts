import {createEarthOvertake} from './earth-overtake.js';
import {createMovingObserver} from './moving-observer.js';
import {createProjectionProof} from './projection-proof.js';
import {createRetrogradeTrack} from './retrograde-track.js';
import {createReturnToDirect} from './return-to-direct.js';
import {createSightlineAngle} from './sightline-angle.js';
import {createSkyOrbitReveal} from './sky-orbit-reveal.js';
import {createSpeedComparison} from './speed-comparison.js';
import {
  createCumulativeSightlines,
  createLocalOvertake,
  createSameDirectionArrows,
  createStationaryPoints,
} from './mars-explainer.js';
import {
  createFullMoonMiss,
  createLunarEclipseAlignment,
  createMonthlyCycleHook,
  createNewMoonMiss,
  createNodeCrossing,
  createSolarEclipseAlignment,
  createTiltReveal,
  createTopViewAlignment,
  createTwoConditionSummary,
} from './eclipse-scenes.js';
import type {
  ControllerContext,
  SceneController,
  SceneFactory,
  TemplateName,
} from './contracts.js';


export const SCENE_REGISTRY: ReadonlyMap<TemplateName, SceneFactory> = new Map([
  ['sky-orbit-reveal', createSkyOrbitReveal],
  ['retrograde-track', createRetrogradeTrack],
  ['moving-observer', createMovingObserver],
  ['sightline-angle', createSightlineAngle],
  ['speed-comparison', createSpeedComparison],
  ['earth-overtake', createEarthOvertake],
  ['projection-proof', createProjectionProof],
  ['return-to-direct', createReturnToDirect],
  ['same-direction-arrows', createSameDirectionArrows],
  ['local-overtake', createLocalOvertake],
  ['cumulative-sightlines', createCumulativeSightlines],
  ['stationary-points', createStationaryPoints],
  ['monthly-cycle-hook', createMonthlyCycleHook],
  ['top-view-alignment', createTopViewAlignment],
  ['tilt-reveal', createTiltReveal],
  ['new-moon-miss', createNewMoonMiss],
  ['full-moon-miss', createFullMoonMiss],
  ['node-crossing', createNodeCrossing],
  ['solar-eclipse-alignment', createSolarEclipseAlignment],
  ['lunar-eclipse-alignment', createLunarEclipseAlignment],
  ['two-condition-summary', createTwoConditionSummary],
]);


export const createSceneController = (
  template: TemplateName,
  context: ControllerContext,
): SceneController => {
  const factory = SCENE_REGISTRY.get(template);
  if (!factory) {
    throw new Error(`unknown simulation template: ${template}`);
  }
  return factory(context);
};
