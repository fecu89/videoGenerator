import * as THREE from 'three';

import type {Vec3} from '../types.js';
import {lunarOrbitPosition} from '../math/eclipse.js';
import {
  createEarthMaterial,
  createSunMaterial,
} from './materials.js';


export interface EclipseSceneOptions {
  earthScale?: number;
  moonScale?: number;
  sunScale?: number;
}


export interface EclipseSceneObjects {
  group: THREE.Group;
  sun: THREE.Mesh;
  earth: THREE.Mesh;
  moon: THREE.Mesh;
  eclipticPlane: THREE.Mesh;
  lunarPlane: THREE.Mesh;
  moonOrbit: THREE.Line;
  nodeLine: THREE.Line;
  moonShadow: THREE.Line;
  earthShadow: THREE.Line;
  moonUmbra: THREE.LineSegments;
  earthUmbra: THREE.LineSegments;
  moonPenumbra: THREE.LineSegments;
  earthPenumbra: THREE.LineSegments;
  moonUmbraFill: THREE.Mesh;
  earthUmbraFill: THREE.Mesh;
  moonPenumbraFill: THREE.Mesh;
  earthPenumbraFill: THREE.Mesh;
  earthPenumbraSpot: THREE.Mesh;
  earthUmbraSpot: THREE.Mesh;
  shadowHitMarker: THREE.Mesh;
  phaseMarkers: THREE.Group;
  sunLight: THREE.PointLight;
}


const line = (color: number, opacity = 0.8): THREE.Line =>
  new THREE.Line(
    new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(),
      new THREE.Vector3(1, 0, 0),
    ]),
    new THREE.LineBasicMaterial({color, transparent: true, opacity}),
  );


const lineSegments = (color: number, opacity = 0.42): THREE.LineSegments =>
  new THREE.LineSegments(
    new THREE.BufferGeometry().setFromPoints(
      Array.from({length: 8}, () => new THREE.Vector3()),
    ),
    new THREE.LineBasicMaterial({color, transparent: true, opacity}),
  );


const shadowVolume = (
  endToStartRadiusRatio: number,
  color: number,
  opacity: number,
): THREE.Mesh =>
  new THREE.Mesh(
    new THREE.CylinderGeometry(
      endToStartRadiusRatio,
      1,
      1,
      32,
      1,
      true,
    ),
    new THREE.MeshBasicMaterial({
      color,
      transparent: true,
      opacity,
      side: THREE.DoubleSide,
      depthWrite: false,
    }),
  );


const orbitalLine = (
  radius: number,
  inclinationDegrees: number,
  color: number,
  opacity: number,
): THREE.Line => {
  const points = Array.from({length: 193}, (_, index) => {
    const point = lunarOrbitPosition(
      (index / 192) * 360,
      radius,
      inclinationDegrees,
    );
    return new THREE.Vector3(point.x, point.y, point.z);
  });
  return new THREE.Line(
    new THREE.BufferGeometry().setFromPoints(points),
    new THREE.LineBasicMaterial({color, transparent: true, opacity}),
  );
};


const plane = (color: number, opacity: number): THREE.Mesh =>
  new THREE.Mesh(
    new THREE.CircleGeometry(3.55, 96),
    new THREE.MeshBasicMaterial({
      color,
      transparent: true,
      opacity,
      side: THREE.DoubleSide,
      depthWrite: false,
    }),
  );


const earthShadowSpot = (
  name: string,
  color: number,
  opacity: number,
  renderOrder: number,
): THREE.Mesh => {
  const spot = new THREE.Mesh(
    new THREE.CircleGeometry(1, 64),
    new THREE.MeshBasicMaterial({
      color,
      transparent: true,
      opacity,
      side: THREE.DoubleSide,
      depthTest: false,
      depthWrite: false,
    }),
  );
  spot.name = name;
  spot.renderOrder = renderOrder;
  spot.visible = false;
  return spot;
};


const phaseMarkers = (): THREE.Group => {
  const group = new THREE.Group();
  for (const longitude of [0, 90, 180, 270]) {
    const point = lunarOrbitPosition(longitude, 2.2, 5);
    const marker = new THREE.Mesh(
      new THREE.SphereGeometry(0.035, 16, 12),
      new THREE.MeshBasicMaterial({color: 0x9fdcff, transparent: true, opacity: 0.72}),
    );
    marker.position.set(point.x, point.y, point.z);
    group.add(marker);
  }
  return group;
};


