import type {Vec3} from '../types.js';


const degreesToRadians = (degrees: number): number =>
  (degrees * Math.PI) / 180;


export const lunarOrbitPosition = (
  longitudeDegrees: number,
  radius: number,
  inclinationDegrees: number,
): Vec3 => {
  const longitude = degreesToRadians(longitudeDegrees);
  const inclination = degreesToRadians(inclinationDegrees);
  return {
    x: radius * Math.cos(longitude),
    y: radius * Math.sin(longitude) * Math.cos(inclination),
    z: radius * Math.sin(longitude) * Math.sin(inclination),
  };
};


export const sunPosition = (
  longitudeDegrees: number,
  distance: number,
): Vec3 => {
  const longitude = degreesToRadians(longitudeDegrees);
  return {
    x: distance * Math.cos(longitude),
    y: distance * Math.sin(longitude),
    z: 0,
  };
};


export const distancePointToRay = (
  point: Vec3,
  rayOrigin: Vec3,
  rayDirection: Vec3,
): number => {
  const magnitude = Math.hypot(rayDirection.x, rayDirection.y, rayDirection.z);
  if (magnitude === 0) throw new Error('ray direction must be non-zero');
  const direction = {
    x: rayDirection.x / magnitude,
    y: rayDirection.y / magnitude,
    z: rayDirection.z / magnitude,
  };
  const offset = {
    x: point.x - rayOrigin.x,
    y: point.y - rayOrigin.y,
    z: point.z - rayOrigin.z,
  };
  const distanceAlongRay = Math.max(
    0,
    offset.x * direction.x +
      offset.y * direction.y +
      offset.z * direction.z,
  );
  return Math.hypot(
    offset.x - distanceAlongRay * direction.x,
    offset.y - distanceAlongRay * direction.y,
    offset.z - distanceAlongRay * direction.z,
  );
};
