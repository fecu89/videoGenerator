export interface Vec3 {
  x: number;
  y: number;
  z: number;
}

export interface Physics {
  earthPeriodDays: number;
  marsPeriodDays: number;
  earthOrbitRadius: number;
  marsOrbitRadius: number;
  oppositionDay: number;
}

export type BodyName = 'earth' | 'mars';
