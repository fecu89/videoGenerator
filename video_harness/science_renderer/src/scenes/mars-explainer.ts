import * as THREE from 'three';

import {orbitPosition} from '../math/circular-orbit.js';
import {findRetrogradeWindow} from '../math/retrograde.js';
import {
  interpolateVector,
  resetVisibility,
  setCamera,
  skyTrackPosition,
  updateCumulativeSightlines,
  updateDirectionArrow,
  updateMotionTrails,
  updateOrbitAndSightline,
  updateSkyTrack,
  type SceneFactory,
} from './contracts.js';


export const createSameDirectionArrows: SceneFactory = (context) => ({
  update(_progress, simulationDay) {
    resetVisibility(context.objects);
    updateOrbitAndSightline(context.objects, context.physics, simulationDay);
    context.objects.sightline.visible = false;
    const earth = orbitPosition('earth', simulationDay, context.physics);
    const mars = orbitPosition('mars', simulationDay, context.physics);
    updateDirectionArrow(context.objects.earthDirectionArrow, earth);
    updateDirectionArrow(context.objects.marsDirectionArrow, mars);
    context.objects.earth.scale.setScalar(1.55);
    context.objects.mars.scale.setScalar(1.7);
    setCamera(context.objects, {x: 0, y: 0, z: 4.15});
  },
});


export const createLocalOvertake: SceneFactory = (context) => ({
  update(_progress, simulationDay) {
    resetVisibility(context.objects);
    updateOrbitAndSightline(context.objects, context.physics, simulationDay);
    context.objects.sun.visible = false;
    updateMotionTrails(
      context.objects,
      context.physics,
      context.simulationDayStart,
      simulationDay,
      18,
    );
    context.objects.earthTrail.visible = true;
    context.objects.marsTrail.visible = true;
    context.objects.earth.scale.setScalar(2.25);
    context.objects.mars.scale.setScalar(2.45);
    const earth = orbitPosition('earth', simulationDay, context.physics);
    const mars = orbitPosition('mars', simulationDay, context.physics);
    const midpoint = {
      x: (earth.x + mars.x) / 2,
      y: (earth.y + mars.y) / 2,
      z: 0,
    };
    setCamera(
      context.objects,
      {x: midpoint.x, y: midpoint.y, z: 1.65},
      midpoint,
    );
  },
});


export const createCumulativeSightlines: SceneFactory = (context) => ({
  update(_progress, simulationDay) {
    resetVisibility(context.objects);
    updateOrbitAndSightline(
      context.objects,
      context.physics,
      simulationDay,
      true,
    );
    context.objects.starWall.visible = true;
    context.objects.projectionMarker.visible = true;
    updateCumulativeSightlines(
      context.objects,
      context.physics,
      context.simulationDayStart,
      simulationDay,
    );
    context.objects.earth.scale.setScalar(1.45);
    context.objects.mars.scale.setScalar(1.55);
    setCamera(context.objects, {x: 0, y: -6.5, z: 5.05});
  },
});


export const createStationaryPoints: SceneFactory = (context) => {
  const window = findRetrogradeWindow(
    context.physics,
    context.simulationDayStart,
    context.simulationDayEnd,
  );
  const start = skyTrackPosition(window.startDay, context.physics);
  const end = skyTrackPosition(window.endDay, context.physics);
  return {
    update(progress) {
      resetVisibility(context.objects);
      context.objects.orbitGroup.visible = false;
      context.objects.skyGroup.visible = true;
      context.objects.skyTrail.visible = true;
      updateSkyTrack(
        context.objects,
        context.physics,
        context.simulationDayStart,
        context.simulationDayEnd,
        64,
      );
      context.objects.skyMarker.visible = false;
      context.objects.stationMarkerStart.position.set(start.x, start.y, start.z + 0.02);
      context.objects.stationMarkerEnd.position.set(end.x, end.y, end.z + 0.02);
      context.objects.stationMarkerStart.visible = true;
      context.objects.stationMarkerEnd.visible = true;
      const pulse = 1 + 0.13 * Math.sin(progress * Math.PI * 6);
      const firstScale = progress < 0.52 ? pulse : 1;
      const secondScale = progress >= 0.38 ? pulse : 0.72;
      context.objects.stationMarkerStart.scale.setScalar(firstScale);
      context.objects.stationMarkerEnd.scale.setScalar(secondScale);
      const center = {x: 0, y: 0, z: 0};
      const focus = progress <= 0.5
        ? interpolateVector(start, center, progress * 2)
        : interpolateVector(center, end, (progress - 0.5) * 2);
      const zoomOut = 1 - Math.abs(progress * 2 - 1);
      setCamera(
        context.objects,
        {x: focus.x, y: focus.y, z: 3.25 + 1.15 * zoomOut},
        focus,
      );
    },
  };
};
