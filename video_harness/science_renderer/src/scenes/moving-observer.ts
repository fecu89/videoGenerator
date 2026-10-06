import {orbitPosition} from '../math/circular-orbit.js';
import {
  interpolateVector,
  resetVisibility,
  setCamera,
  updateOrbitAndSightline,
  type SceneFactory,
} from './contracts.js';


export const createMovingObserver: SceneFactory = (context) => ({
  update(progress, simulationDay) {
    resetVisibility(context.objects);
    updateOrbitAndSightline(context.objects, context.physics, simulationDay);
    const earth = orbitPosition('earth', simulationDay, context.physics);
    const nearEarth = {x: earth.x, y: earth.y - 0.34, z: 0.22};
    const camera = interpolateVector(nearEarth, {x: 0, y: -4.2, z: 3.1}, progress);
    setCamera(context.objects, camera, progress < 0.35 ? earth : {x: 0, y: 0, z: 0});
  },
});
