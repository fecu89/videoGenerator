import * as THREE from 'three';

import {
  projectionOnCircle,
  skyTrackPosition,
  updateCumulativeSightlines,
  updateDirectionArrow,
  updateMotionTrails,
  updateOrbitAndSightline,
  updateProjectionHistory,
  updateSkyTrack,
} from '../scenes/contracts.js';
import {findRetrogradeWindow} from '../math/retrograde.js';
import type {SequenceStateSample, SequenceTimelineItem} from '../render-job.js';
import type {Physics} from '../types.js';
import type {SequenceVariantProfile} from './variant-profile.js';
import {
  heliocentricAngle,
  orbitPosition,
} from '../math/circular-orbit.js';
import {
  positionPlanets,
  setLinePoints,
  setPointPositions,
  type SharedSceneObjects,
} from '../visuals/solar-system.js';
import {
  applyEclipseSequenceOperation,
  type EclipseSequenceOperation,
} from './eclipse.js';
import {
  applyHrDiagramOperation,
  type HrDiagramOperation,
} from './hr-diagram.js';


export type GeometryOperation =
  | HrDiagramOperation
  | EclipseSequenceOperation
  | {
      kind: 'orbit_and_sightline';
      key: string;
      day: number;
      extendToProjection?: boolean;
    }
  | {
      kind: 'sky_track';
      key: string;
      startDay: number;
      endDay: number;
      count: number;
    }
  | {
      kind: 'motion_trails';
      key: string;
      startDay: number;
      endDay: number;
      count?: number;
    }
  | {
      kind: 'cumulative_sightlines';
      key: string;
      startDay: number;
      endDay: number;
      revealedCount: number;
    }
  | {
      kind: 'projection_history';
      key: string;
      startDay: number;
      endDay: number;
      count?: number;
    }
  | {kind: 'direction_arrows'; key: string}
  | {
      kind: 'stationary_markers';
      key: string;
      startDay: number;
      endDay: number;
    }
  | {
      kind: 'inner_planet_overtake';
      key: string;
      day: number;
      orbitRadius: number;
      periodDays: number;
      conjunctionDay: number;
    }
  | {
      kind: 'inner_planet_projection';
      key: string;
      day: number;
      startDay: number;
      endDay: number;
      count: number;
      orbitRadius: number;
      periodDays: number;
      conjunctionDay: number;
    }
  | {
      kind: 'inner_planet_elongation';
      key: string;
      day: number;
      orbitRadius: number;
      side: 'morning' | 'evening';
    };


export interface CameraPatch {
  position?: [number, number, number];
  target?: [number, number, number];
  fov?: number;
}


export interface EntityOverride {
  scale?: number;
  visible?: boolean;
}


export type TransformGroupName = 'orbitGroup' | 'skyGroup';


export interface GroupTransform {
  position?: [number, number, number];
  rotation?: [number, number, number];
  scale?: number;
}


export interface SequencePatch {
  simulationDay?: number;
  geometryOperations?: GeometryOperation[];
  showLayers?: string[];
  hideLayers?: string[];
  camera?: CameraPatch;
  entityOverrides?: Record<string, EntityOverride>;
  groupTransforms?: Partial<Record<TransformGroupName, GroupTransform>>;
}


export interface SequenceState {
  visibleLayers: Set<string>;
}


export interface SequenceControllerContext {
  canonicalFrame: number;
  simulationDay: number;
  progress: number;
  layerRevealProgress?: number;
  timelineItem: SequenceTimelineItem;
  controllerOptions: Record<string, unknown>;
  variantProfile?: SequenceVariantProfile;
}


export interface SequenceController {
  sample(context: SequenceControllerContext): SequencePatch;
}


export interface SequenceRuntime {
  renderFrame(outputFrame: number): void;
  stateSnapshot(): SequenceStateSample;
}


