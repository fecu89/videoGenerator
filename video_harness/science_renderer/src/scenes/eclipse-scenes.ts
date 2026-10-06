import * as THREE from 'three';

import {
  lunarOrbitPosition,
  sunPosition,
} from '../math/eclipse.js';
import type {Vec3} from '../types.js';
import {
  setDynamicLine,
  setShadowOutline,
  setShadowVolume,
} from '../visuals/eclipse-system.js';
import {
  easeInOut,
  interpolateVector,
  resetVisibility,
  setCamera,
  type ControllerContext,
  type SceneController,
  type SceneFactory,
} from './contracts.js';


const numberParameter = (
  context: ControllerContext,
  name: string,
  fallback: number,
): number => {
  const value = context.eclipse?.parameters[name];
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
};


const stringParameter = (
  context: ControllerContext,
  name: string,
  fallback: string,
): string => {
  const value = context.eclipse?.parameters[name];
  return typeof value === 'string' ? value : fallback;
};


const vector = (from: Vec3, to: Vec3): Vec3 => ({
  x: to.x - from.x,
  y: to.y - from.y,
  z: to.z - from.z,
});


const normalize = (value: Vec3): Vec3 => {
  const magnitude = Math.hypot(value.x, value.y, value.z);
  if (magnitude === 0) throw new Error('cannot normalize zero vector');
  return {x: value.x / magnitude, y: value.y / magnitude, z: value.z / magnitude};
};


const extend = (origin: Vec3, direction: Vec3, distance: number): Vec3 => ({
  x: origin.x + direction.x * distance,
  y: origin.y + direction.y * distance,
  z: origin.z + direction.z * distance,
});


const configureEclipseScene = (context: ControllerContext): void => {
  resetVisibility(context.objects);
  const eclipse = context.objects.eclipse;
  context.objects.orbitGroup.visible = false;
  context.objects.camera.up.set(0, 1, 0);
  eclipse.group.visible = true;
  eclipse.sun.visible = true;
  eclipse.earth.visible = true;
  eclipse.moon.visible = true;
  eclipse.eclipticPlane.visible = false;
  eclipse.lunarPlane.visible = false;
  eclipse.moonOrbit.visible = false;
  eclipse.nodeLine.visible = false;
  eclipse.moonShadow.visible = false;
  eclipse.earthShadow.visible = false;
  eclipse.moonUmbra.visible = false;
  eclipse.earthUmbra.visible = false;
  eclipse.moonPenumbra.visible = false;
  eclipse.earthPenumbra.visible = false;
  eclipse.moonUmbraFill.visible = false;
  eclipse.earthUmbraFill.visible = false;
  eclipse.moonPenumbraFill.visible = false;
  eclipse.earthPenumbraFill.visible = false;
  eclipse.earthPenumbraSpot.visible = false;
  eclipse.earthUmbraSpot.visible = false;
  eclipse.shadowHitMarker.visible = false;
  eclipse.phaseMarkers.visible = false;
  eclipse.sun.scale.setScalar(1);
  eclipse.earth.scale.setScalar(1);
  eclipse.moon.scale.setScalar(1);
  const moonMaterial = eclipse.moon.material as THREE.MeshStandardMaterial;
  moonMaterial.color.setHex(0xa9acb2);
  moonMaterial.emissive.setHex(0x101116);
  moonMaterial.emissiveIntensity = 0.08;
};


const setMildlyEllipticalMoonOrbit = (
  context: ControllerContext,
): {semiMajor: number; eccentricity: number} => {
  const eclipse = context.objects.eclipse;
  const semiMajor = numberParameter(context, 'moon_orbit_radius', 2.2);
  const baseEccentricity = numberParameter(
    context,
    'moon_orbit_eccentricity',
    0.0549,
  );
  const emphasis = numberParameter(
    context,
    'distance_difference_visual_emphasis',
    1,
  );
  const eccentricity = THREE.MathUtils.clamp(
    baseEccentricity * emphasis,
    0,
    0.22,
  );
  const semiMinor = semiMajor * Math.sqrt(1 - eccentricity ** 2);
  const inclination = THREE.MathUtils.degToRad(numberParameter(
    context,
    'moon_orbit_inclination_degrees',
    5,
  ));
  const points = Array.from({length: 193}, (_, index) => {
    const angle = (index / 192) * Math.PI * 2;
    const planarY = semiMinor * Math.sin(angle);
    return new THREE.Vector3(
      semiMajor * (Math.cos(angle) + eccentricity),
      planarY * Math.cos(inclination),
      planarY * Math.sin(inclination),
    );
  });
  eclipse.moonOrbit.geometry.setFromPoints(points);
  eclipse.moonOrbit.geometry.attributes.position!.needsUpdate = true;
  return {semiMajor, eccentricity};
};


