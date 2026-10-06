import {describe, expect, it} from 'vitest';

import {DEFAULT_PHYSICS} from '../src/math/circular-orbit.js';
import {
  apparentLongitude,
  apparentLongitudeRate,
  findRetrogradeWindow,
} from '../src/math/retrograde.js';


describe('geocentric apparent motion', () => {
  it('points from Earth directly outward to Mars at opposition', () => {
    expect(apparentLongitude(0, DEFAULT_PHYSICS)).toBeCloseTo(0, 12);
  });

  it('reverses only around opposition', () => {
    expect(apparentLongitudeRate(-60, DEFAULT_PHYSICS)).toBeGreaterThan(0);
    expect(apparentLongitudeRate(0, DEFAULT_PHYSICS)).toBeLessThan(0);
    expect(apparentLongitudeRate(60, DEFAULT_PHYSICS)).toBeGreaterThan(0);
  });

  it('finds the two stationary points near plus and minus 36.5 days', () => {
    const window = findRetrogradeWindow(DEFAULT_PHYSICS);

    expect(window.startDay).toBeGreaterThan(-38);
    expect(window.startDay).toBeLessThan(-35);
    expect(window.endDay).toBeGreaterThan(35);
    expect(window.endDay).toBeLessThan(38);
  });
});
