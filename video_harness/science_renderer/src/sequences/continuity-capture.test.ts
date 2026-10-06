import {describe,expect,it} from 'vitest';
import * as THREE from 'three';
import {captureContinuity} from './continuity-capture.js';

describe('evaluated continuity capture',()=>{
  it('captures parent transforms and hidden ancestors with stable aliases',()=>{
    const scene=new THREE.Scene(),parent=new THREE.Group();
    parent.position.set(4,0,0);parent.rotation.z=Math.PI/2;parent.visible=false;
    const moon=new THREE.Mesh(new THREE.SphereGeometry(1),new THREE.MeshBasicMaterial());
    moon.position.set(2,0,0);moon.scale.setScalar(3);parent.add(moon);scene.add(parent);
    const camera=new THREE.PerspectiveCamera(50,16/9);camera.position.z=20;
    const result=captureContinuity(scene,camera,{Moon:moon});
    expect(result.actors.Moon!.position[0]).toBeCloseTo(4);
    expect(result.actors.Moon!.position[1]).toBeCloseTo(2);
    expect(result.actors.Moon!.rotation[0]).toBeCloseTo(Math.cos(Math.PI/4));
    expect(result.actors.Moon!.rotation[3]).toBeCloseTo(Math.sin(Math.PI/4));
    expect(result.actors.Moon!.visible).toBe(false);
    expect(result.actors.Moon!.radius).toBeCloseTo(3,4);
    expect(result.camera.sensor_width).toBe(camera.getFilmWidth());
  });
  it('records camera roll and evaluated orthographic zoom',()=>{
    const scene=new THREE.Scene(),camera=new THREE.OrthographicCamera(-8,8,4.5,-4.5);
    camera.rotation.z=-Math.PI/2;camera.zoom=2;
    const result=captureContinuity(scene,camera);
    expect(result.camera.ortho_scale).toBe(8);
    expect(result.camera.rotation[3]).toBeCloseTo(-Math.SQRT1_2);
  });
});
