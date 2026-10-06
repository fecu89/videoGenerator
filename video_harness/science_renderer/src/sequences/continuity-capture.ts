import * as THREE from 'three';

/** Evaluated world transforms, with quaternion order w,x,y,z like Blender. */
export function captureContinuity(scene: THREE.Scene, camera: THREE.Camera,
  aliases: Record<string, THREE.Object3D> = {}) {
  scene.updateMatrixWorld(true);camera.updateMatrixWorld(true);
  const pose=(obj: THREE.Object3D)=>{
    const p=new THREE.Vector3(),q=new THREE.Quaternion(),s=new THREE.Vector3();
    obj.matrixWorld.decompose(p,q,s);
    return {position:p.toArray(),rotation:[q.w,q.x,q.y,q.z],scale:s.toArray()};
  };
  const actors: Record<string,ReturnType<typeof pose>&{radius:number;visible:boolean}>={};
  const record=(name:string,obj:THREE.Object3D)=>{
    if(!(obj instanceof THREE.Mesh))return;
    if(!obj.geometry.boundingSphere)obj.geometry.computeBoundingSphere();
    const p=pose(obj);let visible=true;
    for(let n:THREE.Object3D|null=obj;n;n=n.parent)visible=visible&&n.visible;
    actors[name]={...p,radius:Math.max(1e-6,(obj.geometry.boundingSphere?.radius??1)*Math.max(...p.scale.map(Math.abs))),visible};
  };
  const walk=(obj:THREE.Object3D,path:string)=>{
    record(path,obj);obj.children.forEach((child,i)=>walk(child,`${path}/${child.name||child.type}[${i}]`));
  };
  walk(scene,'scene');Object.entries(aliases).forEach(([name,obj])=>record(name,obj));
  const ortho=camera instanceof THREE.OrthographicCamera;
  const perspective=camera instanceof THREE.PerspectiveCamera;
  return {camera:{...pose(camera),projection:ortho?'ORTHO':'PERSP',
    ortho_scale:ortho?(camera.right-camera.left)/camera.zoom:1,
    lens:perspective?camera.getFocalLength():50,
    sensor_width:perspective?camera.getFilmWidth():36},actors,paths:{}};
}
