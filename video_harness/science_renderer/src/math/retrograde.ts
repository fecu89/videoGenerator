import {orbitPosition} from './circular-orbit.js';
import {normalize, subtract} from './sightline.js';
import type {Physics} from '../types.js';


export interface RetrogradeWindow {
  startDay: number;
  endDay: number;
}


const angularDifference = (next: number, previous: number): number =>
  Math.atan2(Math.sin(next - previous), Math.cos(next - previous));


export const apparentLongitude = (day: number, physics: Physics): number => {
  const earth = orbitPosition('earth', day, physics);
  const mars = orbitPosition('mars', day, physics);
  const direction = normalize(subtract(mars, earth));
  return Math.atan2(direction.y, direction.x);
};


export const apparentLongitudeRate = (
  day: number,
  physics: Physics,
  halfStepDays = 0.01,
): number => {
  const before = apparentLongitude(day - halfStepDays, physics);
  const after = apparentLongitude(day + halfStepDays, physics);
  return angularDifference(after, before) / (2 * halfStepDays);
};


const interpolateZero = (
  firstDay: number,
  firstRate: number,
  secondDay: number,
  secondRate: number,
): number =>
  firstDay + ((0 - firstRate) * (secondDay - firstDay)) / (secondRate - firstRate);


export const findRetrogradeWindow = (
  physics: Physics,
  searchStartDay = -100,
  searchEndDay = 100,
  stepDays = 0.1,
): RetrogradeWindow => {
  let previousDay = searchStartDay;
  let previousRate = apparentLongitudeRate(previousDay, physics);
  let startDay: number | undefined;
  let endDay: number | undefined;

  for (
    let day = searchStartDay + stepDays;
    day <= searchEndDay + Number.EPSILON;
    day += stepDays
  ) {
    const rate = apparentLongitudeRate(day, physics);
    if (startDay === undefined && previousRate > 0 && rate <= 0) {
      startDay = interpolateZero(previousDay, previousRate, day, rate);
    } else if (startDay !== undefined && previousRate < 0 && rate >= 0) {
      endDay = interpolateZero(previousDay, previousRate, day, rate);
      break;
    }
    previousDay = day;
    previousRate = rate;
  }

  if (startDay === undefined || endDay === undefined) {
    throw new Error('retrograde stationary points were not found in the search range');
  }
  return {startDay, endDay};
};
