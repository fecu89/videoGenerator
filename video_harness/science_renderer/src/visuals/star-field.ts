import * as THREE from 'three';


const mulberry32 = (seed: number): (() => number) => {
  let state = seed >>> 0;
  return () => {
    state += 0x6d2b79f5;
    let value = state;
    value = Math.imul(value ^ (value >>> 15), value | 1);
    value ^= value + Math.imul(value ^ (value >>> 7), value | 61);
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
  };
};


export const generateStarPositions = (
  seed: number,
  count: number,
  radius = 12,
): number[] => {
  const random = mulberry32(seed);
  const positions: number[] = [];
  for (let index = 0; index < count; index += 1) {
    const longitude = random() * Math.PI * 2;
    const vertical = random() * 2 - 1;
    const horizontal = Math.sqrt(1 - vertical * vertical);
    const distance = radius * (0.92 + random() * 0.08);
    positions.push(
      distance * horizontal * Math.cos(longitude),
      distance * horizontal * Math.sin(longitude),
      distance * vertical,
    );
  }
  return positions;
};


export const createStarField = (seed: number, count = 900): THREE.Points => {
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute(
    'position',
    new THREE.Float32BufferAttribute(generateStarPositions(seed, count), 3),
  );
  const material = new THREE.PointsMaterial({
    color: 0xdde9ff,
    size: 1.35,
    sizeAttenuation: false,
    transparent: true,
    opacity: 0.72,
    depthWrite: false,
  });
  const stars = new THREE.Points(geometry, material);
  stars.renderOrder = -10;
  return stars;
};
