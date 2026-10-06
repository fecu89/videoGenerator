import * as THREE from 'three';

import {orbitPosition} from '../math/circular-orbit.js';
import type {Physics, Vec3} from '../types.js';
import {
  createEarthMaterial,
  createMarsMaterial,
  createSunMaterial,
} from './materials.js';
import {createStarField} from './star-field.js';
import {
  createEclipseSystem,
  type EclipseSceneObjects,
} from './eclipse-system.js';
import {
  createHrDiagramSystem,
  type HrDiagramSceneObjects,
} from './hr-diagram.js';


export interface SharedSceneOptions {
  seed: number;
  width: number;
  height: number;
  earthScale?: number;
  marsScale?: number;
  eclipseEarthScale?: number;
  eclipseMoonScale?: number;
  eclipseSunScale?: number;
}


export interface SharedSceneObjects {
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  orbitGroup: THREE.Group;
  skyGroup: THREE.Group;
  earthOrbitPath: THREE.Line;
  marsOrbitPath: THREE.Line;
  sun: THREE.Mesh;
  earth: THREE.Mesh;
  mars: THREE.Mesh;
  innerPlanetGroup: THREE.Group;
  innerPlanet: THREE.Mesh;
  innerPlanetDirectionArrow: THREE.ArrowHelper;
  innerConjunctionLine: THREE.Line;
  innerSightline: THREE.Line;
  innerProjectionMarker: THREE.Mesh;
  innerProjectionHistory: THREE.Points;
  innerSunRay: THREE.Line;
  innerElongationRay: THREE.Line;
  innerElongationArc: THREE.Line;
  sightline: THREE.Line;
  projectionMarker: THREE.Mesh;
  starWall: THREE.Points;
  stars: THREE.Points;
  skyMarker: THREE.Mesh;
  skyTrail: THREE.Points;
  earthTrail: THREE.Points;
  marsTrail: THREE.Points;
  projectionHistory: THREE.Points;
  sightlineHistory: THREE.Group;
  earthDirectionArrow: THREE.ArrowHelper;
  marsDirectionArrow: THREE.ArrowHelper;
  stationMarkerStart: THREE.Mesh;
  stationMarkerEnd: THREE.Mesh;
  eclipse: EclipseSceneObjects;
  hr: HrDiagramSceneObjects;
}


export const resetSharedSceneGroupTransforms = (
  objects: Pick<SharedSceneObjects, 'orbitGroup' | 'skyGroup'>,
): void => {
  for (const group of [objects.orbitGroup, objects.skyGroup]) {
    group.position.set(0, 0, 0);
    group.rotation.set(0, 0, 0);
    group.scale.set(1, 1, 1);
  }
};


const circleLine = (radius: number, color: number, opacity: number): THREE.Line => {
  const points = Array.from({length: 193}, (_, index) => {
    const angle = (index / 192) * Math.PI * 2;
    return new THREE.Vector3(radius * Math.cos(angle), radius * Math.sin(angle), 0);
  });
  return new THREE.Line(
    new THREE.BufferGeometry().setFromPoints(points),
    new THREE.LineBasicMaterial({color, transparent: true, opacity}),
  );
};


const dynamicPoints = (color: number, size: number): THREE.Points =>
  new THREE.Points(
    new THREE.BufferGeometry().setAttribute(
      'position',
      new THREE.Float32BufferAttribute([], 3),
    ),
    new THREE.PointsMaterial({
      color,
      size,
      sizeAttenuation: true,
      transparent: true,
      opacity: 0.85,
      depthWrite: false,
    }),
  );


const dynamicLine = (color: number, opacity: number): THREE.Line =>
  new THREE.Line(
    new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(),
      new THREE.Vector3(1, 0, 0),
    ]),
    new THREE.LineBasicMaterial({color, transparent: true, opacity}),
  );


const stationRing = (color: number): THREE.Mesh =>
  new THREE.Mesh(
    new THREE.RingGeometry(0.09, 0.14, 32),
    new THREE.MeshBasicMaterial({
      color,
      transparent: true,
      opacity: 0.95,
      side: THREE.DoubleSide,
    }),
  );


