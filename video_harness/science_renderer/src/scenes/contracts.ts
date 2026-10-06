import * as THREE from 'three';

import {apparentLongitude} from '../math/retrograde.js';
import {orbitPosition} from '../math/circular-orbit.js';
import {normalize, subtract} from '../math/sightline.js';
import type {Physics, Vec3} from '../types.js';
import {
  positionPlanets,
  setLinePoints,
  setPointPositions,
  type SharedSceneObjects,
} from '../visuals/solar-system.js';


export type TemplateName =
  | 'sky-orbit-reveal'
  | 'retrograde-track'
  | 'moving-observer'
  | 'sightline-angle'
  | 'speed-comparison'
  | 'earth-overtake'
  | 'projection-proof'
  | 'return-to-direct'
  | 'same-direction-arrows'
  | 'local-overtake'
  | 'cumulative-sightlines'
  | 'stationary-points'
  | 'monthly-cycle-hook'
  | 'top-view-alignment'
  | 'tilt-reveal'
  | 'new-moon-miss'
  | 'full-moon-miss'
  | 'node-crossing'
  | 'solar-eclipse-alignment'
  | 'lunar-eclipse-alignment'
  | 'two-condition-summary';


export interface EclipseControllerConfig {
  parameters: Record<string, unknown>;
  rendererOptions: Record<string, unknown>;
}

export interface ControllerContext {
  objects: SharedSceneObjects;
  physics: Physics;
  simulationDayStart: number;
  simulationDayEnd: number;
  camera?: {
    projection: 'perspective' | 'orthographic';
    framing: string;
    movement: string;
    position?: [number, number, number];
    target?: [number, number, number];
  };
  rendererOptions?: Record<string, unknown>;
  eclipse?: EclipseControllerConfig;
}

export interface SceneController {
  update(progress: number, simulationDay: number): void;
}

export type SceneFactory = (context: ControllerContext) => SceneController;


export const clampProgress = (progress: number): number =>
  Math.min(1, Math.max(0, progress));


export const easeInOut = (progress: number): number => {
  const value = clampProgress(progress);
  return value * value * (3 - 2 * value);
};


export const setCamera = (
  objects: SharedSceneObjects,
  position: Vec3,
  target: Vec3 = {x: 0, y: 0, z: 0},
): void => {
  objects.camera.position.set(position.x, position.y, position.z);
  objects.camera.lookAt(target.x, target.y, target.z);
};


export const resetVisibility = (objects: SharedSceneObjects): void => {
  objects.orbitGroup.visible = true;
  objects.skyGroup.visible = false;
  objects.sightline.visible = true;
  objects.projectionMarker.visible = false;
  objects.starWall.visible = false;
  objects.earthTrail.visible = false;
  objects.marsTrail.visible = false;
  objects.projectionHistory.visible = false;
  objects.sightlineHistory.visible = false;
  for (const child of objects.sightlineHistory.children) child.visible = false;
  objects.earthDirectionArrow.visible = false;
  objects.marsDirectionArrow.visible = false;
  objects.skyMarker.visible = false;
  objects.skyTrail.visible = false;
  objects.stationMarkerStart.visible = false;
  objects.stationMarkerEnd.visible = false;
  objects.eclipse.group.visible = false;
};


export const updateOrbitAndSightline = (
  objects: SharedSceneObjects,
  physics: Physics,
  day: number,
  extendToProjection = false,
): Vec3 => {
  positionPlanets(objects, physics, day);
  const earth = orbitPosition('earth', day, physics);
  const mars = orbitPosition('mars', day, physics);
  const endpoint = extendToProjection
    ? projectionOnCircle(earth, mars, 4.6)
    : mars;
  setLinePoints(objects.sightline, [earth, endpoint]);
  if (extendToProjection) {
    objects.projectionMarker.position.set(endpoint.x, endpoint.y, endpoint.z);
  }
  return endpoint;
};


export const projectionOnCircle = (
  earth: Vec3,
  mars: Vec3,
  radius: number,
): Vec3 => {
  const direction = normalize(subtract(mars, earth));
  const dot = earth.x * direction.x + earth.y * direction.y;
  const earthSquared = earth.x * earth.x + earth.y * earth.y;
  const distance = -dot + Math.sqrt(dot * dot - earthSquared + radius * radius);
  return {
    x: earth.x + direction.x * distance,
    y: earth.y + direction.y * distance,
    z: 0,
  };
};


