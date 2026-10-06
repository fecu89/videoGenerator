import {describe, expect, it} from 'vitest';

import {
  HR_SOURCE_STARS,
  STELLAR_RADII_KM,
  hrChartPosition,
  hrStarById,
  spectralCoordinate,
  validateHrStarCatalog,
} from '../src/data/hr-stars.js';


describe('H-R source data', () => {
  it('converts the lesson spectral codes exactly', () => {
    expect(spectralCoordinate('A2')).toBe(22);
    expect(spectralCoordinate('M1')).toBe(61);
    expect(() => spectralCoordinate('Q4')).toThrow(/invalid spectral type/);
  });

  it('places hotter classes left and brighter magnitudes higher', () => {
    expect(hrChartPosition({spectralType: 'B1', absoluteMagnitude: 5}).x)
      .toBeLessThan(hrChartPosition({spectralType: 'K1', absoluteMagnitude: 5}).x);
    expect(hrChartPosition({spectralType: 'G2', absoluteMagnitude: -5}).y)
      .toBeGreaterThan(hrChartPosition({spectralType: 'G2', absoluteMagnitude: 10}).y);
  });

  it('preserves source rows and radius ratios', () => {
    expect(HR_SOURCE_STARS).toHaveLength(30);
    expect(hrStarById('antares')).toMatchObject({
      spectralType: 'M1',
      absoluteMagnitude: -5.6,
    });
    expect(STELLAR_RADII_KM.antares / STELLAR_RADII_KM.sun)
      .toBeCloseTo(470_000_000 / 700_000, 8);
  });

  it('rejects duplicate and unknown source IDs', () => {
    expect(() => validateHrStarCatalog([
      {id: 'same', name: 'A', spectralType: 'G2', absoluteMagnitude: 4},
      {id: 'same', name: 'B', spectralType: 'K2', absoluteMagnitude: 5},
    ])).toThrow(/duplicate H-R star ID: same/);
    expect(() => hrStarById('missing')).toThrow(/unknown H-R star ID: missing/);
  });

  it('rejects absolute magnitudes outside the declared chart', () => {
    expect(() => hrChartPosition({spectralType: 'G2', absoluteMagnitude: -10.1}))
      .toThrow(/absolute magnitude outside H-R domain/);
    expect(() => hrChartPosition({spectralType: 'G2', absoluteMagnitude: 16.1}))
      .toThrow(/absolute magnitude outside H-R domain/);
  });
});