const setMoonOnEllipticalOrbit = (
  context: ControllerContext,
  angle: number,
  semiMajor: number,
  eccentricity: number,
): void => {
  const semiMinor = semiMajor * Math.sqrt(1 - eccentricity ** 2);
  const inclination = THREE.MathUtils.degToRad(numberParameter(
    context,
    'moon_orbit_inclination_degrees',
    5,
  ));
  const planarY = semiMinor * Math.sin(angle);
  context.objects.eclipse.moon.position.set(
    semiMajor * (Math.cos(angle) + eccentricity),
    planarY * Math.cos(inclination),
    planarY * Math.sin(inclination),
  );
};


const setEarthSurfaceShadow = (
  context: ControllerContext,
  progress: number,
): void => {
  const eclipse = context.objects.eclipse;
  const surfaceRadius = 0.237 * eclipse.earth.scale.x;
  const surfaceY = THREE.MathUtils.lerp(-0.07, 0.07, easeInOut(progress));
  const surfaceZ = 0.025 * Math.sin(progress * Math.PI);
  const surfaceX = Math.sqrt(Math.max(
    0,
    surfaceRadius ** 2 - surfaceY ** 2 - surfaceZ ** 2,
  ));
  const normal = new THREE.Vector3(surfaceX, surfaceY, surfaceZ).normalize();
  const position = normal.clone().multiplyScalar(surfaceRadius);
  const orientation = new THREE.Quaternion().setFromUnitVectors(
    new THREE.Vector3(0, 0, 1),
    normal,
  );
  for (const [spot, radius] of [
    [eclipse.earthPenumbraSpot, 0.105],
    [eclipse.earthUmbraSpot, 0.032],
  ] as const) {
    spot.visible = true;
    spot.position.copy(position);
    spot.quaternion.copy(orientation);
    spot.scale.setScalar(radius);
  }
};


const tintMoon = (
  context: ControllerContext,
  progress: number,
  startColor: number,
  endColor: number,
): void => {
  const material = context.objects.eclipse.moon.material as THREE.MeshStandardMaterial;
  material.color.lerpColors(
    new THREE.Color(startColor),
    new THREE.Color(endColor),
    easeInOut(progress),
  );
  material.emissive.lerpColors(
    new THREE.Color(0x101116),
    new THREE.Color(0x2b0904),
    easeInOut(progress),
  );
  material.emissiveIntensity = THREE.MathUtils.lerp(0.08, 0.28, progress);
};


const tintMoonFromEarthShadowGeometry = (
  context: ControllerContext,
): void => {
  const eclipse = context.objects.eclipse;
  const moonRadius = 0.12 * eclipse.moon.scale.x;
  const shadowDistance = Math.min(3.4, Math.abs(eclipse.moon.position.x));
  const distanceRatio = shadowDistance / 3.4;
  const umbraRadius = THREE.MathUtils.lerp(0.23, 0.14, distanceRatio)
    * eclipse.earth.scale.x;
  const penumbraRadius = THREE.MathUtils.lerp(0.23, 0.42, distanceRatio)
    * eclipse.earth.scale.x;
  const axisDistance = Math.hypot(
    eclipse.moon.position.y,
    eclipse.moon.position.z,
  );
  const penetration = (shadowRadius: number): number => THREE.MathUtils.clamp(
    (shadowRadius + moonRadius - axisDistance) / (2 * moonRadius),
    0,
    1,
  );
  const penumbraAmount = easeInOut(penetration(penumbraRadius));
  const umbraAmount = easeInOut(penetration(umbraRadius));
  const material = eclipse.moon.material as THREE.MeshStandardMaterial;
  const penumbralColor = new THREE.Color(0x887b78);
  material.color.lerpColors(
    new THREE.Color(0xa9acb2),
    penumbralColor,
    penumbraAmount,
  ).lerp(new THREE.Color(0x6d241b), umbraAmount);
  material.emissive.lerpColors(
    new THREE.Color(0x101116),
    new THREE.Color(0x2b0904),
    umbraAmount,
  );
  material.emissiveIntensity = THREE.MathUtils.lerp(0.08, 0.28, umbraAmount);
};