export const createEclipseSystem = (
  options: EclipseSceneOptions = {},
): EclipseSceneObjects => {
  const group = new THREE.Group();
  group.visible = false;

  const sun = new THREE.Mesh(
    new THREE.SphereGeometry(0.48 * (options.sunScale ?? 1), 40, 28),
    createSunMaterial(),
  );
  const earth = new THREE.Mesh(
    new THREE.SphereGeometry(0.23 * (options.earthScale ?? 1), 40, 28),
    createEarthMaterial(),
  );
  const moon = new THREE.Mesh(
    new THREE.SphereGeometry(0.12 * (options.moonScale ?? 1), 32, 24),
    new THREE.MeshStandardMaterial({
      color: 0xa9acb2,
      roughness: 0.96,
      emissive: 0x101116,
      emissiveIntensity: 0.08,
    }),
  );

  const eclipticPlane = plane(0x1c4e75, 0.15);
  const lunarPlane = plane(0x39bed8, 0.13);
  lunarPlane.rotation.x = THREE.MathUtils.degToRad(5);
  const moonOrbit = orbitalLine(2.2, 5, 0x78d9e8, 0.78);
  const nodeLine = line(0xffc769, 0.9);
  nodeLine.geometry.setFromPoints([
    new THREE.Vector3(-3.55, 0, 0),
    new THREE.Vector3(3.55, 0, 0),
  ]);

  const moonShadow = line(0x86d8f2, 0.86);
  const earthShadow = line(0x778ba8, 0.82);
  const moonUmbra = lineSegments(0x45667f, 0.48);
  const earthUmbra = lineSegments(0x42536c, 0.48);
  const moonPenumbra = lineSegments(0x86b6ca, 0.42);
  moonPenumbra.name = 'moon-penumbra-outline';
  const earthPenumbra = lineSegments(0x8397b0, 0.42);
  earthPenumbra.name = 'earth-penumbra-outline';
  const moonUmbraFill = shadowVolume(0.25, 0x315c78, 0.3);
  const earthUmbraFill = shadowVolume(0.14 / 0.23, 0x33465f, 0.25);
  const moonPenumbraFill = shadowVolume(2.4, 0x527d91, 0.12);
  moonPenumbraFill.name = 'moon-penumbra-fill';
  const earthPenumbraFill = shadowVolume(0.42 / 0.23, 0x566b83, 0.11);
  earthPenumbraFill.name = 'earth-penumbra-fill';
  const earthPenumbraSpot = earthShadowSpot(
    'earth-penumbra-spot',
    0x47657c,
    0.58,
    20,
  );
  const earthUmbraSpot = earthShadowSpot(
    'earth-umbra-spot',
    0x07111d,
    0.92,
    21,
  );
  const shadowHitMarker = new THREE.Mesh(
    new THREE.RingGeometry(0.25, 0.29, 48),
    new THREE.MeshBasicMaterial({
      color: 0xffcf70,
      transparent: true,
      opacity: 0.9,
      side: THREE.DoubleSide,
    }),
  );
  shadowHitMarker.visible = false;

  const markers = phaseMarkers();
  const sunLight = new THREE.PointLight(0xfff0cf, 34, 24, 1.1);
  group.add(
    eclipticPlane,
    lunarPlane,
    moonOrbit,
    nodeLine,
    moonShadow,
    earthShadow,
    moonUmbra,
    earthUmbra,
    moonPenumbra,
    earthPenumbra,
    moonPenumbraFill,
    earthPenumbraFill,
    moonUmbraFill,
    earthUmbraFill,
    earthPenumbraSpot,
    earthUmbraSpot,
    markers,
    sun,
    earth,
    moon,
    shadowHitMarker,
    sunLight,
  );

  return {
    group,
    sun,
    earth,
    moon,
    eclipticPlane,
    lunarPlane,
    moonOrbit,
    nodeLine,
    moonShadow,
    earthShadow,
    moonUmbra,
    earthUmbra,
    moonPenumbra,
    earthPenumbra,
    moonUmbraFill,
    earthUmbraFill,
    moonPenumbraFill,
    earthPenumbraFill,
    earthPenumbraSpot,
    earthUmbraSpot,
    shadowHitMarker,
    phaseMarkers: markers,
    sunLight,
  };
};


export const setDynamicLine = (
  target: THREE.Line,
  points: readonly Vec3[],
): void => {
  target.geometry.setFromPoints(
    points.map((point) => new THREE.Vector3(point.x, point.y, point.z)),
  );
  target.geometry.attributes.position!.needsUpdate = true;
};


export const setShadowOutline = (
  target: THREE.LineSegments,
  start: Vec3,
  end: Vec3,
  startRadius: number,
  endRadius: number,
): void => {
  const direction = new THREE.Vector3(
    end.x - start.x,
    end.y - start.y,
    end.z - start.z,
  ).normalize();
  const reference = Math.abs(direction.z) < 0.9
    ? new THREE.Vector3(0, 0, 1)
    : new THREE.Vector3(0, 1, 0);
  const side = new THREE.Vector3().crossVectors(direction, reference).normalize();
  const vertical = new THREE.Vector3().crossVectors(direction, side).normalize();
  const startVector = new THREE.Vector3(start.x, start.y, start.z);
  const endVector = new THREE.Vector3(end.x, end.y, end.z);
  const points: THREE.Vector3[] = [];
  for (const axis of [side, vertical]) {
    points.push(
      startVector.clone().addScaledVector(axis, startRadius),
      endVector.clone().addScaledVector(axis, endRadius),
      startVector.clone().addScaledVector(axis, -startRadius),
      endVector.clone().addScaledVector(axis, -endRadius),
    );
  }
  target.geometry.setFromPoints(points);
  target.geometry.attributes.position!.needsUpdate = true;
};


export const setShadowVolume = (
  target: THREE.Mesh,
  start: Vec3,
  end: Vec3,
  startRadius: number,
): void => {
  const direction = new THREE.Vector3(
    end.x - start.x,
    end.y - start.y,
    end.z - start.z,
  );
  const distance = direction.length();
  if (distance === 0) throw new Error('shadow volume needs distinct endpoints');
  direction.normalize();
  target.position.set(
    (start.x + end.x) / 2,
    (start.y + end.y) / 2,
    (start.z + end.z) / 2,
  );
  target.scale.set(startRadius, distance, startRadius);
  target.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), direction);
};
