import {describe, expect, it} from 'vitest';
import * as THREE from 'three';

import {
  setHrRadiusStage,
  setHrRegionReveal,
  setHrStarReveal,
} from '../src/visuals/hr-diagram.js';
import {createSharedScene} from '../src/visuals/solar-system.js';


describe('H-R diagram visual system', () => {
  it('creates a hidden chart with 30 points and four group layers', () => {
    const objects = createSharedScene({seed: 4, width: 320, height: 180});

    expect(objects.hr.group.visible).toBe(false);
    expect(objects.hr.sourceStars.geometry.attributes.position!.count).toBe(30);
    expect(Object.keys(objects.hr.regions).sort()).toEqual([
      'main_sequence',
      'red_giant',
      'supergiant',
      'white_dwarf',
    ]);
  });

  it('reveals chart layers without moving source positions', () => {
    const objects = createSharedScene({seed: 4, width: 320, height: 180});
    const position = objects.hr.sourceStars.geometry.attributes.position!;
    const before = Array.from(position.array);

    setHrStarReveal(objects.hr, 15);
    setHrRegionReveal(objects.hr, ['main_sequence']);

    expect(objects.hr.sourceStars.geometry.drawRange.count).toBe(15);
    expect(Array.from(position.array)).toEqual(before);
    expect(objects.hr.regions.main_sequence.visible).toBe(true);
    expect(objects.hr.regions.red_giant.visible).toBe(false);
  });

  it('stores source radii independently of display scale', () => {
    const objects = createSharedScene({seed: 4, width: 320, height: 180});

    expect(objects.hr.radiusBodies.antares.userData.radiusKm).toBe(470_000_000);
    expect(objects.hr.radiusBodies.sun.userData.radiusKm).toBe(700_000);
    expect(objects.hr.radiusBodies.antares.scale.x).toBe(1);
    expect(objects.hr.radiusBodies.sun.scale.x).toBe(1);
  });

  it('fits every declared chart annotation inside the teaching camera safe frame', () => {
    const objects = createSharedScene({seed: 4, width: 1920, height: 1080});
    objects.hr.group.visible = true;
    objects.hr.chartGroup.visible = true;
    objects.camera.position.set(0, 0, 6.2);
    objects.camera.lookAt(0, 0, 0);
    objects.camera.updateProjectionMatrix();
    objects.scene.updateMatrixWorld(true);
    objects.camera.updateMatrixWorld(true);

    const bounds = new THREE.Box3().setFromObject(objects.hr.chartGroup, true);
    const corners = [
      new THREE.Vector3(bounds.min.x, bounds.min.y, bounds.min.z),
      new THREE.Vector3(bounds.min.x, bounds.max.y, bounds.min.z),
      new THREE.Vector3(bounds.max.x, bounds.min.y, bounds.min.z),
      new THREE.Vector3(bounds.max.x, bounds.max.y, bounds.min.z),
      new THREE.Vector3(bounds.min.x, bounds.min.y, bounds.max.z),
      new THREE.Vector3(bounds.min.x, bounds.max.y, bounds.max.z),
      new THREE.Vector3(bounds.max.x, bounds.min.y, bounds.max.z),
      new THREE.Vector3(bounds.max.x, bounds.max.y, bounds.max.z),
    ];

    for (const corner of corners) {
      const projected = corner.project(objects.camera);
      expect(Math.abs(projected.x)).toBeLessThanOrEqual(0.94);
      expect(Math.abs(projected.y)).toBeLessThanOrEqual(0.94);
    }
  });

  it('labels the source-backed bodies in both radius comparison stages', () => {
    const objects = createSharedScene({seed: 4, width: 320, height: 180});

    setHrRadiusStage(objects.hr, 0.25);
    expect(objects.hr.radiusLabels.sun.visible).toBe(true);
    expect(objects.hr.radiusLabels.arcturus.visible).toBe(true);
    expect(objects.hr.radiusLabels.antares.visible).toBe(false);
    expect(objects.hr.scaleLabel.visible).toBe(true);

    setHrRadiusStage(objects.hr, 0.75);
    expect(objects.hr.radiusLabels.sun.visible).toBe(false);
    expect(objects.hr.radiusLabels.arcturus.visible).toBe(true);
    expect(objects.hr.radiusLabels.antares.visible).toBe(true);
    const arcturusRight = objects.hr.radiusLabels.arcturus.position.x
      + objects.hr.radiusLabels.arcturus.scale.x / 2;
    const antaresLeft = objects.hr.radiusLabels.antares.position.x
      - objects.hr.radiusLabels.antares.scale.x / 2;
    expect(antaresLeft - arcturusRight).toBeGreaterThanOrEqual(0.2);
    expect(objects.hr.radiusLabels.antares.userData.textRenderMaxWidth)
      .toBe(480);
  });
});