const createStarWall = (seed: number, radius = 4.6): THREE.Points => {
  const positions: number[] = [];
  let state = seed >>> 0;
  const random = (): number => {
    state = (1664525 * state + 1013904223) >>> 0;
    return state / 4294967296;
  };
  for (let index = 0; index < 260; index += 1) {
    const angle = (index / 260) * Math.PI * 2;
    const jitter = (random() - 0.5) * 0.18;
    positions.push(
      (radius + jitter) * Math.cos(angle),
      (radius + jitter) * Math.sin(angle),
      (random() - 0.5) * 0.35,
    );
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  return new THREE.Points(
    geometry,
    new THREE.PointsMaterial({
      color: 0xcbdcff,
      size: 0.025,
      transparent: true,
      opacity: 0.7,
      depthWrite: false,
    }),
  );
};


export const createSharedScene = (options: SharedSceneOptions): SharedSceneObjects => {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x020611);
  const camera = new THREE.PerspectiveCamera(
    38,
    options.width / options.height,
    0.01,
    40,
  );
  camera.position.set(0, 0, 5.2);
  camera.lookAt(0, 0, 0);

  scene.add(new THREE.AmbientLight(0x86a0c8, 0.72));
  const sunLight = new THREE.PointLight(0xfff0cf, 18, 10, 1.2);
  sunLight.position.set(0, 0, 0.18);
  scene.add(sunLight);

  const stars = createStarField(options.seed);
  scene.add(stars);

  const orbitGroup = new THREE.Group();
  const skyGroup = new THREE.Group();
  scene.add(orbitGroup, skyGroup);
  const eclipse = createEclipseSystem({
    earthScale: options.eclipseEarthScale ?? 1,
    moonScale: options.eclipseMoonScale ?? 1,
    sunScale: options.eclipseSunScale ?? 1,
  });
  scene.add(eclipse.group);
  const hr = createHrDiagramSystem();
  scene.add(hr.group);

  const sun = new THREE.Mesh(
    new THREE.SphereGeometry(0.13, 32, 24),
    createSunMaterial(),
  );
  const earth = new THREE.Mesh(
    new THREE.SphereGeometry(options.earthScale ?? 0.075, 32, 24),
    createEarthMaterial(),
  );
  const mars = new THREE.Mesh(
    new THREE.SphereGeometry(options.marsScale ?? 0.055, 32, 24),
    createMarsMaterial(),
  );
  const earthOrbitPath = circleLine(1, 0x55708d, 0.5);
  const marsOrbitPath = circleLine(1.52, 0x765f59, 0.46);
  orbitGroup.add(sun, earthOrbitPath, marsOrbitPath);
  orbitGroup.add(earth, mars);

  const innerPlanetGroup = new THREE.Group();
  const innerPlanetOrbitPath = circleLine(0.72, 0x9f8a55, 0.58);
  const innerPlanet = new THREE.Mesh(
    new THREE.SphereGeometry(0.062, 32, 24),
    new THREE.MeshStandardMaterial({
      color: 0xe0bd72,
      roughness: 0.78,
      metalness: 0.02,
    }),
  );
  const innerPlanetDirectionArrow = new THREE.ArrowHelper(
    new THREE.Vector3(0, 1, 0),
    new THREE.Vector3(),
    0.31,
    0xf5ce78,
    0.12,
    0.08,
  );
  const innerConjunctionLine = dynamicLine(0xffd166, 0.72);
  const innerSightline = dynamicLine(0x8bdcf2, 0.88);
  const innerProjectionMarker = new THREE.Mesh(
    new THREE.SphereGeometry(0.065, 20, 16),
    new THREE.MeshBasicMaterial({color: 0xffd166}),
  );
  const innerProjectionHistory = dynamicPoints(0xffd166, 0.075);
  const innerSunRay = dynamicLine(0xffb347, 0.9);
  const innerElongationRay = dynamicLine(0x8bdcf2, 0.92);
  const innerElongationArc = new THREE.Line(
    new THREE.BufferGeometry().setFromPoints(
      Array.from({length: 25}, () => new THREE.Vector3()),
    ),
    new THREE.LineBasicMaterial({
      color: 0xffd166,
      transparent: true,
      opacity: 0.96,
    }),
  );
  innerPlanetGroup.add(
    innerPlanetOrbitPath,
    innerPlanet,
    innerPlanetDirectionArrow,
    innerConjunctionLine,
    innerSightline,
    innerProjectionMarker,
    innerProjectionHistory,
    innerSunRay,
    innerElongationRay,
    innerElongationArc,
  );
  orbitGroup.add(innerPlanetGroup);

  const sightline = new THREE.Line(
    new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(),
      new THREE.Vector3(1, 0, 0),
    ]),
    new THREE.LineBasicMaterial({color: 0xa9d7e8, transparent: true, opacity: 0.82}),
  );
  orbitGroup.add(sightline);

  const projectionMarker = new THREE.Mesh(
    new THREE.SphereGeometry(0.065, 20, 16),
    new THREE.MeshBasicMaterial({color: 0xff926f}),
  );
  orbitGroup.add(projectionMarker);

  const starWall = createStarWall(options.seed + 17);
  orbitGroup.add(starWall);

  const earthTrail = dynamicPoints(0x75bfff, 0.055);
  const marsTrail = dynamicPoints(0xef865e, 0.05);
  const projectionHistory = dynamicPoints(0xffb38f, 0.075);
  const sightlineHistory = new THREE.Group();
  for (let index = 0; index < 6; index += 1) {
    const line = dynamicLine(0x8bdcf2, 0.28 + index * 0.1);
    line.visible = false;
    sightlineHistory.add(line);
  }
  const earthDirectionArrow = new THREE.ArrowHelper(
    new THREE.Vector3(0, 1, 0),
    new THREE.Vector3(),
    0.34,
    0x7fc8ff,
    0.13,
    0.085,
  );
  const marsDirectionArrow = new THREE.ArrowHelper(
    new THREE.Vector3(0, 1, 0),
    new THREE.Vector3(),
    0.34,
    0xff9470,
    0.13,
    0.085,
  );
  orbitGroup.add(
    earthTrail,
    marsTrail,
    projectionHistory,
    sightlineHistory,
    earthDirectionArrow,
    marsDirectionArrow,
  );

  const skyMarker = new THREE.Mesh(
    new THREE.SphereGeometry(0.082, 20, 16),
    new THREE.MeshBasicMaterial({color: 0xf07850}),
  );
  const skyTrail = dynamicPoints(0xffa080, 0.09);
  const stationMarkerStart = stationRing(0x77d8ff);
  const stationMarkerEnd = stationRing(0xffd166);
  skyGroup.add(
    skyTrail,
    skyMarker,
    stationMarkerStart,
    stationMarkerEnd,
  );

  return {
    scene,
    camera,
    orbitGroup,
    skyGroup,
    earthOrbitPath,
    marsOrbitPath,
    sun,
    earth,
    mars,
    innerPlanetGroup,
    innerPlanet,
    innerPlanetDirectionArrow,
    innerConjunctionLine,
    innerSightline,
    innerProjectionMarker,
    innerProjectionHistory,
    innerSunRay,
    innerElongationRay,
    innerElongationArc,
    sightline,
    projectionMarker,
    starWall,
    stars,
    skyMarker,
    skyTrail,
    earthTrail,
    marsTrail,
    projectionHistory,
    sightlineHistory,
    earthDirectionArrow,
    marsDirectionArrow,
    stationMarkerStart,
    stationMarkerEnd,
    eclipse,
    hr,
  };
};


export const setLinePoints = (
  line: THREE.Line,
  points: readonly Vec3[],
): void => {
  line.geometry.setFromPoints(
    points.map((point) => new THREE.Vector3(point.x, point.y, point.z)),
  );
  line.geometry.attributes.position!.needsUpdate = true;
};


export const setPointPositions = (
  points: THREE.Points,
  positions: readonly Vec3[],
): void => {
  const flattened = positions.flatMap((position) => [position.x, position.y, position.z]);
  points.geometry.setAttribute(
    'position',
    new THREE.Float32BufferAttribute(flattened, 3),
  );
  points.geometry.attributes.position!.needsUpdate = true;
};


export const positionPlanets = (
  objects: SharedSceneObjects,
  physics: Physics,
  day: number,
): void => {
  const earth = orbitPosition('earth', day, physics);
  const mars = orbitPosition('mars', day, physics);
  objects.earth.position.set(earth.x, earth.y, earth.z);
  objects.mars.position.set(mars.x, mars.y, mars.z);
  objects.earth.rotation.y = day * 0.12;
  objects.mars.rotation.y = day * 0.07;
};
