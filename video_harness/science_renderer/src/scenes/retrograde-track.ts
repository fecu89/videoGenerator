import {
  resetVisibility,
  setCamera,
  updateSkyTrack,
  type SceneFactory,
} from './contracts.js';


export const createRetrogradeTrack: SceneFactory = (context) => ({
  update(progress, simulationDay) {
    resetVisibility(context.objects);
    context.objects.orbitGroup.visible = false;
    context.objects.skyGroup.visible = true;
    context.objects.skyMarker.visible = true;
    context.objects.skyTrail.visible = true;
    updateSkyTrack(
      context.objects,
      context.physics,
      context.simulationDayStart,
      simulationDay,
      Math.max(3, Math.round(3 + progress * 39)),
    );
    setCamera(context.objects, {x: 0, y: 0, z: 4.25});
  },
});
