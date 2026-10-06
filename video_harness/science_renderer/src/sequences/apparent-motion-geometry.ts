import * as T from 'three';
const TAU=2*Math.PI;
export const earthPosition=(day:number)=>new T.Vector3(Math.cos(TAU*day/365.25),Math.sin(TAU*day/365.25),0);
/** Circular teaching model; Mars crosses its ascending node at opposition.
 * Inclination is 1.8497 degrees (JPL). This is a possible S-shaped geometry,
 * not an ephemeris for a particular dated opposition. */
export const marsPosition=(day:number)=>{
 const angle=TAU*day/686.98,i=T.MathUtils.degToRad(1.8497);
 return new T.Vector3(1.52*Math.cos(angle),1.52*Math.sin(angle)*Math.cos(i),1.52*Math.sin(angle)*Math.sin(i));
};
export const skyDirection=(day:number)=>marsPosition(day).sub(earthPosition(day)).normalize();
export const longitudeRate=(day:number)=>{
 const a=skyDirection(day-.001),b=skyDirection(day+.001);
 return Math.atan2(a.x*b.y-a.y*b.x,a.x*b.x+a.y*b.y)/.002;
};
const stations:number[]=[];
for(let d=-90;d<90;d+=1){
 if(longitudeRate(d)*longitudeRate(d+1)>=0)continue;
 let a=d,b=d+1;
 for(let j=0;j<35;j++){const m=(a+b)/2;if(longitudeRate(a)*longitudeRate(m)<=0)b=m;else a=m;}
 stations.push((a+b)/2);
}
export const marsStationDays=()=>[...stations];
export const skyStage=(day:number):string=>stations.some(d=>Math.abs(day-d)<4)?'유':longitudeRate(day)>0?'순행':'역행';
