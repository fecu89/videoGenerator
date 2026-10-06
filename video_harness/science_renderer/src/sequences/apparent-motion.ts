import * as T from 'three';
import type {SequenceRenderJob,SequenceStateSample} from '../render-job.js';
import type {SequenceRuntime} from './contracts.js';
import {canonicalFrameForOutput,stateFingerprint} from './contracts.js';
import {captureContinuity} from './continuity-capture.js';
import {FullCycleVisual} from './apparent-motion-full-cycle.js';
import {marsPosition} from './apparent-motion-geometry.js';
const TAU=2*Math.PI,v=(x:number,y:number,z:number)=>new T.Vector3(x,y,z);
export const orbitPosition=(d:number,r:number,p:number)=>v(r*Math.cos(TAU*d/p),r*Math.sin(TAU*d/p),0);
export const apparentLongitude=(d:number,inner=false)=>{const p=orbitPosition(d,inner?.72:1.52,inner?224.7:686.98).sub(orbitPosition(d,1,365.25));return Math.atan2(p.y,p.x);};
export const unwrap=(a:number,r:number)=>r+Math.atan2(Math.sin(a-r),Math.cos(a-r));
const smooth=(a:number,b:number,x:number)=>T.MathUtils.smootherstep(x,a,b),mix=(a:T.Vector3,b:T.Vector3,p:number)=>a.clone().lerp(b,p);
const C={earth:'#6cbdff',mars:'#ffa074',venus:'#ffe0a0',white:'#f3f5fc',muted:'#9eacc3',gold:'#ffc76a'};
/** Opt-in presentation with canonical physical time and evaluated continuity telemetry. */
export class ApparentMotionRuntime implements SequenceRuntime {
 scene=new T.Scene();camera=new T.PerspectiveCamera(38,1,.005,300);hudScene=new T.Scene();hudCamera=new T.OrthographicCamera(-960,960,540,-540,.01,10);
 canvas=document.createElement('canvas');ctx:CanvasRenderingContext2D;hudTexture:T.CanvasTexture;
 earth:T.Mesh;mars:T.Mesh;venus:T.Mesh;sun:T.Mesh;orbits=new T.Group();world=new T.Group();sight:T.Line;history:T.Line;arc:T.Line;sunRay:T.Line;observer:T.Mesh;ground:T.Mesh;
 earthArrow=new T.ArrowHelper(v(0,1,0),v(1,0,0),.19,0x6cbdff,.055,.035);planetArrow=new T.ArrowHelper(v(0,1,0),v(1.52,0,0),.19,0xffd098,.055,.035);second=new T.Group();secondEarth:T.Mesh;secondVenus:T.Mesh;target=new T.Vector3();snapshot?:SequenceStateSample;frame=0;day=0;mode='';progress=0;
 fullCycle?:FullCycleVisual;
 private constructor(public job:SequenceRenderJob,textures:Record<string,T.Texture>){
  this.scene.background=new T.Color('#040917');this.canvas.width=1920;this.canvas.height=1080;this.ctx=this.canvas.getContext('2d')!;
  this.hudTexture=new T.CanvasTexture(this.canvas);this.hudTexture.colorSpace=T.SRGBColorSpace;
  const hud=new T.Mesh(new T.PlaneGeometry(1920,1080),new T.MeshBasicMaterial({map:this.hudTexture,transparent:true,depthTest:false,toneMapped:false}));hud.position.z=-1;this.hudScene.add(hud);this.hudCamera.position.z=1;
  this.scene.add(this.earthArrow,this.planetArrow);this.scene.add(this.world,this.orbits,new T.AmbientLight(0xb7c7ed,.6));const key=new T.PointLight(0xfff4e1,5,0,0);this.scene.add(key);
  const make=(name:string,r:number,tex:string)=>{const m=new T.Mesh(new T.SphereGeometry(r,48,32),new T.MeshStandardMaterial({map:textures[tex]!,roughness:1}));m.name=name;m.rotation.x=Math.PI/2;this.world.add(m);return m;};
  this.earth=make('Earth',.115,'earth');this.mars=make('Mars',.088,'mars');this.venus=make('Venus',.108,'venus');
  this.sun=new T.Mesh(new T.SphereGeometry(.16,40,24),new T.MeshBasicMaterial({color:C.gold}));this.sun.name='Sun';this.world.add(this.sun);
  const clouds=new T.Mesh(new T.SphereGeometry(.1165,40,24),new T.MeshStandardMaterial({map:textures.earth_clouds!,alphaMap:textures.earth_clouds!,transparent:true,opacity:.6,depthWrite:false}));this.earth.add(clouds);
  for(const [r,col] of [[1,C.earth],[1.52,C.mars],[.72,C.venus]] as const){const l=this.line(col,.36);this.setLine(l,Array.from({length:241},(_,i)=>v(r*Math.cos(i*TAU/240),r*Math.sin(i*TAU/240),0)));this.orbits.add(l);}
  this.sight=this.line('#e6ebf7',.8);this.history=this.line(C.mars,.9);this.arc=this.line(C.gold);this.sunRay=this.line(C.gold,.7);this.scene.add(this.sight,this.history,this.arc,this.sunRay);
  this.observer=new T.Mesh(new T.SphereGeometry(.0045,16,12),new T.MeshBasicMaterial({color:'white'}));this.scene.add(this.observer);
  this.ground=new T.Mesh(new T.PlaneGeometry(30,7.5),new T.MeshBasicMaterial({color:'#27384f',side:T.DoubleSide}));this.ground.rotation.x=Math.PI/2;this.ground.position.set(0,-.15,-3.75);this.scene.add(this.ground);
  const pts:number[]=[];let seed=20260919;const rand=()=>{seed=(1664525*seed+1013904223)>>>0;return seed/4294967296;};for(let i=0;i<1500;i++){const z=rand()*2-1,a=rand()*TAU,r=Math.sqrt(1-z*z);pts.push(80*r*Math.cos(a),80*r*Math.sin(a),80*z);}
  const geo=new T.BufferGeometry();geo.setAttribute('position',new T.Float32BufferAttribute(pts,3));this.scene.add(new T.Points(geo,new T.PointsMaterial({color:0xc2d3ec,size:.12,sizeAttenuation:true})));
  if(job.timeline[0]?.controller_options.full_cycle_revision){
   this.fullCycle=new FullCycleVisual(this);
   this.setLine(this.orbits.children[1] as T.Line,Array.from({length:241},(_,i)=>marsPosition(686.98*i/240)));
  }
  this.secondEarth=this.earth.clone();this.secondVenus=this.venus.clone();this.second.add(this.secondEarth,this.secondVenus,this.sun.clone());this.scene.add(this.second);
  for(const r of [.72,1]){const l=this.line(r===1?C.earth:C.venus,.4);this.setLine(l,Array.from({length:181},(_,i)=>v(r*Math.cos(i*TAU/180),r*Math.sin(i*TAU/180),0)));this.second.add(l);}
 }
 static async create(job:SequenceRenderJob){const urls=job.timeline[0]!.controller_options.texture_urls as Record<string,string>;if(!urls)throw new Error('Texture URLs missing');const pairs=await Promise.all(Object.entries(urls).map(async([key,url])=>{const tex=await new T.TextureLoader().loadAsync(url);tex.colorSpace=T.SRGBColorSpace;tex.anisotropy=4;return [key,tex] as const;}));for(const key of ['earth','earth_clouds','venus','mars'])if(!pairs.some(([k])=>k===key))throw new Error(`Missing texture ${key}`);return new ApparentMotionRuntime(job,Object.fromEntries(pairs));}
 line(color:string,opacity=1){return new T.Line(new T.BufferGeometry(),new T.LineBasicMaterial({color,transparent:true,opacity,depthWrite:false}));}
 setLine(l:T.Line,p:T.Vector3[]){l.geometry.dispose();l.geometry=new T.BufferGeometry().setFromPoints(p.length>1?p:[v(0,0,0),v(0,0,0)]);}
 point(d:number,inner:boolean){if(this.fullCycle&&!inner)return marsPosition(d);return orbitPosition(d,inner?.72:1.52,inner?224.7:686.98);}
 pose(pos:T.Vector3,target:T.Vector3,fov=38){this.camera.position.copy(pos);this.target.copy(target);this.camera.up.set(0,0,1);this.camera.fov=fov;this.camera.lookAt(target);this.camera.updateProjectionMatrix();}
 renderFrame(outputFrame:number){
  const f=canonicalFrameForOutput(outputFrame,this.job.output.fps,this.job.canonical_fps,this.job.duration_frames);this.frame=f;const cache=this.job.canonical_state_cache[f]!;this.day=cache.simulation_time;
  const item=this.job.timeline.find(b=>f>=b.start_frame&&f<b.end_frame)!;this.mode=String(item.controller_options.view_mode);this.progress=(f-item.start_frame)/Math.max(1,item.end_frame-item.start_frame-1);
  const d=this.day,mode=this.mode,inner=mode.startsWith('venus');
  this.earth.position.copy(orbitPosition(d,1,365.25));this.mars.position.copy(this.point(d,false));this.venus.position.copy(this.point(d,true));
  this.earth.rotation.set(Math.PI/2,0,0);if(!this.fullCycle)this.earth.rotateY(d*TAU);this.mars.rotation.set(Math.PI/2,0,0);if(!this.fullCycle)this.mars.rotateY(d*TAU/1.026);this.venus.rotation.set(Math.PI/2,0,0);if(!this.fullCycle)this.venus.rotateY(-d*TAU/243);
  this.world.position.set(0,0,0);this.orbits.position.set(0,0,0);this.earth.scale.setScalar(1);this.mars.scale.setScalar(1);this.venus.scale.setScalar(1);this.sun.position.set(0,0,0);this.sun.scale.setScalar(1);
  this.earth.visible=true;this.mars.visible=!inner;this.venus.visible=inner;this.sun.visible=true;this.orbits.visible=true;this.orbits.children.forEach((o,i)=>o.visible=inner?i!==1:i!==2);
  this.sight.visible=false;this.history.visible=false;this.arc.visible=false;this.sunRay.visible=false;this.observer.visible=false;this.ground.visible=false;this.second.visible=false;
  this.camera.aspect=this.job.output.width*.68/this.job.output.height;
  const e=this.earth.position,m=this.mars.position,p=inner?this.venus.position:m;
  const orbitalView=!mode.includes('night')&&!mode.includes('evening')&&!mode.includes('morning')&&mode!=='mars_sky'&&mode!=='mars_pullback'&&mode!=='comparison';this.earthArrow.setLength(.19,.055,.035);this.earthArrow.visible=orbitalView;this.planetArrow.visible=orbitalView;
  for(const [arrow,pos] of [[this.earthArrow,e],[this.planetArrow,p]] as const){const a=Math.atan2(pos.y,pos.x)+.24,r=pos.length();arrow.position.set(r*Math.cos(a),r*Math.sin(a),.005);arrow.setDirection(v(-Math.sin(a),Math.cos(a),0));}
  if(this.fullCycle)this.fullCycle.group.visible=false;
  if(this.fullCycle&&mode.startsWith('mars_cycle')){this.fullCycle.update();
  }else if(mode.startsWith('mars')){
   const reveal=smooth(281,417,f),projection=smooth(659,800,f),near=e.clone().add(v(.13,0,.012)),nearTarget=near.clone().add(v(3,.35,0).normalize().multiplyScalar(m.distanceTo(near)));
   this.pose(mix(mix(near,v(1.75,-1.45,1.55),reveal),v(2.1,-2.5,3.0),projection),mix(mix(nearTarget,mix(e.clone().add(m).multiplyScalar(.5),v(1.0,0,0),smooth(417,550,f)),reveal),v(.65,0,0),projection),T.MathUtils.lerp(24,38,reveal));
   this.sun.visible=reveal>.02;this.orbits.visible=reveal>.02;
   if(reveal>.02){this.sight.visible=mode==='mars_projection'||mode==='mars_pullback';this.setLine(this.sight,[e.clone(),m.clone(),e.clone().add(m.clone().sub(e).multiplyScalar(4))]);}
   this.history.visible=true;const pts=[];for(let t=-60;t<=d;t+=.35){const a=apparentLongitude(t);pts.push(v(12*Math.cos(a),12*Math.sin(a),.025));}this.setLine(this.history,pts);
  }else if(mode.startsWith('opposition')){
   const top=smooth(0,309,f),night=smooth(510,this.fullCycle?710:605,f),base=mix(v(2.1,-2.6,2.8),v(.75,-.02,2.75),top);
   this.pose(mix(base,e.clone().add(v(.23,-.48,.33)),night),mix(v(.7,0,0),e,night));this.observer.visible=night>.01;
   const a=this.fullCycle?0:-Math.PI/2+Math.PI*T.MathUtils.clamp((f-510)/200,0,1);this.observer.position.copy(e).add(v(.119*Math.cos(a),.119*Math.sin(a),0));if(night>.9){this.earthArrow.visible=true;this.earthArrow.position.copy(e).add(v(.14,0,0));this.earthArrow.setDirection(v(1,0,0));this.earthArrow.setLength(.11,.025,.018);}
   if(f>=309&&f<600){this.sight.visible=true;this.setLine(this.sight,[v(0,0,0),e.clone(),m.clone()]);}
  }else if(mode==='venus_elongation'){
   this.pose(v(1.0,-1.6,2.5).applyAxisAngle(v(0,0,1),-.15+.3*this.progress),v(.25,0,0));this.sight.visible=true;this.sunRay.visible=true;this.arc.visible=true;
   this.setLine(this.sight,[e.clone(),p.clone()]);this.setLine(this.sunRay,[e.clone(),v(0,0,0)]);const a=Math.atan2(-e.y,-e.x),b=unwrap(Math.atan2(p.y-e.y,p.x-e.x),a);
   this.setLine(this.arc,Array.from({length:50},(_,i)=>e.clone().add(v(.3*Math.cos(a+(b-a)*i/49),.3*Math.sin(a+(b-a)*i/49),.007))));
  }else if(mode==='venus_evening'||mode==='venus_morning'){
   const morning=mode==='venus_morning',alt=morning?-.7+1.5*this.progress:1-1.4*this.progress;
   this.earth.visible=false;this.mars.visible=false;this.orbits.visible=false;this.pose(v(0,-5,1),v(0,0,1));
   this.sun.position.set((morning?-.8:-.1)+this.progress,0,alt);this.venus.position.set((morning?-.1:-.8)+this.progress,0,alt+.52);this.sun.scale.setScalar(.7);this.venus.scale.setScalar(.8);this.ground.visible=true;
  }else if(mode==='comparison'){
   this.camera.aspect=this.job.output.width/this.job.output.height;this.world.position.x=-1.9;this.orbits.position.x=-1.9;this.second.visible=true;this.second.position.x=1.9;this.venus.visible=false;
   this.secondEarth.position.copy(e);this.secondEarth.rotation.copy(this.earth.rotation);this.secondVenus.position.copy(this.point(d,true));this.secondVenus.rotation.copy(this.venus.rotation);this.pose(v(0,-3.1,6.1),v(0,0,0),42);
  }else{
   const project=smooth(436,535,f);this.pose(mix(v(1.4,-1.1,1.75),v(1.7,-1.9,2.8),project),v(.5,0,0));
   if(mode==='venus_conjunction'||mode==='venus_projection'){this.sight.visible=true;const delta=p.clone().sub(e);this.setLine(this.sight,[e.clone(),p.clone(),e.clone().add(delta.multiplyScalar(mode==='venus_projection'?4:1))]);}
  }
  if(this.fullCycle&&mode==='opposition_night')this.observer.visible=false;
  this.camera.updateMatrixWorld(true);this.scene.updateMatrixWorld(true);this.paint();
  const state={canonical_frame:f,simulation_time:d,visible_layers:[mode],geometry_operation_keys:['physical-orbits','textured-planets',mode],camera:{position:this.camera.position.toArray() as [number,number,number],target:this.target.toArray() as [number,number,number]},entity_scales:{earth:this.earth.scale.x,mars:this.mars.scale.x,innerPlanet:this.venus.scale.x},continuity:captureContinuity(this.scene,this.camera,{earth:this.earth,mars:this.mars,innerPlanet:this.venus,sun:this.sun,...(this.fullCycle?{skyProjection:this.fullCycle.point}:{})})};if(this.fullCycle&&mode.startsWith('mars_cycle')){
   const paths:Record<string,number[][]>={};
   for(const [name,line] of [['sightline',this.sight],['skyTrack',this.history]] as const){const pos=line.geometry.getAttribute('position');paths[name]=Array.from({length:pos?.count??0},(_,i)=>v(pos.getX(i),pos.getY(i),pos.getZ(i)).applyMatrix4(line.matrixWorld).toArray());}
   state.continuity.paths=paths;
  }
  this.snapshot={...state,state_fingerprint:stateFingerprint(state)};
 }
 text(s:string,x:number,y:number,size=64,color=C.white,weight=700){this.ctx.fillStyle=color;this.ctx.font=`${weight} ${size}px "Apple SD Gothic Neo", "Noto Sans CJK KR", sans-serif`;this.ctx.fillText(s,x,y);}
 label(mesh:T.Object3D,name:string,col:string){if(!mesh.visible)return;if((this.mode==='venus_evening'||this.mode==='venus_morning')&&mesh.position.z<0)return;const p=new T.Vector3();mesh.getWorldPosition(p);p.project(this.camera);if(Math.abs(p.x)>1||Math.abs(p.y)>1||p.z>1)return;const w=this.mode==='comparison'?1920:1920*.68;const radius=mesh instanceof T.Mesh?(mesh.geometry.boundingSphere?.radius??.1)*mesh.getWorldScale(new T.Vector3()).x:0;const depth=mesh.getWorldPosition(new T.Vector3()).sub(this.camera.position).length();const pxRadius=540*radius/(depth*Math.tan(this.camera.fov*Math.PI/360));if(this.mode==='comparison'){this.text(name,(p.x+1)*w/2-35,(1-p.y)*540+(name==='지구'?-60:90),38,col,600);return;}this.text(name,(p.x+1)*w/2+pxRadius+15,(1-p.y)*540-5,38,col,600);}
 chart(inner:boolean,x:number,y:number,w:number,h:number,start:number,end:number,current:number){
  const c=this.ctx,ref=apparentLongitude(start,inner),samples=Array.from({length:241},(_,i)=>{const d=start+(end-start)*i/240;return {d,lon:unwrap(apparentLongitude(d,inner),ref)};});const min=Math.min(...samples.map(p=>p.lon)),max=Math.max(...samples.map(p=>p.lon));
  const pt=(d:number,lon:number)=>[x+w*(.1+.8*(max-lon)/(max-min)),y+h*.5];
  c.save();c.strokeStyle='#344459';c.lineWidth=2;for(let k=0;k<6;k++){const sx=x+k*w/5;c.beginPath();c.moveTo(sx,y);c.lineTo(sx,y+h);c.stroke();}this.text('배경별에 대한 위치',x,y-95,34,C.muted,500);this.text('동',x,y-25,34,C.muted);this.text('서',x+w-35,y-25,34,C.muted);
  c.strokeStyle=inner?C.venus:C.mars;c.lineWidth=6;c.lineJoin='round';c.beginPath();let first=true;for(const p of samples){if(p.d>current)break;const [px,py]=pt(p.d,p.lon);if(first)c.moveTo(px!,py!);else c.lineTo(px!,py!);first=false;}c.stroke();const [px,py]=pt(current,unwrap(apparentLongitude(current,inner),ref));c.fillStyle=inner?C.venus:C.mars;c.beginPath();c.arc(px!,py!,9,0,TAU);c.fill();const previous=unwrap(apparentLongitude(current-.05,inner),ref);const now=unwrap(apparentLongitude(current,inner),ref);this.text(now<previous?'역행 →':'← 순행',x+110,y+h-10,44,inner?C.venus:C.mars);c.restore();
 }
 paint(){
  this.ctx.clearRect(0,0,1920,1080);if(this.fullCycle&&this.mode.startsWith('mars_cycle')){this.fullCycle.paint();return;}const x=1340,mode=this.mode;const beat=this.job.timeline.find(b=>this.frame>=b.start_frame&&this.frame<b.end_frame)!;this.ctx.globalAlpha=Math.min(smooth(beat.start_frame,beat.start_frame+12,this.frame),1-smooth(beat.end_frame-13,beat.end_frame-1,this.frame));if(mode==='mars_pullback'){this.hudTexture.needsUpdate=true;return;}
  const titles:Record<string,string[]>={mars_sky:['왜 뒤로','갈까?'],mars_pullback:[],mars_overtake:['지구가','더 빠르다'],mars_projection:['순행 · 유 · 역행'],opposition_reveal:['태양은','어느 쪽?'],opposition_alignment:['충'],opposition_night:['태양 반대편','밤새 관측'],venus_elongation:['이각','최대이각'],venus_evening:['태양의 동쪽','저녁 서쪽 하늘'],venus_morning:['태양의 서쪽','새벽 동쪽 하늘'],venus_approach:['금성도','역행할까?'],venus_conjunction:['내합','금성이 추월'],venus_projection:['같은 원리','바뀐 추월자']};
  if(mode!=='comparison'){
   this.text(mode.startsWith('venus')?'금성의 겉보기 운동':mode.startsWith('opposition')?'충과 관측 시간':'화성의 겉보기 운동',x,190,30,C.muted,500);
   for(const [i,t] of (titles[mode]??[]).entries())this.text(t,x,350+i*98,mode==='opposition_alignment'?110:mode==='mars_projection'?55:64);
   if(mode==='mars_sky'){this.text('북',600,90,30,C.muted);this.text('동',75,560,34,C.muted);this.text('서',1220,560,34,C.muted);this.chart(false,x,650,490,250,-60,60,this.day);}
   if(mode==='mars_projection')this.chart(false,x,560,490,350,-60,60,this.day);
   if(mode==='venus_projection')this.chart(true,x,580,490,300,-30,18,this.day);
   if(mode==='venus_elongation'){this.text('태양과 벌어진 각',x,640,42,C.gold,500);this.text(this.progress>.8?'가장 크게 벌어질 때':'금성을 따라 변하는 이각',x,735,36,C.muted,500);}
   if(mode==='opposition_night'){this.text('저녁 → 한밤 → 새벽',x,650,35,C.muted,500);const normal=this.observer.position.clone().sub(this.earth.position),view=this.camera.position.clone().sub(this.earth.position);if(normal.dot(view)>0&&this.observer.visible){const p=this.observer.position.clone().project(this.camera),sx=(p.x+1)*1920*.68/2,sy=(1-p.y)*540;this.ctx.strokeStyle='#9eacc3';this.ctx.lineWidth=2;this.ctx.beginPath();this.ctx.moveTo(sx+14,sy);this.ctx.lineTo(1245,sy);this.ctx.lineTo(1310,765);this.ctx.stroke();this.text('지표 관측자',x,780,38,C.white,500);}if(this.earthArrow.visible){const p=this.earth.position.clone().add(v(.27,0,0)).project(this.camera);this.text('화성 방향',(p.x+1)*1920*.68/2+10,(1-p.y)*540+15,30,C.earth,500);}}
   if(mode==='venus_evening'||mode==='venus_morning')this.text(mode==='venus_evening'?'서쪽 지평선':'동쪽 지평선',80,820,42,C.muted);
   if(mode==='mars_overtake'||mode==='venus_approach'||mode==='venus_conjunction'){this.text('공전 방향 ↺',x,690,42,C.muted,500);this.text(mode.startsWith('venus')?'금성 225일 · 지구 365일':'지구 365일 · 화성 687일',x,765,34,C.muted,500);}
   if(mode!=='mars_sky'&&mode!=='mars_pullback'){this.label(this.earth,'지구',C.earth);this.label(this.mars,'화성',C.mars);this.label(this.venus,'금성',C.venus);this.label(this.sun,'태양',C.gold);}
  }else{this.text('화성',130,120,70,C.mars);this.text('지구가 추월',130,205,54);this.text('금성',1080,120,70,C.venus);this.text('금성이 추월',1080,205,54);this.text('겉보기 운동 = 행성의 운동 + 지구의 운동',380,980,58);this.label(this.earth,'지구',C.earth);this.label(this.mars,'화성',C.mars);this.label(this.secondEarth,'지구',C.earth);this.label(this.secondVenus,'금성',C.venus);}
  this.hudTexture.needsUpdate=true;
 }
 draw(renderer:T.WebGLRenderer){const w=this.job.output.width,h=this.job.output.height;renderer.setViewport(0,0,w,h);renderer.setScissorTest(false);renderer.clear();renderer.setViewport(0,0,this.mode==='comparison'?w:Math.round(w*.68),h);renderer.render(this.scene,this.camera);renderer.autoClear=false;renderer.clearDepth();renderer.setViewport(0,0,w,h);renderer.render(this.hudScene,this.hudCamera);renderer.autoClear=true;}
 stateSnapshot(){if(!this.snapshot)throw new Error('No frame evaluated');return structuredClone(this.snapshot);}
}
