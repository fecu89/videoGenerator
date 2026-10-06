import {orbitPosition} from '../math/circular-orbit.js';
import {
  resetVisibility,
  setCamera,
  updateOrbitAndSightline,
  type SceneFactory,
} from './contracts.js';


export const createEarthOvertake: SceneFactory = (context) => ({
  update(_progress, simulationDay) {
    resetVisibility(context.objects);
    updateOrbitAndSightline(context.objects, context.physics, simulationDay);
    const earth = orbitPosition('earth', simulationDay, context.physics);
    setCamera(
      context.objects,
      {x: earth.x * 0.32, y: -4.1 + earth.y * 0.25, z: 3.15},
    );
  },
});