const layerObjects = (objects: SharedSceneObjects): Record<string, THREE.Object3D> => ({
  orbitGroup: objects.orbitGroup,
  skyGroup: objects.skyGroup,
  earthOrbitPath: objects.earthOrbitPath,
  marsOrbitPath: objects.marsOrbitPath,
  sightline: objects.sightline,
  projectionMarker: objects.projectionMarker,
  starWall: objects.starWall,
  skyMarker: objects.skyMarker,
  skyTrail: objects.skyTrail,
  earthTrail: objects.earthTrail,
  marsTrail: objects.marsTrail,
  projectionHistory: objects.projectionHistory,
  sightlineHistory: objects.sightlineHistory,
  earthDirectionArrow: objects.earthDirectionArrow,
  marsDirectionArrow: objects.marsDirectionArrow,
  stationMarkerStart: objects.stationMarkerStart,
  stationMarkerEnd: objects.stationMarkerEnd,
  innerPlanetGroup: objects.innerPlanetGroup,
  innerPlanetDirectionArrow: objects.innerPlanetDirectionArrow,
  innerConjunctionLine: objects.innerConjunctionLine,
  innerSightline: objects.innerSightline,
  innerProjectionMarker: objects.innerProjectionMarker,
  innerProjectionHistory: objects.innerProjectionHistory,
  innerSunRay: objects.innerSunRay,
  innerElongationRay: objects.innerElongationRay,
  innerElongationArc: objects.innerElongationArc,
  eclipse: objects.eclipse.group,
  hr: objects.hr.group,
});


const entityObjects = (objects: SharedSceneObjects): Record<string, THREE.Object3D> => ({
  sun: objects.sun,
  earth: objects.earth,
  mars: objects.mars,
  innerPlanet: objects.innerPlanet,
  projectionMarker: objects.projectionMarker,
  skyMarker: objects.skyMarker,
  stationMarkerStart: objects.stationMarkerStart,
  stationMarkerEnd: objects.stationMarkerEnd,
});


const transformGroups = (
  objects: SharedSceneObjects,
): Record<TransformGroupName, THREE.Group> => ({
  orbitGroup: objects.orbitGroup,
  skyGroup: objects.skyGroup,
});


const requireNamedObject = (
  objects: Record<string, THREE.Object3D>,
  name: string,
  kind: string,
): THREE.Object3D => {
  const object = objects[name];
  if (!object) throw new Error(`unknown sequence ${kind}: ${name}`);
  return object;
};


export const createSequenceState = (
  visibleLayers: Iterable<string> = [],
): SequenceState => ({visibleLayers: new Set(visibleLayers)});


export const applyPersistentEvents = (
  state: SequenceState,
  patch: Pick<SequencePatch, 'showLayers' | 'hideLayers'>,
): void => {
  for (const layer of patch.showLayers ?? []) state.visibleLayers.add(layer);
  for (const layer of patch.hideLayers ?? []) state.visibleLayers.delete(layer);
};


export const initializeSequenceLayerVisibility = (
  objects: SharedSceneObjects,
): SequenceState => {
  const initializedLayers = objects.scene.userData.sequenceInitialVisibleLayers;
  if (Array.isArray(initializedLayers)) {
    return createSequenceState(initializedLayers as string[]);
  }
  const layers = layerObjects(objects);
  for (const object of Object.values(layers)) object.visible = false;
  layers.orbitGroup!.visible = true;
  layers.sightline!.visible = true;
  layers.earthOrbitPath!.visible = true;
  layers.marsOrbitPath!.visible = true;
  const visibleLayers = [
    'orbitGroup',
    'earthOrbitPath',
    'marsOrbitPath',
    'sightline',
  ];
  objects.scene.userData.sequenceInitialVisibleLayers = [...visibleLayers];
  return createSequenceState(visibleLayers);
};


export const setLayerVisible = (
  objects: SharedSceneObjects,
  layer: string,
  visible: boolean,
): void => {
  requireNamedObject(layerObjects(objects), layer, 'layer').visible = visible;
};


const validatePatchLayers = (
  objects: SharedSceneObjects,
  patch: Pick<SequencePatch, 'showLayers' | 'hideLayers'>,
): void => {
  const layers = layerObjects(objects);
  for (const layer of [...(patch.showLayers ?? []), ...(patch.hideLayers ?? [])]) {
    requireNamedObject(layers, layer, 'layer');
  }
};


export const applyBaseSimulation = (
  objects: SharedSceneObjects,
  physics: Physics,
  simulationDay: number,
): void => {
  positionPlanets(objects, physics, simulationDay);
};


