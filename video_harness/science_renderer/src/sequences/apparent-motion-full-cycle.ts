import * as T from 'three';
import type {ApparentMotionRuntime} from './apparent-motion.js';
import {earthPosition,marsPosition,skyDirection,marsStationDays,skyStage} from './apparent-motion-geometry.js';
const V=(x:number,y:number,z:number)=>new T.Vector3(x,y,z);
const ease=(a:number,b:number,t:number)=>T.MathUtils.smootherstep(t,a,b);
const blend=(a:T.Vector3,b:T.Vector3,t:number)=>a.clone().lerp(b,t);
const amber='#ffa074',white='#f3f5fc',muted='#9eacc3';

/** A common 3D sky dome carries stars, the sightline endpoint and its history.
 * Its radius is a diagram surface, not the distance of the background stars. */
export class FullCycleVisual {
 group=new T.Group();point:T.Mesh;stations:T.Mesh[]=[];stars:T.Points;
 skySamples=Array.from({length:721},(_,i)=>({day:-90+i/4,direction:skyDirection(-90+i/4)}));
 constructor(public host:ApparentMotionRuntime){
  this.group.name='ObservedSky';host.scene.add(this.group);
  this.point=new T.Mesh(new T.SphereGeometry(.018,16,12),new T.MeshBasicMaterial({color:amber}));
  this.point.name='SkyProjection';this.group.add(this.point);
  for(const day of marsStationDays()){
   const dot=new T.Mesh(new T.SphereGeometry(.009,12,8),new T.MeshBasicMaterial({color:white}));
   dot.position.copy(skyDirection(day).multiplyScalar(4));this.stations.push(dot);this.group.add(dot);
  }
  let seed=811;const random=()=>{seed=(1664525*seed+1013904223)>>>0;return seed/4294967296;};const points=[];
  for(let k=0;k<170;k++){const lon=(random()-.5)*.58,lat=(random()-.5)*.38;points.push(4*Math.cos(lat)*Math.cos(lon),4*Math.cos(lat)*Math.sin(lon),4*Math.sin(lat));}
  const geometry=new T.BufferGeometry();geometry.setAttribute('position',new T.Float32BufferAttribute(points,3));
  const sprite=document.createElement('canvas');sprite.width=32;sprite.height=32;
  const ctx=sprite.getContext('2d')!,gradient=ctx.createRadialGradient(16,16,0,16,16,16);
  gradient.addColorStop(0,'white');gradient.addColorStop(.35,'white');gradient.addColorStop(1,'transparent');ctx.fillStyle=gradient;ctx.fillRect(0,0,32,32);
  this.stars=new T.Points(geometry,new T.PointsMaterial({map:new T.CanvasTexture(sprite),size:.038,color:0xc4d7f3,transparent:true,opacity:.9,depthWrite:false}));this.group.add(this.stars);
 }
 update(){
  const h=this.host,e=h.earth.position,m=h.mars.position,mode=h.mode;
  for(const child of h.scene.children)if(child instanceof T.Points)child.position.copy(e);
  const sky=mode.startsWith('mars_cycle_sky'),reveal=mode==='mars_cycle_reveal';
  const beat=h.job.timeline.find(b=>h.frame>=b.start_frame&&h.frame<b.end_frame)!;
  const u=reveal?(h.frame-beat.start_frame)/(beat.end_frame-beat.start_frame-1):sky?0:1;
  const zoom=ease(0,.24,u),orbit=ease(.20,.82,u);
  const eye=e.clone(),initialTarget=e.clone().add(V(1,0,0));
  const near=m.clone().add(e.clone().sub(m).normalize().multiplyScalar(.56)).add(V(0,0,.035));
  const overview=V(-2.8,-4.6,3.2),overviewTarget=V(1.55,.08,.06);
  if(sky)h.pose(eye,initialTarget,16);
  else if(reveal)h.pose(blend(blend(eye,near,zoom),overview,orbit),blend(blend(initialTarget,m,zoom),overviewTarget,orbit),T.MathUtils.lerp(16,43,orbit));
  else h.pose(overview,overviewTarget,43);
  h.earth.scale.setScalar(T.MathUtils.lerp(.025,1.65,zoom));
  // Keep the close-up within the viewport, then grow the teaching-model
  // sphere only as the camera moves into the wide view.
  h.mars.scale.setScalar(T.MathUtils.lerp(T.MathUtils.lerp(.015,.68,zoom),1.65,orbit));
  h.sun.scale.setScalar(.7);
  h.earth.visible=!sky;h.sun.visible=!sky&&(!reveal||orbit>.12);h.orbits.visible=h.sun.visible;
  h.earthArrow.visible=!sky&&(!reveal||orbit>.7);h.planetArrow.visible=h.earthArrow.visible;
  h.venus.visible=false;
  this.group.visible=true;this.group.position.copy(e);
  this.point.position.copy(skyDirection(h.day).multiplyScalar(4));
  this.point.visible=!sky&&(!reveal||orbit>.85);
  (this.stars.material as T.PointsMaterial).opacity=sky?.85:reveal?T.MathUtils.lerp(.85,.5,orbit):.5;
  h.history.visible=true;
  const history=this.skySamples.filter(s=>s.day<=Math.min(h.day,90)).map(s=>e.clone().add(s.direction.clone().multiplyScalar(4)));
  history.push(e.clone().add(skyDirection(Math.min(h.day,90)).multiplyScalar(4)));
  h.setLine(h.history,history);
  (h.history.material as T.LineBasicMaterial).opacity=sky?.72:reveal?T.MathUtils.lerp(.72,.65,orbit):.65;
  for(const [i,dot] of this.stations.entries())dot.visible=h.day>=marsStationDays()[i]!;
  h.sight.visible=!sky&&(!reveal||orbit>.85);
  if(h.sight.visible)h.setLine(h.sight,[e.clone(),m.clone(),e.clone().add(skyDirection(h.day).multiplyScalar(4))]);
 }
 pixel(p:T.Vector3){const h=this.host,q=p.clone().project(h.camera);return {x:(q.x+1)*1920*.68/2,y:(1-q.y)*540,z:q.z};}
 paint(){
  const h=this.host,c=h.ctx,mode=h.mode,sky=mode.startsWith('mars_cycle_sky'),reveal=mode==='mars_cycle_reveal';
  const beat=h.job.timeline.find(b=>h.frame>=b.start_frame&&h.frame<b.end_frame)!;
  c.globalAlpha=1;
  if(reveal){
   const fade=ease(.72,.92,h.progress);c.globalAlpha=fade;
   h.text('같은 방향의 공전',1340,260,56);h.text('지구가 더 빠르다',1340,355,56);
   h.text('지구 365일',1340,590,42,'#6cbdff');h.text('화성 687일',1340,665,42,amber);
   this.planetLabels();
   h.hudTexture.needsUpdate=true;return;
  }
  const stage=skyStage(h.day);
  h.text(sky?'별들 사이의 화성':'시선이 만드는 궤적',1340,190,40,muted,500);
  h.text(stage,1340,330,100,stage==='역행'?amber:white);
  h.text(stage==='유'?'방향이 바뀌는 순간':stage==='순행'?'서 → 동':'동 → 서',1340,405,42,muted,500);
  const days=marsStationDays(),active=h.day<days[0]!-4?0:h.day<days[0]!+4?1:h.day<days[1]!-4?2:h.day<days[1]!+4?3:4;
  if(sky){
   c.strokeStyle=amber;c.globalAlpha=.65;c.lineWidth=3;c.lineJoin='round';c.beginPath();let first=true;
   for(const sample of this.skySamples){if(sample.day>h.day)break;const q=this.pixel(h.earth.position.clone().add(sample.direction.clone().multiplyScalar(4)));if(first)c.moveTo(q.x,q.y);else c.lineTo(q.x,q.y);first=false;}c.stroke();c.globalAlpha=1;
   ['순행','첫 번째 유','역행','두 번째 유','다시 순행'].forEach((text,i)=>h.text(text,1385,545+i*78,i===active?56:42,i===active?amber:i<active?'#d4dfef':'#53627c',i===active?700:500));
   const p=this.pixel(h.mars.position);c.fillStyle=amber;c.shadowColor=amber;c.shadowBlur=18;c.beginPath();c.arc(p.x,p.y,5,0,Math.PI*2);c.fill();c.shadowBlur=0;
   h.text('화성',p.x+24,p.y-24,38,amber);h.text('동',70,900,40,muted);h.text('서',1200,900,40,muted);
   for(const [i,day] of days.entries()){if(h.day<day)continue;const q=this.pixel(h.earth.position.clone().add(skyDirection(day).multiplyScalar(4)));h.text('유',q.x-15,q.y+(i===0?65:-35),40);}
  }else{
   this.chart();this.planetLabels();
   const p=this.pixel(this.point.getWorldPosition(new T.Vector3()));
   if(p.x>80&&p.x<1060&&p.y>80&&p.y<900)h.text('별들 사이의 위치',p.x-70,p.y-48,32,amber,500);
   if(mode==='mars_cycle_project'&&h.frame-beat.start_frame<90){c.globalAlpha=1-ease(50,90,h.frame-beat.start_frame);h.text('처음부터 다시',90,135,46,muted,500);c.globalAlpha=1;}
  }
  h.hudTexture.needsUpdate=true;
 }
 planetLabels(){
  const h=this.host,e=this.pixel(h.earth.position),m=this.pixel(h.mars.position);
  h.text('지구',e.x-80,e.y+85,38,'#6cbdff');h.text('화성',m.x+44,m.y-28,38,amber);h.label(h.sun,'태양','#ffc76a');
 }
 chart(){
  const h=this.host,c=h.ctx,x=1360,y=580,w=470;
  const pt=(direction:T.Vector3)=>[x+w/2-Math.atan2(direction.y,direction.x)*w/.33,y+180-Math.atan2(direction.z,Math.hypot(direction.x,direction.y))*w/.33];
  h.text('지구에서 본 궤적',x,530,36,muted,500);h.text('동',x,885,32,muted);h.text('서',x+w-32,885,32,muted);
  let seed=93;for(let i=0;i<45;i++){seed=(1664525*seed+1013904223)>>>0;const px=x+(seed/4294967296)*w;seed=(1664525*seed+1013904223)>>>0;const py=y+(seed/4294967296)*265;c.fillStyle='#8398b7';c.beginPath();c.arc(px,py,1.4,0,Math.PI*2);c.fill();}
  c.strokeStyle=amber;c.lineWidth=4;c.lineJoin='round';c.beginPath();let first=true;
  for(const s of this.skySamples){if(s.day>h.day)break;const [px,py]=pt(s.direction);if(first)c.moveTo(px!,py!);else c.lineTo(px!,py!);first=false;}c.stroke();
  const [px,py]=pt(skyDirection(h.day));c.fillStyle=amber;c.beginPath();c.arc(px!,py!,7,0,Math.PI*2);c.fill();
  for(const [i,day] of marsStationDays().entries()){if(h.day<day)continue;const [sx,sy]=pt(skyDirection(day));h.text('유',sx!-12,sy!+(i===0?50:-24),30);}
 }
}
