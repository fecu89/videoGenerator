import type {Vec3} from '../types.js';


export const subtract = (target: Vec3, origin: Vec3): Vec3 => ({
  x: target.x - origin.x,
  y: target.y - origin.y,
  z: target.z - origin.z,
});


export const normalize = (vector: Vec3): Vec3 => {
  const length = Math.hypot(vector.x, vector.y, vector.z);
  if (length === 0) {
    throw new ValueError('cannot normalize a zero-length sightline');
  }
  return {
    x: vector.x / length,
    y: vector.y / length,
    z: vector.z / length,
  };
};


class ValueError extends Error {
  override name = 'ValueError';
}
