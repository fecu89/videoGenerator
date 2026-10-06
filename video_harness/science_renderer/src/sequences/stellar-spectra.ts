import {captureContinuity} from './continuity-capture.js';
/** Native Three.js teaching diagrams. Positions are schematic, not measured spectra. */
import * as THREE from 'three';
import type {SequenceRenderJob, SequenceStateSample} from '../render-job.js';
import {canonicalFrameForOutput, createFrameOrderGuard, stateFingerprint} from './contracts.js';

const INK='#ddecff', CYAN='#50d2ed', GOLD='#ffbf58';
const CLASSES=['O','B','A','F','G','K','M'];
const TEMPS=[35000,15000,9000,6700,5800,4500,3200];
const COLORS=['#8baeff','#bad3ff','#edf5ff','#fff0ce','#ffdd8b','#ffac5b','#ff7651'];
const SPECTRUM_COLORS=['#9254d9','#686aff','#3abff5','#38dd95','#d2ee48','#ffb634','#ee5734'];
const H=[.08,.17,.35,.91];
const clamp=(v:number)=>Math.max(0,Math.min(1,v));
const ease=(v:number)=>{const q=clamp(v);return q*q*(3-2*q);};
export function strengths(t:number) {
  if(!(t>0))throw new Error('temperature must be positive');
  const bell=(center:number,width:number)=>Math.exp(-.5*(Math.log(t/center)/width)**2);
  return {h:.08+.78*bell(9000,.34),he:.8*bell(36000,.35),metal:.7*bell(4700,.32),molecule:.75/(1+Math.exp((t-3900)/220))};
}
const fragment=`
precision highp float;
varying vec2 vUv;
uniform float hydrogen, helium, metals, molecules, reveal;
vec3 rainbow(float x) {
 vec3 c[7];c[0]=vec3(.3,.06,.65);c[1]=vec3(.16,.2,1.);c[2]=vec3(.06,.65,1.);
 c[3]=vec3(.04,.82,.44);c[4]=vec3(.75,.9,.02);c[5]=vec3(1.,.5,.015);c[6]=vec3(.82,.04,.025);
 float u=clamp(x,0.,.99999)*6.;int i=int(floor(u));return mix(c[i],c[i+1],fract(u));
}
float line(float x,float p,float w){return 1.-smoothstep(w*.7,w,abs(x-p));}
void main(){
 float x=vUv.x;float a=0.;
 a=max(a,hydrogen*max(max(line(x,.08,.004),line(x,.17,.004)),max(line(x,.35,.004),line(x,.91,.004))));
 a=max(a,helium*max(line(x,.23,.0035),max(line(x,.54,.0035),line(x,.74,.0035))));
 a=max(a,metals*max(max(line(x,.11,.002),line(x,.26,.002)),max(line(x,.61,.002),line(x,.83,.002))));
 a=max(a,molecules*max(line(x,.56,.014),max(line(x,.69,.014),line(x,.82,.014))));
 vec3 color=mix(rainbow(x),vec3(.005,.012,.027),a*reveal);
 gl_FragColor=vec4(color,1.);
 #include <colorspace_fragment>
}`;

