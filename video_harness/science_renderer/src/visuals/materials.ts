import * as THREE from 'three';


export const createEarthMaterial = (): THREE.MeshStandardMaterial =>
  new THREE.MeshStandardMaterial({
    color: 0x2d75b8,
    roughness: 0.78,
    metalness: 0,
    emissive: 0x061725,
    emissiveIntensity: 0.18,
  });


export const createMarsMaterial = (): THREE.MeshStandardMaterial =>
  new THREE.MeshStandardMaterial({
    color: 0xb85f38,
    roughness: 0.92,
    metalness: 0,
    emissive: 0x261008,
    emissiveIntensity: 0.12,
  });


export const createSunMaterial = (): THREE.MeshBasicMaterial =>
  new THREE.MeshBasicMaterial({color: 0xffd37a});
