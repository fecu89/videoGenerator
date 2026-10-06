import {
  resetVisibility,
  setCamera,
  updateOrbitAndSightline,
  type SceneFactory,
} from './contracts.js';


export const createSightlineAngle: SceneFactory = (context) => ({
  update(_progress, simulationDay) {
    resetVisibility(context.objects);
    updateOrbitAndSightline(context.objects, context.physics, simulationDay);
    setCamera(context.objects, {x: 0.2, y: -4.4, z: 3.35});
  },
});