type Diagram={group:THREE.Group; update:(p:number,time:number)=>void};
export class StellarSpectraRuntime {
  scene=new THREE.Scene();
  camera=new THREE.OrthographicCamera(-12.2,12.2,6.8625,-6.8625,.1,100);
  private diagrams=new Map<string,Diagram>();
  private snapshot?:SequenceStateSample;
  private guard=createFrameOrderGuard();
  constructor(private job:SequenceRenderJob){
    this.scene.background=new THREE.Color(.005,.012,.027);
    this.camera.position.set(0,0,25);
    if(job.canonical_state_cache.length!==job.duration_frames)throw new Error('invalid canonical state cache');
    let lastTime=-Infinity;
    for(const [index,e] of job.canonical_state_cache.entries()){
      if(e.canonical_frame!==index||!Number.isFinite(e.simulation_time)||e.simulation_time<lastTime)throw new Error('invalid canonical state cache');
      lastTime=e.simulation_time;
    }
    for(const item of job.timeline){
      if(!this.diagrams.has(item.controller)){
        const d=this.build(item.controller);this.diagrams.set(item.controller,d);this.scene.add(d.group);
      }
    }
  }
  private label(g:THREE.Group,text:string,x:number,y:number,size=.65,color=INK){
    const c=document.createElement('canvas'),ctx=c.getContext('2d')!;
    const font='"AppleGothic", "Apple SD Gothic Neo", sans-serif';
    ctx.font=`96px ${font}`;
    c.width=Math.ceil(ctx.measureText(text).width+32);c.height=148;
    ctx.font=`96px ${font}`;ctx.fillStyle=color;ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(text,c.width/2,74);
    const texture=new THREE.CanvasTexture(c);texture.colorSpace=THREE.SRGBColorSpace;
    const mesh=new THREE.Mesh(new THREE.PlaneGeometry(size*c.width/96,size*c.height/96),new THREE.MeshBasicMaterial({map:texture,transparent:true,depthWrite:false}));
    mesh.position.set(x,y,1);mesh.name=text;g.add(mesh);return mesh;
  }
  private line(g:THREE.Group,pts:number[][],color=CYAN,width=.035){
    const group=new THREE.Group();
    for(let i=1;i<pts.length;i++){
      const a=pts[i-1]!,b=pts[i]!,dx=b[0]!-a[0]!,dy=b[1]!-a[1]!;
      const mesh=new THREE.Mesh(new THREE.PlaneGeometry(Math.hypot(dx,dy),width),new THREE.MeshBasicMaterial({color}));
      mesh.position.set((a[0]!+b[0]!)/2,(a[1]!+b[1]!)/2,.4);mesh.rotation.z=Math.atan2(dy,dx);group.add(mesh);
    }
    g.add(group);return group;
  }
  private dot(g:THREE.Group,x:number,y:number,color=GOLD,r=.18){
    const dot=new THREE.Mesh(new THREE.CircleGeometry(r,48),new THREE.MeshBasicMaterial({color}));dot.position.set(x,y,.8);g.add(dot);return dot;
  }
  private strip(g:THREE.Group,x:number,y:number,w:number,h:number,t=9000,mode='all'){
    const s=strengths(t);
    const material=new THREE.ShaderMaterial({vertexShader:'varying vec2 vUv; void main(){vUv=uv;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}',fragmentShader:fragment,
      uniforms:{hydrogen:{value:mode==='all'||mode==='h'?s.h:0},helium:{value:mode==='all'||mode==='he'?s.he:0},metals:{value:mode==='all'?s.metal:0},molecules:{value:mode==='all'?s.molecule:0},reveal:{value:1}}});
    const mesh=new THREE.Mesh(new THREE.PlaneGeometry(w,h),material);mesh.position.set(x,y,0);g.add(mesh);return mesh;
  }
  private build(controller:string):Diagram {
    const group=new THREE.Group();
    let update:Diagram['update']=()=>{};
    if(controller==='spectra-dispersion'){
      this.label(group,'빛을 나누면 드러나는 무늬',0,5.05,.83);
      this.line(group,[[-10.7,2.4],[-2.5,2.4]],INK,.15);
      this.line(group,[[-2.5,.8],[-1,4], [.5,.8],[-2.5,.8]],CYAN,.075);
      const packets:THREE.Mesh[]=[];
      for(let i=0;i<7;i++){
        this.line(group,[[0,2.4],[9.7,4-i*.55]],SPECTRUM_COLORS[i],.055);
        packets.push(this.dot(group,0,2.4,SPECTRUM_COLORS[i],.13));
      }
      const photon=this.dot(group,-9,2.4,INK,.21);
      const strip=this.strip(group,0,-1.7,21.6,2.25);
      this.label(group,'흡수선',0,-4.15,.94,GOLD);
      this.line(group,[[0,-3.4],[-3.24,-2.9]],GOLD,.035);
      update=(p,time)=>{strip.material.uniforms.reveal!.value=ease((p-.15)/.6);photon.position.x=-10+7.4*((time*.35)%1);
        packets.forEach((packet,i)=>{const q=(time*.36+i*.075)%1;packet.position.set(9.7*q,2.4+(1.6-i*.55)*q,.8);});
        strip.scale.y=.7+.3*ease(p*4);
      };
    }else if(controller==='spectra-temperature-question'){
      this.label(group,'이 무늬로 온도를 알 수 있을까?',0,4.85,.91);
      this.strip(group,0,1,21.6,2.4);
      this.label(group,'흡수선이 만들어지는 과정',0,-3.8,.81,CYAN);
      const guide=this.line(group,[[0,-.6],[0,2.6]],GOLD,.08);
      const marker=this.dot(group,0,-1.15,GOLD,.22);
      update=(p)=>{guide.position.x=-10+20*ease(p);marker.position.x=guide.position.x;};
    }else if(controller==='spectra-elements'){
      this.label(group,'같은 원소 → 같은 파장',0,5.3,.85);
      const a=this.strip(group,1,2.9,19.2,1.15,9000,'h');
      const b=this.strip(group,1,.5,19.2,1.15,9000,'h');
      const c=this.strip(group,1,-3,19.2,1.35,35000,'he');
      this.label(group,'H',-10.4,2.9,.92,CYAN);this.label(group,'H',-10.4,.5,.92,CYAN);this.label(group,'He',-10.4,-3,.86,GOLD);
      for(const pos of H){const x=-8.6+19.2*pos;this.line(group,[[x,1.1],[x,2.3]],CYAN,.025);}
      this.label(group,'수소',-7.6,-.85,.49,CYAN);this.label(group,'헬륨',-7.6,-4.45,.49,GOLD);
      const pulse=this.dot(group,-7,1.7,CYAN,.13);
      update=(p,time)=>{a.material.uniforms.reveal!.value=ease(p*3);b.material.uniforms.reveal!.value=ease((p-.12)*3);c.material.uniforms.reveal!.value=ease((p-.35)*3);pulse.position.x=-8.6+19.2*((time*.1)%1);
        [a,b,c].forEach((row,i)=>{row.scale.y=.2+.8*ease((p-i*.12)*5);});
      };
    }else if(controller==='spectra-hot'||controller==='spectra-cool'){
      const hot=controller==='spectra-hot';
      this.label(group,hot?'수소선은 A형에서 가장 강하다':'차가워도 수소선이 약해진다',0,5.25,.84);
      const px=(temp:number)=>-9.4+18.8*Math.log(temp/40000)/Math.log(3000/40000);
      const py=(temp:number)=>-1.6+5.5*strengths(temp).h;
      this.line(group,[[-9.4,-1.6],[9.4,-1.6]],INK,.035);
      this.line(group,[[-9.4,-1.6],[-9.4,3.7]],INK,.035);
      this.label(group,'선의 세기',-9.4,4.2,.44,INK);
      const curvePoints=Array.from({length:161},(_,i)=>{const t=40000*(3000/40000)**(i/160);return [px(t),py(t)];});
      this.line(group,curvePoints,'#516a87',.055);
      const trace=this.line(group,curvePoints,GOLD,.095);
      CLASSES.forEach((letter,i)=>this.label(group,letter,px(TEMPS[i]!),-2.25,.67,letter==='A'?GOLD:INK));
      this.label(group,'고온',-9.4,-3.15,.49,CYAN);this.label(group,'저온',9.4,-3.15,.49,GOLD);
      this.label(group,hot?'이온화 증가':'흡수할 상태의 수소 감소',hot?-6.1:5.7,3.7,.61,CYAN);
      const marker=this.dot(group,px(9000),py(9000),GOLD,.23);
      const strip=this.strip(group,0,-4.6,21.6,1.05,9000,'h');
      update=p=>{const temp=9000*((hot?35000:3200)/9000)**ease((p-.15)/.78);marker.position.set(px(temp),py(temp),.8);strip.material.uniforms.hydrogen!.value=strengths(temp).h;
        const left=Math.min(px(9000),px(temp)),right=Math.max(px(9000),px(temp));
        trace.children.forEach(segment=>{segment.visible=segment.position.x>=left&&segment.position.x<=right;});
      };
    }else if(controller==='spectra-classify'){
      this.label(group,'O  B  A  F  G  K  M',0,5.15,.76);
      const rows:THREE.Mesh[]=[];
      CLASSES.forEach((letter,i)=>{const y=3.75-i*1.28;this.label(group,letter,-10.4,y,.87,COLORS[i]);rows.push(this.strip(group,.6,y,19.7,.8,TEMPS[i]));});
      const box=this.line(group,[[-9.45,-.55],[10.7,-.55],[10.7,.55],[-9.45,.55],[-9.45,-.55]],GOLD,.045);
      update=p=>{box.position.y=3.75-7.68*ease((p-.28)/.65);rows.forEach((row,i)=>{row.scale.y=.15+.85*ease((p-i*.018)*7);});};
    }else if(controller==='spectra-subtype'){
      this.label(group,'같은 G형 안에서도',0,5.15,.84);
      this.strip(group,0,2.75,21.6,1.4,5800);
      this.line(group,[[-10.2,-.2],[10.2,-.2]],INK,.05);
      for(let i=0;i<10;i++){const x=-10.2+20.4*i/9;this.line(group,[[x,-.2],[x,-.7]],INK,.04);this.label(group,'G'+i,x,-1.65,.65);}
      this.label(group,'고온',-10.1,-3.1,.55,CYAN);this.label(group,'저온',10.1,-3.1,.55,GOLD);
      this.label(group,'작은 숫자가 더 뜨겁다',0,-4.95,.76);
      const marker=this.dot(group,-10.2,-.2,GOLD,.26);
      update=p=>{marker.position.x=-10.2+(40.8/9)*ease((p-.15)/.65);const q=1+.18*Math.sin(Math.PI*ease((p-.8)/.2));marker.scale.set(q,q,1);};
    }else throw new Error(`unknown stellar controller: ${controller}`);
    return {group,update};
  }
  renderFrame(outputFrame:number){
    this.guard.accept(outputFrame);
    const frame=canonicalFrameForOutput(outputFrame,this.job.output.fps,this.job.canonical_fps,this.job.duration_frames);
    const entry=this.job.canonical_state_cache[frame]!;
    const active=this.job.timeline.filter(b=>entry.active_beat_ids.includes(b.beat_id)).sort((a,b)=>b.priority-a.priority)[0];
    if(!active)throw new Error('canonical cache has no active beat');
    for(const [name,d] of this.diagrams)d.group.visible=name===active.controller;
    const diagram=this.diagrams.get(active.controller)!;
    const p=(frame-active.start_frame)/Math.max(1,active.end_frame-active.start_frame-1);
    diagram.update(p,entry.simulation_time);
    // Readable, continuous push: the widest 21.6-unit strip stays inside the frame.
    const profile=String(this.job.variant_profile?.camera_profile??'base');
    const zoom=profile==='close'?1.035:profile==='wide'?.96:1;
    this.camera.zoom=(1+.035*ease(p))*zoom;this.camera.updateProjectionMatrix();
    const actual:unknown[]=[];
    diagram.group.traverse(o=>{actual.push([o.name,o.visible,o.position.toArray(),o.scale.toArray()]);if(o instanceof THREE.Mesh&&o.material instanceof THREE.ShaderMaterial)actual.push(Object.fromEntries(Object.entries(o.material.uniforms).map(([k,v])=>[k,v.value])));});
    const base={continuity:captureContinuity(this.scene,this.camera),canonical_frame:frame,simulation_time:entry.simulation_time,visible_layers:[active.controller],geometry_operation_keys:entry.active_beat_ids,
      camera:{position:[0,0,25] as [number,number,number],target:[0,0,0] as [number,number,number]},entity_scales:{diagram:diagram.group.scale.x,camera_zoom:this.camera.zoom}};
    this.snapshot={...base,state_fingerprint:stateFingerprint({...base,entity_scales:{...base.entity_scales,geometry:JSON.stringify(actual).split('').reduce((v,c)=>(Math.imul(v,31)+c.charCodeAt(0))|0,0)}})};
  }
  stateSnapshot(){if(!this.snapshot)throw new Error('no rendered state');return this.snapshot;}
}
