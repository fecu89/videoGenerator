import {describe, expect, it} from 'vitest';

import {
  distancePointToRay,
  lunarOrbitPosition,
  sunPosition,
} from '../src/math/eclipse.js';


describe('Sun Earth Moon eclipse geometry', () => {
  it('puts the off-season new Moon above the ecliptic by the declared five degrees', () => {
    const moon = lunarOrbitPosition(90, 2.2, 5);

    expect(moon.x).toBeCloseTo(0, 12);
    expect(moon.y).toBeCloseTo(2.2 * Math.cos((5 * Math.PI) / 180), 12);
    expect(moon.z).toBeCloseTo(2.2 * Math.sin((5 * Math.PI) / 180), 12);
  });

  it('places the Moon on the ecliptic at both nodes', () => {
    expect(lunarOrbitPosition(0, 2.2, 5).z).toBeCloseTo(0, 12);
    expect(lunarOrbitPosition(180, 2.2, 5).z).toBeCloseTo(0, 12);
  });

  it('makes the off-season lunar shadow miss Earth but the node shadow hit it', () => {
    const offSeasonSun = sunPosition(90, 8);
    const offSeasonMoon = lunarOrbitPosition(90, 2.2, 5);
    const offSeasonShadowDirection = {
      x: offSeasonMoon.x - offSeasonSun.x,
      y: offSeasonMoon.y - offSeasonSun.y,
      z: offSeasonMoon.z - offSeasonSun.z,
    };
    const nodeSun = sunPosition(0, 8);
    const nodeMoon = lunarOrbitPosition(0, 2.2, 5);
    const nodeShadowDirection = {
      x: nodeMoon.x - nodeSun.x,
      y: nodeMoon.y - nodeSun.y,
      z: nodeMoon.z - nodeSun.z,
    };

    expect(
      distancePointToRay({x: 0, y: 0, z: 0}, offSeasonMoon, offSeasonShadowDirection),
    ).toBeGreaterThan(0.19);
    expect(
      distancePointToRay({x: 0, y: 0, z: 0}, nodeMoon, nodeShadowDirection),
    ).toBeCloseTo(0, 12);
  });
});
