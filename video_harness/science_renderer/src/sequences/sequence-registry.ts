import {captureContinuity} from './continuity-capture.js';
import type {
  PatchTarget,
  SequenceRenderJob,
  SequenceStateSample,
  SequenceTimelineItem,
} from '../render-job.js';
import type {Physics} from '../types.js';
import {
  createSharedScene,
  resetSharedSceneGroupTransforms,
  type SharedSceneObjects,
  type SharedSceneOptions,
} from '../visuals/solar-system.js';
import {
  applyMergedPatch,
  cameraSnapshot,
  canonicalFrameForOutput,
  createFrameOrderGuard,
  entityScaleSnapshot,
  initializeSequenceLayerVisibility,
  mergeSequencePatches,
  stateFingerprint,
  type SequenceController,
  type SequenceControllerContext,
  type SequencePatch,
  type SequenceRuntime,
} from './contracts.js';
import {DEFAULT_PHYSICS} from '../math/circular-orbit.js';
import {MARS_SEQUENCE_CONTROLLERS} from './mars-retrograde.js';
import {INNER_PLANET_SEQUENCE_CONTROLLERS} from './inner-planet.js';
import {ECLIPSE_SEQUENCE_CONTROLLERS} from './eclipse.js';
import {HR_DIAGRAM_SEQUENCE_CONTROLLERS} from './hr-diagram.js';
import {
  applySequenceVariantProfile,
  layerRevealProgress,
  parseSequenceVariantProfile,
  type SequenceVariantProfile,
} from './variant-profile.js';


export type SequenceSceneGraphFactory = (
  options: SharedSceneOptions,
) => SharedSceneObjects;


export const SEQUENCE_CONTROLLER_REGISTRY = new Map<string, SequenceController>(
  [
    ...MARS_SEQUENCE_CONTROLLERS,
    ...INNER_PLANET_SEQUENCE_CONTROLLERS,
    ...ECLIPSE_SEQUENCE_CONTROLLERS,
    ...HR_DIAGRAM_SEQUENCE_CONTROLLERS,
  ],
);


const createMarsRetrogradeTeachingModel: SequenceSceneGraphFactory = (options) => {
  const objects = createSharedScene(options);
  resetSharedSceneGroupTransforms(objects);
  initializeSequenceLayerVisibility(objects);
  return objects;
};


const createInnerPlanetOvertakeTeachingModel: SequenceSceneGraphFactory = (options) => {
  const objects = createSharedScene(options);
  resetSharedSceneGroupTransforms(objects);
  initializeSequenceLayerVisibility(objects);
  return objects;
};


const createSunEarthMoonEclipseTeachingModel: SequenceSceneGraphFactory = (options) => {
  const objects = createSharedScene(options);
  resetSharedSceneGroupTransforms(objects);
  initializeSequenceLayerVisibility(objects);
  return objects;
};


const createHrDiagramTeachingModel: SequenceSceneGraphFactory = (options) => {
  const objects = createSharedScene(options);
  resetSharedSceneGroupTransforms(objects);
  initializeSequenceLayerVisibility(objects);
  return objects;
};


export const SEQUENCE_SCENE_GRAPH_REGISTRY = new Map<
  string,
  SequenceSceneGraphFactory
>([
  ['shared-science-scene', createSharedScene],
  ['mars-retrograde-teaching-model-v2', createMarsRetrogradeTeachingModel],
  [
    'inner-planet-overtake-teaching-model-v1',
    createInnerPlanetOvertakeTeachingModel,
  ],
  [
    'sun-earth-moon-eclipse-teaching-model-v1',
    createSunEarthMoonEclipseTeachingModel,
  ],
  ['hr-diagram-teaching-model-v1', createHrDiagramTeachingModel],
]);