const setBodies = (
  context: ControllerContext,
  moonLongitude: number,
  sunLongitude: number,
): {sun: Vec3; moon: Vec3} => {
  const radius = numberParameter(context, 'moon_orbit_radius', 2.2);
  const inclination = numberParameter(
    context,
    'moon_orbit_inclination_degrees',
    5,
  );
  const sunDistance = numberParameter(context, 'sun_distance', 8);
  const sun = sunPosition(sunLongitude, sunDistance);
  const moon = lunarOrbitPosition(moonLongitude, radius, inclination);
  const eclipse = context.objects.eclipse;
  eclipse.sun.position.set(sun.x, sun.y, sun.z);
  eclipse.sunLight.position.set(sun.x, sun.y, sun.z);
  eclipse.earth.position.set(0, 0, 0);
  eclipse.moon.position.set(moon.x, moon.y, moon.z);
  eclipse.earth.rotation.y = moonLongitude * 0.015;
  eclipse.moon.rotation.y = moonLongitude * 0.01;
  return {sun, moon};
};


const setMoonShadow = (
  context: ControllerContext,
  sun: Vec3,
  moon: Vec3,
  hitMarker: boolean,
): void => {
  const eclipse = context.objects.eclipse;
  const direction = normalize(vector(sun, moon));
  const end = extend(moon, direction, 3.2);
  const shadowStartRadius = 0.1 * eclipse.moon.scale.x;
  const shadowEndRadius = 0.025 * eclipse.moon.scale.x;
  const penumbraEndRadius = 0.24 * eclipse.moon.scale.x;
  setDynamicLine(eclipse.moonShadow, [moon, end]);
  setShadowOutline(
    eclipse.moonUmbra,
    moon,
    end,
    shadowStartRadius,
    shadowEndRadius,
  );
  setShadowVolume(eclipse.moonUmbraFill, moon, end, shadowStartRadius);
  setShadowOutline(
    eclipse.moonPenumbra,
    moon,
    end,
    shadowStartRadius,
    penumbraEndRadius,
  );
  setShadowVolume(
    eclipse.moonPenumbraFill,
    moon,
    end,
    shadowStartRadius,
  );
  eclipse.moonShadow.visible = true;
  eclipse.moonUmbra.visible = true;
  eclipse.moonUmbraFill.visible = true;
  eclipse.moonPenumbra.visible = true;
  eclipse.moonPenumbraFill.visible = true;
  eclipse.shadowHitMarker.visible = hitMarker;
  if (hitMarker) {
    eclipse.shadowHitMarker.position.set(0.235, 0, 0);
    eclipse.shadowHitMarker.rotation.y = Math.PI / 2;
  }
};


const setEarthShadow = (
  context: ControllerContext,
  sun: Vec3,
): void => {
  const eclipse = context.objects.eclipse;
  const earth = {x: 0, y: 0, z: 0};
  const direction = normalize(vector(sun, earth));
  const end = extend(earth, direction, 3.4);
  const shadowStartRadius = 0.23 * eclipse.earth.scale.x;
  const shadowEndRadius = 0.14 * eclipse.earth.scale.x;
  const penumbraEndRadius = 0.42 * eclipse.earth.scale.x;
  setDynamicLine(eclipse.earthShadow, [earth, end]);
  setShadowOutline(
    eclipse.earthUmbra,
    earth,
    end,
    shadowStartRadius,
    shadowEndRadius,
  );
  setShadowVolume(eclipse.earthUmbraFill, earth, end, shadowStartRadius);
  setShadowOutline(
    eclipse.earthPenumbra,
    earth,
    end,
    shadowStartRadius,
    penumbraEndRadius,
  );
  setShadowVolume(
    eclipse.earthPenumbraFill,
    earth,
    end,
    shadowStartRadius,
  );
  eclipse.earthShadow.visible = true;
  eclipse.earthUmbra.visible = true;
  eclipse.earthUmbraFill.visible = true;
  eclipse.earthPenumbra.visible = true;
  eclipse.earthPenumbraFill.visible = true;
};


const threeQuarterCamera = (context: ControllerContext): void =>
  setCamera(context.objects, {x: 7.2, y: -8.4, z: 4.6});


export const createMonthlyCycleHook: SceneFactory = (context) => ({
  update(_progress, simulationDay) {
    configureEclipseScene(context);
    const eclipse = context.objects.eclipse;
    eclipse.moonOrbit.visible = true;
    eclipse.phaseMarkers.visible = true;
    setBodies(
      context,
      simulationDay,
      numberParameter(context, 'sun_longitude_degrees', 90),
    );
    threeQuarterCamera(context);
  },
});