export const applyGeometryOperations = (
  objects: SharedSceneObjects,
  physics: Physics,
  operations: readonly GeometryOperation[],
): void => {
  for (const operation of operations) {
    switch (operation.kind) {
      case 'hr_diagram':
        applyHrDiagramOperation(objects, operation);
        break;
      case 'eclipse_template':
        applyEclipseSequenceOperation(objects, physics, operation);
        break;
      case 'orbit_and_sightline':
        updateOrbitAndSightline(
          objects,
          physics,
          operation.day,
          operation.extendToProjection ?? false,
        );
        break;
      case 'sky_track':
        updateSkyTrack(
          objects,
          physics,
          operation.startDay,
          operation.endDay,
          operation.count,
        );
        break;
      case 'motion_trails':
        updateMotionTrails(
          objects,
          physics,
          operation.startDay,
          operation.endDay,
          operation.count,
        );
        break;
      case 'cumulative_sightlines':
        updateCumulativeSightlines(
          objects,
          physics,
          operation.startDay,
          operation.endDay,
          operation.revealedCount,
        );
        break;
      case 'projection_history':
        updateProjectionHistory(
          objects,
          physics,
          operation.startDay,
          operation.endDay,
          operation.count,
        );
        break;
      case 'direction_arrows':
        updateDirectionArrow(objects.earthDirectionArrow, {
          x: objects.earth.position.x,
          y: objects.earth.position.y,
          z: objects.earth.position.z,
        });
        updateDirectionArrow(objects.marsDirectionArrow, {
          x: objects.mars.position.x,
          y: objects.mars.position.y,
          z: objects.mars.position.z,
        });
        break;
      case 'stationary_markers': {
        const window = findRetrogradeWindow(
          physics,
          operation.startDay,
          operation.endDay,
        );
        const start = skyTrackPosition(window.startDay, physics);
        const end = skyTrackPosition(window.endDay, physics);
        objects.stationMarkerStart.position.set(start.x, start.y, start.z);
        objects.stationMarkerEnd.position.set(end.x, end.y, end.z);
        break;
      }
      case 'inner_planet_overtake': {
        const earth = orbitPosition('earth', operation.day, physics);
        const innerAngle = heliocentricAngle(
          operation.periodDays,
          operation.day,
          operation.conjunctionDay,
        );
        const inner = {
          x: operation.orbitRadius * Math.cos(innerAngle),
          y: operation.orbitRadius * Math.sin(innerAngle),
          z: 0,
        };
        objects.earth.position.set(earth.x, earth.y, earth.z);
        objects.innerPlanet.position.set(inner.x, inner.y, inner.z);
        objects.innerPlanet.rotation.y = operation.day * 0.09;
        updateDirectionArrow(objects.earthDirectionArrow, earth);
        updateDirectionArrow(objects.innerPlanetDirectionArrow, inner);
        setLinePoints(objects.innerConjunctionLine, [
          {x: 0, y: 0, z: 0},
          earth,
        ]);
        break;
      }
      case 'inner_planet_projection': {
        const innerPosition = (day: number) => {
          const angle = heliocentricAngle(
            operation.periodDays,
            day,
            operation.conjunctionDay,
          );
          return {
            x: operation.orbitRadius * Math.cos(angle),
            y: operation.orbitRadius * Math.sin(angle),
            z: 0,
          };
        };
        const earth = orbitPosition('earth', operation.day, physics);
        const inner = innerPosition(operation.day);
        const endpoint = projectionOnCircle(earth, inner, 4.6);
        objects.earth.position.set(earth.x, earth.y, earth.z);
        objects.innerPlanet.position.set(inner.x, inner.y, inner.z);
        objects.innerPlanet.rotation.y = operation.day * 0.09;
        updateDirectionArrow(objects.earthDirectionArrow, earth);
        updateDirectionArrow(objects.innerPlanetDirectionArrow, inner);
        setLinePoints(objects.innerConjunctionLine, [
          {x: 0, y: 0, z: 0},
          earth,
        ]);
        setLinePoints(objects.innerSightline, [earth, endpoint]);
        objects.innerProjectionMarker.position.set(
          endpoint.x,
          endpoint.y,
          endpoint.z,
        );
        const days = Array.from({length: Math.max(2, operation.count)}, (_, index) =>
          operation.startDay
            + ((operation.endDay - operation.startDay) * index)
              / (Math.max(2, operation.count) - 1),
        );
        setPointPositions(
          objects.innerProjectionHistory,
          days.map((day) => projectionOnCircle(
            orbitPosition('earth', day, physics),
            innerPosition(day),
            4.6,
          )),
        );
        break;
      }
      case 'inner_planet_elongation': {
        const earth = orbitPosition('earth', operation.day, physics);
        const earthRadius = Math.hypot(earth.x, earth.y);
        if (!(operation.orbitRadius > 0)
            || operation.orbitRadius >= earthRadius) {
          throw new Error('inner-planet orbit radius must be inside Earth orbit');
        }
        const radial = {
          x: earth.x / earthRadius,
          y: earth.y / earthRadius,
          z: 0,
        };
        const tangent = {
          x: -radial.y,
          y: radial.x,
          z: 0,
        };
        const side = operation.side === 'morning' ? 1 : -1;
        const along = (operation.orbitRadius * operation.orbitRadius) / earthRadius;
        const across = operation.orbitRadius * Math.sqrt(
          1 - (operation.orbitRadius * operation.orbitRadius)
            / (earthRadius * earthRadius),
        );
        const inner = {
          x: radial.x * along + tangent.x * across * side,
          y: radial.y * along + tangent.y * across * side,
          z: 0,
        };
        objects.earth.position.set(earth.x, earth.y, earth.z);
        objects.innerPlanet.position.set(inner.x, inner.y, inner.z);
        updateDirectionArrow(objects.earthDirectionArrow, earth);
        updateDirectionArrow(objects.innerPlanetDirectionArrow, inner);
        setLinePoints(objects.innerSunRay, [earth, {x: 0, y: 0, z: 0}]);
        setLinePoints(objects.innerElongationRay, [earth, inner]);

        const sunDirection = {
          x: -radial.x,
          y: -radial.y,
          z: 0,
        };
        const planetDirection = {
          x: inner.x - earth.x,
          y: inner.y - earth.y,
          z: 0,
        };
        const planetLength = Math.hypot(planetDirection.x, planetDirection.y);
        planetDirection.x /= planetLength;
        planetDirection.y /= planetLength;
        const startAngle = Math.atan2(sunDirection.y, sunDirection.x);
        const signedAngle = Math.atan2(
          sunDirection.x * planetDirection.y
            - sunDirection.y * planetDirection.x,
          sunDirection.x * planetDirection.x
            + sunDirection.y * planetDirection.y,
        );
        setLinePoints(
          objects.innerElongationArc,
          Array.from({length: 25}, (_, index) => {
            const angle = startAngle + signedAngle * index / 24;
            return {
              x: earth.x + 0.28 * Math.cos(angle),
              y: earth.y + 0.28 * Math.sin(angle),
              z: 0.035,
            };
          }),
        );
        break;
      }
    }
  }
};


