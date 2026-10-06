import {
  resetVisibility,
  setCamera,
  updateOrbitAndSightline,
  updateProjectionHistory,
  updateSkyTrack,
  type SceneFactory,
} from './contracts.js';


export const createReturnToDirect: SceneFactory = (context) => ({
  update(_progress, simulationDay) {
    resetVisibility(context.objects);
    updateOrbitAndSightline(context.objects, context.physics, simulationDay, true);
    context.objects.projectionMarker.visible = true;
    context.objects.starWall.visible = true;
    updateProjectionHistory(
      context.objects,
      context.physics,
      context.simulationDayStart,
      simulationDay,
      28,
    );

    // End on a comparison composition instead of replaying the opening sky
    // shot: physical orbits on the left, apparent sky motion on the right.
    context.objects.orbitGroup.position.set(-1.75, -0.45, 0);
    context.objects.orbitGroup.scale.setScalar(0.3);
    context.objects.earth.scale.setScalar(5);
    context.objects.mars.scale.setScalar(5.5);
    context.objects.projectionMarker.scale.setScalar(3);

    context.objects.skyGroup.visible = true;
    context.objects.skyMarker.visible = true;
    context.objects.skyTrail.visible = true;
    updateSkyTrack(
      context.objects,
      context.physics,
      context.physics.oppositionDay - 70,
      simulationDay,
      36,
    );
    context.objects.skyGroup.position.set(1.5, 0.55, 0.1);
    context.objects.skyGroup.scale.setScalar(0.58);
    context.objects.skyMarker.scale.setScalar(1.35);
    setCamera(context.objects, {x: 0, y: 0, z: 5.2});
  },
});
