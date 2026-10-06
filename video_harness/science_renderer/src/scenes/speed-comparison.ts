import {
  resetVisibility,
  setCamera,
  updateMotionTrails,
  updateOrbitAndSightline,
  type SceneFactory,
} from './contracts.js';


export const createSpeedComparison: SceneFactory = (context) => ({
  update(_progress, simulationDay) {
    resetVisibility(context.objects);
    context.objects.sightline.visible = false;
    context.objects.earthTrail.visible = true;
    context.objects.marsTrail.visible = true;
    updateOrbitAndSightline(context.objects, context.physics, simulationDay);
    updateMotionTrails(
      context.objects,
      context.physics,
      context.simulationDayStart,
      simulationDay,
    );
    context.objects.earth.scale.setScalar(1.65);
    context.objects.mars.scale.setScalar(1.8);
    setCamera(context.objects, {x: 0, y: -4.25, z: 3.25});
  },
});