export const createSequenceSceneGraph = (
  name: string,
  options: SharedSceneOptions,
): SharedSceneObjects => {
  const factory = SEQUENCE_SCENE_GRAPH_REGISTRY.get(name);
  if (!factory) throw new Error(`unknown sequence scene graph: ${name}`);
  return factory(options);
};


const physicsFromJob = (job: SequenceRenderJob): Physics =>
  job.physics
    ? {
        earthPeriodDays: job.physics.earth_period_days,
        marsPeriodDays: job.physics.mars_period_days,
        earthOrbitRadius: job.physics.earth_orbit_radius,
        marsOrbitRadius: job.physics.mars_orbit_radius,
        oppositionDay: job.physics.opposition_day,
      }
    : DEFAULT_PHYSICS;


const validateCanonicalCache = (job: SequenceRenderJob): void => {
  if (!Number.isInteger(job.duration_frames) || job.duration_frames < 1) {
    throw new Error('duration_frames must be a positive integer');
  }
  if (job.canonical_state_cache.length !== job.duration_frames) {
    throw new Error(
      'canonical state cache frames must be exactly 0..duration_frames-1',
    );
  }
  let previousSimulationTime = Number.NEGATIVE_INFINITY;
  for (let index = 0; index < job.canonical_state_cache.length; index += 1) {
    const entry = job.canonical_state_cache[index]!;
    if (entry.canonical_frame !== index) {
      throw new Error(
        'canonical state cache frames must be exactly 0..duration_frames-1',
      );
    }
    if (!Number.isFinite(entry.simulation_time)
        || entry.simulation_time < previousSimulationTime) {
      throw new Error('canonical state cache simulation time must not decrease');
    }
    previousSimulationTime = entry.simulation_time;
  }
};


const timelineByBeatId = (
  timeline: readonly SequenceTimelineItem[],
): ReadonlyMap<string, SequenceTimelineItem> => {
  const result = new Map<string, SequenceTimelineItem>();
  for (const item of timeline) {
    if (result.has(item.beat_id)) {
      throw new Error(`duplicate sequence beat id: ${item.beat_id}`);
    }
    result.set(item.beat_id, item);
  }
  return result;
};


const validateTimelineReferences = (
  job: SequenceRenderJob,
  itemsById: ReadonlyMap<string, SequenceTimelineItem>,
): void => {
  for (const item of job.timeline) {
    if (!SEQUENCE_CONTROLLER_REGISTRY.has(item.controller)) {
      throw new Error(`unknown sequence controller: ${item.controller}`);
    }
  }
  for (const entry of job.canonical_state_cache) {
    const seen = new Set<string>();
    for (const beatId of entry.active_beat_ids) {
      if (seen.has(beatId)) {
        throw new Error(`canonical cache repeats active beat: ${beatId}`);
      }
      seen.add(beatId);
      if (!itemsById.has(beatId)) {
        throw new Error(`canonical cache names unknown beat: ${beatId}`);
      }
    }
  }
};


const controllerContext = (
  job: SequenceRenderJob,
  item: SequenceTimelineItem,
  canonicalFrame: number,
  simulationDay: number,
  variantProfile: SequenceVariantProfile,
): SequenceControllerContext => {
  const denominator = Math.max(1, item.end_frame - item.start_frame - 1);
  const progress = Math.min(
    1,
    Math.max(0, (canonicalFrame - item.start_frame) / denominator),
  );
  return {
    canonicalFrame,
    simulationDay,
    progress,
    layerRevealProgress: layerRevealProgress(progress, variantProfile),
    timelineItem: item,
    controllerOptions: item.controller_options,
    variantProfile,
  };
};