export const createTopViewAlignment: SceneFactory = (context) => ({
  update(progress, simulationDay) {
    configureEclipseScene(context);
    const eclipse = context.objects.eclipse;
    const viewMode = stringParameter(context, 'view_mode', 'wide_alignment');
    const sunLongitude = numberParameter(context, 'sun_longitude_degrees', 90);
    const sightlineProgress = viewMode === 'scale_to_apparent_size'
      ? Math.min(1, progress / 0.88)
      : progress;
    const moonLongitude = viewMode === 'scale_to_apparent_size'
      ? THREE.MathUtils.lerp(
        simulationDay,
        sunLongitude,
        easeInOut(sightlineProgress),
      )
      : simulationDay;
    eclipse.moonOrbit.visible = viewMode !== 'scale_to_apparent_size'
      || sightlineProgress < 0.62;
    setBodies(context, moonLongitude, sunLongitude);
    if (viewMode === 'scale_to_apparent_size') {
      eclipse.moon.position.z = 0;
      context.objects.camera.up
        .set(0, 1 - sightlineProgress, sightlineProgress)
        .normalize();
      if (sightlineProgress > 0.62) eclipse.earth.visible = false;
    }
    setCamera(
      context.objects,
      {x: 0, y: 2.8, z: 20},
      {x: 0, y: 2.8, z: 0},
    );
  },
});


export const createTiltReveal: SceneFactory = (context) => ({
  update(progress) {
    configureEclipseScene(context);
    const eclipse = context.objects.eclipse;
    eclipse.moonOrbit.visible = true;
    eclipse.eclipticPlane.visible = true;
    eclipse.lunarPlane.visible = true;
    eclipse.nodeLine.visible = true;
    setBodies(
      context,
      numberParameter(context, 'moon_longitude_degrees', 90),
      90,
    );
    setCamera(
      context.objects,
      interpolateVector(
        {x: 0, y: 0, z: 11},
        {x: 7, y: -9, z: 5},
        progress,
      ),
    );
  },
});


export const createNewMoonMiss: SceneFactory = (context) => ({
  update(_progress, simulationDay) {
    configureEclipseScene(context);
    const eclipse = context.objects.eclipse;
    eclipse.moonOrbit.visible = true;
    eclipse.earth.scale.setScalar(numberParameter(context, 'earth_display_scale', 0.55));
    eclipse.moon.scale.setScalar(numberParameter(context, 'moon_display_scale', 0.7));
    const state = setBodies(
      context,
      simulationDay,
      numberParameter(context, 'sun_longitude_degrees', 90),
    );
    setMoonShadow(context, state.sun, state.moon, false);
    context.objects.camera.up.set(0, 0, 1);
    setCamera(context.objects, {x: 8, y: 1, z: 0}, {x: 0, y: 1, z: 0});
  },
});


export const createFullMoonMiss: SceneFactory = (context) => ({
  update(_progress, simulationDay) {
    configureEclipseScene(context);
    const eclipse = context.objects.eclipse;
    eclipse.moonOrbit.visible = true;
    eclipse.earth.scale.setScalar(numberParameter(context, 'earth_display_scale', 0.55));
    eclipse.moon.scale.setScalar(numberParameter(context, 'moon_display_scale', 0.7));
    const state = setBodies(
      context,
      simulationDay,
      numberParameter(context, 'sun_longitude_degrees', 90),
    );
    setEarthShadow(context, state.sun);
    context.objects.camera.up.set(0, 0, 1);
    setCamera(context.objects, {x: 8, y: -1, z: 0}, {x: 0, y: -1, z: 0});
  },
});


export const createNodeCrossing: SceneFactory = (context) => ({
  update(_progress, simulationDay) {
    configureEclipseScene(context);
    const eclipse = context.objects.eclipse;
    eclipse.moonOrbit.visible = true;
    eclipse.eclipticPlane.visible = true;
    eclipse.lunarPlane.visible = true;
    eclipse.nodeLine.visible = true;
    eclipse.sun.visible = false;
    setBodies(context, simulationDay, 0);
    eclipse.sun.visible = false;
    setCamera(context.objects, {x: 7.5, y: -8.5, z: 4}, {x: 0.8, y: 0, z: 0});
  },
});


