import {
  interpolateVector,
  resetVisibility,
  setCamera,
  updateOrbitAndSightline,
  updateSkyTrack,
  type SceneFactory,
} from './contracts.js';


export const createSkyOrbitReveal: SceneFactory = (context) => ({
  update(progress, simulationDay) {
    resetVisibility(context.objects);
    updateOrbitAndSightline(context.objects, context.physics, simulationDay);
    // The preceding shot already establishes the full retrograde track. Keep
    // this callback deliberately brief so the reveal does not replay it.
    if (progress < 0.12) {
      context.objects.orbitGroup.visible = false;
      context.objects.skyGroup.visible = true;
      context.objects.skyMarker.visible = true;
      context.objects.skyTrail.visible = true;
      updateSkyTrack(
        context.objects,
        context.physics,
        context.simulationDayStart,
        simulationDay,
        22,
      );
      setCamera(context.objects, {x: 0, y: 0, z: 4.25});
      return;
    }
    const local = (progress - 0.12) / 0.88;
    setCamera(
      context.objects,
      interpolateVector({x: 0, y: 0, z: 4.25}, {x: 0, y: -4.1, z: 3.2}, local),
    );
  },
});