export const applyGroupTransforms = (
  objects: SharedSceneObjects,
  transforms: Partial<Record<TransformGroupName, GroupTransform>>,
): void => {
  const groups = transformGroups(objects);
  for (const [name, transform] of Object.entries(transforms) as Array<
    [TransformGroupName, GroupTransform]
  >) {
    const group = groups[name];
    if (transform.position) group.position.fromArray(transform.position);
    if (transform.rotation) group.rotation.set(...transform.rotation);
    if (transform.scale !== undefined) group.scale.setScalar(transform.scale);
  }
};


export const applyEntityOverrides = (
  objects: SharedSceneObjects,
  overrides: Readonly<Record<string, EntityOverride>>,
): void => {
  const entities = entityObjects(objects);
  for (const [name, override] of Object.entries(overrides)) {
    const entity = requireNamedObject(entities, name, 'entity');
    if (override.scale !== undefined) entity.scale.setScalar(override.scale);
    if (override.visible !== undefined) entity.visible = override.visible;
  }
};


export const applyVisibleLayers = (
  objects: SharedSceneObjects,
  visibleLayers: ReadonlySet<string>,
): void => {
  for (const [name, object] of Object.entries(layerObjects(objects))) {
    object.visible = visibleLayers.has(name);
  }
};


export const applyCameraPatch = (
  objects: SharedSceneObjects,
  patch: CameraPatch,
): void => {
  if (patch.position) objects.camera.position.fromArray(patch.position);
  const priorTarget = objects.camera.userData.sequenceTarget as
    | [number, number, number]
    | undefined;
  const target = patch.target ?? priorTarget ?? [0, 0, 0];
  objects.camera.lookAt(...target);
  objects.camera.userData.sequenceTarget = [...target];
  if (patch.fov !== undefined) {
    objects.camera.fov = patch.fov;
    objects.camera.updateProjectionMatrix();
  }
};