export const createSolarEclipseAlignment: SceneFactory = (context) => ({
  update(progress, simulationDay) {
    configureEclipseScene(context);
    const eclipse = context.objects.eclipse;
    const viewMode = stringParameter(context, 'view_mode', 'wide_alignment');
    const state = setBodies(
      context,
      simulationDay,
      numberParameter(context, 'sun_longitude_degrees', 0),
    );
    if (viewMode === 'earth_close_shadow_track') {
      setMoonShadow(context, state.sun, state.moon, false);
      setEarthSurfaceShadow(context, progress);
      eclipse.sun.visible = false;
      return;
    }
    if (viewMode === 'moon_orbit_distance_reveal') {
      const orbit = setMildlyEllipticalMoonOrbit(context);
      eclipse.moonOrbit.visible = true;
      const angle = THREE.MathUtils.lerp(
        THREE.MathUtils.degToRad(68),
        0,
        easeInOut(progress),
      );
      setMoonOnEllipticalOrbit(
        context,
        angle,
        orbit.semiMajor,
        orbit.eccentricity,
      );
      const sightlineReveal = easeInOut(Math.max(0, (progress - 0.58) / 0.42));
      eclipse.moon.position.y += 0.18 * sightlineReveal;
      eclipse.moon.position.z *= 1 - sightlineReveal;
      eclipse.moonOrbit.visible = progress < 0.76;
      if (progress > 0.7) eclipse.earth.visible = false;
      return;
    }
    if (viewMode === 'observer_annular_close') {
      const orbit = setMildlyEllipticalMoonOrbit(context);
      setMoonOnEllipticalOrbit(
        context,
        0,
        orbit.semiMajor,
        orbit.eccentricity,
      );
      eclipse.moon.position.y = THREE.MathUtils.lerp(
        0.16,
        0,
        easeInOut(progress),
      );
      eclipse.moon.position.z = 0;
      eclipse.earth.visible = false;
      return;
    }
    setMoonShadow(context, state.sun, state.moon, progress > 0.82);
    setCamera(context.objects, {x: 4, y: -15, z: 6}, {x: 2.5, y: 0, z: 0});
  },
});


export const createLunarEclipseAlignment: SceneFactory = (context) => ({
  update(progress, simulationDay) {
    configureEclipseScene(context);
    const eclipse = context.objects.eclipse;
    const viewMode = stringParameter(context, 'view_mode', 'wide_alignment');
    const state = setBodies(
      context,
      simulationDay,
      numberParameter(context, 'sun_longitude_degrees', 0),
    );
    setEarthShadow(context, state.sun);
    if (viewMode === 'moon_close_shadow_entry') {
      eclipse.sun.visible = progress < 0.12;
      eclipse.moon.position.set(
        -numberParameter(context, 'moon_orbit_radius', 2.2),
        THREE.MathUtils.lerp(0.55, 0, easeInOut(progress)),
        0,
      );
      tintMoonFromEarthShadowGeometry(context);
      return;
    }
    if (viewMode === 'blood_moon_close_to_night_side') {
      eclipse.sun.visible = false;
      eclipse.moon.position.set(
        -numberParameter(context, 'moon_orbit_radius', 2.2),
        0,
        0,
      );
      tintMoon(context, 1, 0xa9acb2, 0x7c291d);
      return;
    }
    setCamera(context.objects, {x: 4, y: -15, z: 6}, {x: 2.5, y: 0, z: 0});
  },
});


export const createTwoConditionSummary: SceneFactory = (context) => ({
  update(progress) {
    configureEclipseScene(context);
    const eclipse = context.objects.eclipse;
    eclipse.moonOrbit.visible = true;
    eclipse.eclipticPlane.visible = true;
    eclipse.lunarPlane.visible = true;
    eclipse.nodeLine.visible = true;
    const start = numberParameter(context, 'sun_longitude_start_degrees', 90);
    const end = numberParameter(context, 'sun_longitude_end_degrees', 0);
    const longitude = THREE.MathUtils.lerp(start, end, easeInOut(progress));
    const state = setBodies(context, longitude, longitude);
    setMoonShadow(context, state.sun, state.moon, progress > 0.82);
    eclipse.moonShadow.visible = progress > 0.48;
    eclipse.moonUmbra.visible = progress > 0.48;
    eclipse.moonUmbraFill.visible = progress > 0.48;
    eclipse.moonPenumbra.visible = progress > 0.48;
    eclipse.moonPenumbraFill.visible = progress > 0.48;
    setCamera(
      context.objects,
      {x: 7, y: -18, z: 9},
      {x: 2.5, y: 2.5, z: 0},
    );
  },
});