export const skyTrackPosition = (
  day: number,
  physics: Physics,
): Vec3 => {
  const longitude = apparentLongitude(day, physics);
  const center = apparentLongitude(physics.oppositionDay, physics);
  const relative = Math.atan2(
    Math.sin(longitude - center),
    Math.cos(longitude - center),
  );
  return {
    x: -relative * 5.4,
    y: 0.08 * Math.sin(day / 18),
    z: 0,
  };
};


const unwrapLongitudes = (values: readonly number[]): number[] => {
  if (values.length === 0) return [];
  const result = [values[0]!];
  for (let index = 1; index < values.length; index += 1) {
    const previousRaw = values[index - 1]!;
    const currentRaw = values[index]!;
    const difference = Math.atan2(
      Math.sin(currentRaw - previousRaw),
      Math.cos(currentRaw - previousRaw),
    );
    result.push(result[index - 1]! + difference);
  }
  return result;
};


export const updateSkyTrack = (
  objects: SharedSceneObjects,
  physics: Physics,
  startDay: number,
  endDay: number,
  count: number,
): void => {
  const days = Array.from({length: Math.max(2, count)}, (_, index) =>
    startDay + ((endDay - startDay) * index) / (Math.max(2, count) - 1),
  );
  const longitudes = unwrapLongitudes(
    days.map((day) => apparentLongitude(day, physics)),
  );
  const center = apparentLongitude(physics.oppositionDay, physics);
  const positions = days.map((day, index) => ({
    x: -(longitudes[index]! - center) * 5.4,
    y: 0.08 * Math.sin(day / 18),
    z: 0,
  }));
  setPointPositions(objects.skyTrail, positions);
  const last = positions.at(-1) ?? {x: 0, y: 0, z: 0};
  objects.skyMarker.position.set(last.x, last.y, last.z);
};


export const updateMotionTrails = (
  objects: SharedSceneObjects,
  physics: Physics,
  startDay: number,
  endDay: number,
  count = 12,
): void => {
  const days = Array.from({length: count}, (_, index) =>
    startDay + ((endDay - startDay) * index) / (count - 1),
  );
  setPointPositions(
    objects.earthTrail,
    days.map((day) => orbitPosition('earth', day, physics)),
  );
  setPointPositions(
    objects.marsTrail,
    days.map((day) => orbitPosition('mars', day, physics)),
  );
};


export const updateCumulativeSightlines = (
  objects: SharedSceneObjects,
  physics: Physics,
  startDay: number,
  endDay: number,
  revealedCount = objects.sightlineHistory.children.length,
): void => {
  const children = objects.sightlineHistory.children as THREE.Line[];
  const visibleCount = Math.min(
    children.length,
    Math.max(0, Math.floor(revealedCount)),
  );
  const endpoints: Vec3[] = [];
  for (let index = 0; index < children.length; index += 1) {
    const line = children[index]!;
    if (index >= visibleCount) {
      line.visible = false;
      continue;
    }
    const day = startDay + ((endDay - startDay) * index) / Math.max(1, children.length - 1);
    const earth = orbitPosition('earth', day, physics);
    const mars = orbitPosition('mars', day, physics);
    const endpoint = projectionOnCircle(earth, mars, 4.6);
    setLinePoints(line, [earth, endpoint]);
    line.visible = true;
    endpoints.push(endpoint);
  }
  objects.sightlineHistory.visible = true;
  setPointPositions(objects.projectionHistory, endpoints);
  objects.projectionHistory.visible = true;
};


export const updateProjectionHistory = (
  objects: SharedSceneObjects,
  physics: Physics,
  startDay: number,
  endDay: number,
  count = 24,
): void => {
  const days = Array.from({length: count}, (_, index) =>
    startDay + ((endDay - startDay) * index) / Math.max(1, count - 1),
  );
  setPointPositions(
    objects.projectionHistory,
    days.map((day) => {
      const earth = orbitPosition('earth', day, physics);
      const mars = orbitPosition('mars', day, physics);
      return projectionOnCircle(earth, mars, 4.6);
    }),
  );
  objects.projectionHistory.visible = true;
};


export const updateDirectionArrow = (
  arrow: THREE.ArrowHelper,
  position: Vec3,
): void => {
  arrow.position.set(position.x, position.y, position.z + 0.03);
  arrow.setDirection(
    new THREE.Vector3(-position.y, position.x, 0).normalize(),
  );
  arrow.visible = true;
};


export const interpolateVector = (
  from: Vec3,
  to: Vec3,
  progress: number,
): Vec3 => {
  const eased = easeInOut(progress);
  return {
    x: THREE.MathUtils.lerp(from.x, to.x, eased),
    y: THREE.MathUtils.lerp(from.y, to.y, eased),
    z: THREE.MathUtils.lerp(from.z, to.z, eased),
  };
};