export const applyMergedPatch = (
  objects: SharedSceneObjects,
  state: SequenceState,
  patch: SequencePatch,
  physics: Physics,
): void => {
  if (patch.simulationDay === undefined) {
    throw new Error('merged sequence patch requires simulationDay');
  }
  validatePatchLayers(objects, patch);
  applyBaseSimulation(objects, physics, patch.simulationDay);
  applyPersistentEvents(state, patch);
  applyGeometryOperations(objects, physics, patch.geometryOperations ?? []);
  applyEntityOverrides(objects, patch.entityOverrides ?? {});
  applyGroupTransforms(objects, patch.groupTransforms ?? {});
  applyVisibleLayers(objects, state.visibleLayers);
  if (patch.camera) applyCameraPatch(objects, patch.camera);
  for (const layer of patch.hideLayers ?? []) setLayerVisible(objects, layer, false);
};


export const canonicalFrameForOutput = (
  outputFrame: number,
  outputFps: number,
  canonicalFps: number,
  durationFrames: number,
): number => {
  if (!Number.isInteger(outputFrame) || outputFrame < 0) {
    throw new Error('output frame must be a non-negative integer');
  }
  if (!(outputFps > 0) || !(canonicalFps > 0) || !Number.isInteger(durationFrames)
      || durationFrames < 1) {
    throw new Error('frame rates and duration must be positive');
  }
  return Math.min(
    durationFrames - 1,
    Math.floor((outputFrame * canonicalFps) / outputFps),
  );
};


export interface FrameOrderGuard {
  accept(frame: number): void;
}


export const createFrameOrderGuard = (): FrameOrderGuard => {
  let previous = -1;
  return {
    accept(frame: number): void {
      if (!Number.isInteger(frame) || frame < 0 || frame <= previous) {
        throw new Error('output frames must be rendered in increasing order');
      }
      previous = frame;
    },
  };
};


export const mergeSequencePatches = (
  simulationDay: number,
  patches: readonly SequencePatch[],
): SequencePatch => {
  const merged: SequencePatch = {
    simulationDay,
    geometryOperations: [],
    showLayers: [],
    hideLayers: [],
    entityOverrides: {},
    groupTransforms: {},
  };
  for (const patch of patches) {
    merged.geometryOperations!.push(...(patch.geometryOperations ?? []));
    merged.showLayers!.push(...(patch.showLayers ?? []));
    merged.hideLayers!.push(...(patch.hideLayers ?? []));
    for (const [name, override] of Object.entries(patch.entityOverrides ?? {})) {
      merged.entityOverrides![name] = {
        ...merged.entityOverrides![name],
        ...override,
      };
    }
    for (const [name, transform] of Object.entries(patch.groupTransforms ?? {}) as
      Array<[TransformGroupName, GroupTransform]>) {
      merged.groupTransforms![name] = {
        ...merged.groupTransforms![name],
        ...transform,
      };
    }
    if (patch.camera) merged.camera = {...merged.camera, ...patch.camera};
  }
  return merged;
};


export const entityScaleSnapshot = (
  objects: SharedSceneObjects,
): Record<string, number> => Object.fromEntries(
  Object.entries(entityObjects(objects))
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([name, object]) => [name, object.scale.x]),
);


export const cameraSnapshot = (
  objects: SharedSceneObjects,
): SequenceStateSample['camera'] => {
  const target = objects.camera.userData.sequenceTarget as
    | [number, number, number]
    | undefined;
  return {
    position: objects.camera.position.toArray() as [number, number, number],
    target: target ? [...target] : [0, 0, 0],
  };
};


export const stateFingerprint = (
  sample: Omit<SequenceStateSample, 'state_fingerprint'>,
): string => {
  const serialized = JSON.stringify(sample);
  let hash = 0x811c9dc5;
  for (let index = 0; index < serialized.length; index += 1) {
    hash ^= serialized.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return `fnv1a32:${(hash >>> 0).toString(16).padStart(8, '0')}`;
};