const patchTargetsWritten = (patch: SequencePatch): PatchTarget[] => {
  const targets: PatchTarget[] = [];
  if (patch.simulationDay !== undefined) targets.push('simulation_clock');
  if ((patch.geometryOperations?.length ?? 0) > 0) targets.push('geometry');
  if ((patch.showLayers?.length ?? 0) > 0) targets.push('layers');
  if (Object.keys(patch.entityOverrides ?? {}).length > 0
      || Object.keys(patch.groupTransforms ?? {}).length > 0) {
    targets.push('entities');
  }
  if (patch.camera) targets.push('camera');
  if ((patch.hideLayers?.length ?? 0) > 0) targets.push('hide_events');
  return targets;
};


const validateControllerPatchTargets = (
  item: SequenceTimelineItem,
  patch: SequencePatch,
): void => {
  const declared = new Set(item.patch_targets);
  for (const target of patchTargetsWritten(patch)) {
    if (!declared.has(target)) {
      throw new Error(
        `sequence controller ${item.controller} writes undeclared patch target: ${target}`,
      );
    }
  }
};


export const createSequenceRuntime = (
  job: SequenceRenderJob,
  objects: SharedSceneObjects,
): SequenceRuntime => {
  validateCanonicalCache(job);
  if (!(job.output.fps > 0) || !(job.canonical_fps > 0)) {
    throw new Error('sequence frame rates must be positive');
  }
  const itemsById = timelineByBeatId(job.timeline);
  validateTimelineReferences(job, itemsById);
  const physics = physicsFromJob(job);
  const variantProfile = parseSequenceVariantProfile(job.variant_profile);
  const state = initializeSequenceLayerVisibility(objects);
  const orderGuard = createFrameOrderGuard();
  let latestSnapshot: SequenceStateSample | undefined;

  return {
    renderFrame(outputFrame: number): void {
      orderGuard.accept(outputFrame);
      const canonicalFrame = canonicalFrameForOutput(
        outputFrame,
        job.output.fps,
        job.canonical_fps,
        job.duration_frames,
      );
      const cacheEntry = job.canonical_state_cache[canonicalFrame]!;
      const activeItems = cacheEntry.active_beat_ids.map((beatId) => {
        const item = itemsById.get(beatId);
        if (!item) throw new Error(`canonical cache names unknown beat: ${beatId}`);
        return item;
      }).sort((left, right) =>
        left.priority - right.priority || left.beat_id.localeCompare(right.beat_id),
      );
      const patches = activeItems.map((item) => {
        const controller = SEQUENCE_CONTROLLER_REGISTRY.get(item.controller);
        if (!controller) {
          throw new Error(`unknown sequence controller: ${item.controller}`);
        }
        const patch = controller.sample(
          controllerContext(
            job,
            item,
            canonicalFrame,
            cacheEntry.simulation_time,
            variantProfile,
          ),
        );
        validateControllerPatchTargets(item, patch);
        return patch;
      });
      const mergedPatch = applySequenceVariantProfile(
        mergeSequencePatches(cacheEntry.simulation_time, patches),
        variantProfile,
      );
      applyMergedPatch(objects, state, mergedPatch, physics);

      const snapshotWithoutFingerprint: Omit<
        SequenceStateSample,
        'state_fingerprint'
      > = {
        canonical_frame: canonicalFrame,
        simulation_time: cacheEntry.simulation_time,
        visible_layers: [...state.visibleLayers].sort(),
        geometry_operation_keys: (mergedPatch.geometryOperations ?? [])
          .map((operation) => operation.key),
        continuity: captureContinuity(objects.scene, objects.camera, {sun:objects.sun,earth:objects.earth,mars:objects.mars,innerPlanet:objects.innerPlanet}),
        camera: cameraSnapshot(objects),
        entity_scales: entityScaleSnapshot(objects),
      };
      latestSnapshot = {
        ...snapshotWithoutFingerprint,
        state_fingerprint: stateFingerprint(snapshotWithoutFingerprint),
      };
    },

    stateSnapshot(): SequenceStateSample {
      if (!latestSnapshot) {
        throw new Error('sequence state is unavailable before the first frame');
      }
      return structuredClone(latestSnapshot);
    },
  };
};
