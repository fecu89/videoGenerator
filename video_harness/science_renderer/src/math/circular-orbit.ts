import type {BodyName, Physics, Vec3} from '../types.js';


export const DEFAULT_PHYSICS: Physics = {
  earthPeriodDays: 365,
  marsPeriodDays: 687,
  earthOrbitRadius: 1,
  marsOrbitRadius: 1.52,
  oppositionDay: 0,
};


export const heliocentricAngle = (
  periodDays: number,
  day: number,
  oppositionDay = 0,
): number => (2 * Math.PI * (day - oppositionDay)) / periodDays;


export const orbitPosition = (
  body: BodyName,
  day: number,
  physics: Physics,
): Vec3 => {
  const period =
    body === 'earth' ? physics.earthPeriodDays : physics.marsPeriodDays;
  const radius =
    body === 'earth' ? physics.earthOrbitRadius : physics.marsOrbitRadius;
  const angle = heliocentricAngle(period, day, physics.oppositionDay);
  return {
    x: radius * Math.cos(angle),
    y: radius * Math.sin(angle),
    z: 0,
  };
};
