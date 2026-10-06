import {
  interpolateVector,
  resetVisibility,
  setCamera,
  updateOrbitAndSightline,
  updateProjectionHistory,
  type SceneFactory,
} from './contracts.js';


export const createProjectionProof: SceneFactory = (context) => ({
  update(progress, simulationDay) {
    resetVisibility(context.objects);
    context.objects.projectionMarker.visible = true;
    context.objects.starWall.visible = true;
    updateOrbitAndSightline(context.objects, context.physics, simulationDay, true);
    updateProjectionHistory(
      context.objects,
      context.physics,
      context.simulationDayStart,
      simulationDay,
      32,
    );
    context.objects.earth.scale.setScalar(1.55);
    context.objects.mars.scale.setScalar(1.7);
    setCamera(
      context.objects,
      interpolateVector(
        {x: -0.8, y: -7.3, z: 6},
        {x: 1, y: -5.7, z: 4.5},
        progress,
      ),
    );
  },
});
