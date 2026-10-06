import {describe, expect, it} from 'vitest';

import {
  DEFAULT_PHYSICS,
  heliocentricAngle,
  orbitPosition,
} from '../src/math/circular-orbit.js';


describe('circular teaching orbits', () => {
  it('keeps both heliocentric angles strictly increasing', () => {
    for (const period of [
      DEFAULT_PHYSICS.earthPeriodDays,
      DEFAULT_PHYSICS.marsPeriodDays,
    ]) {
      const angles = [-90, -45, 0, 45, 90].map((day) =>
        heliocentricAngle(period, day),
      );
      expect(angles.slice(1).every((angle, index) => angle > angles[index]!)).toBe(
        true,
      );
    }
  });

  it('moves Earth through a greater angle over the same interval', () => {
    const earthDelta =
      heliocentricAngle(DEFAULT_PHYSICS.earthPeriodDays, 30) -
      heliocentricAngle(DEFAULT_PHYSICS.earthPeriodDays, 0);
    const marsDelta =
      heliocentricAngle(DEFAULT_PHYSICS.marsPeriodDays, 30) -
      heliocentricAngle(DEFAULT_PHYSICS.marsPeriodDays, 0);

    expect(earthDelta).toBeGreaterThan(marsDelta);
  });

  it('places Earth between the Sun and Mars at opposition day zero', () => {
    expect(orbitPosition('earth', 0, DEFAULT_PHYSICS)).toEqual({x: 1, y: 0, z: 0});
    expect(orbitPosition('mars', 0, DEFAULT_PHYSICS)).toEqual({x: 1.52, y: 0, z: 0});
  });
});
