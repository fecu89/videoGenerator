import {describe,it,expect} from 'vitest';
import {apparentLongitude,unwrap,orbitPosition} from '../src/sequences/apparent-motion.js';
import {marsPosition,skyDirection,marsStationDays,skyStage} from '../src/sequences/apparent-motion-geometry.js';
const rate=(d:number,inner=false)=>(unwrap(apparentLongitude(d+.01,inner),apparentLongitude(d-.01,inner))-apparentLongitude(d-.01,inner))/.02;
describe('apparent motion presentation geometry',()=>{
 it('all three planets orbit counterclockwise viewed from north',()=>{for(const [r,p] of [[1,365.25],[1.52,686.98],[.72,224.7]]){const a=orbitPosition(0,r!,p!),b=orbitPosition(.1,r!,p!);expect(a.clone().cross(b).z).toBeGreaterThan(0);}});
 it('opening Mars track crosses station and retrograde has east-left screen motion to right',()=>{expect(rate(-60)).toBeGreaterThan(0);expect(rate(-28)).toBeLessThan(0);expect(-rate(0)).toBeGreaterThan(0);});
 it('Venus projection remains retrograde for the full approved interval',()=>{for(let d=3.4848;d<=18;d+=.1)expect(-rate(d,true)).toBeGreaterThan(0);});
 it('elongation peaks at the tangent of the inner orbit',()=>{let max=0;for(let d=-130;d<=-71.3;d+=.02){const e=orbitPosition(d,1,365.25),p=orbitPosition(d,.72,224.7);max=Math.max(max,e.clone().negate().angleTo(p.sub(e)));}expect(max).toBeCloseTo(Math.asin(.72),4);});
});

describe('complete inclined Mars apparent cycle',()=>{
 it('projects the actual Earth to Mars direction, including orbital latitude',()=>{
  const e=orbitPosition(36,1,365.25),m=marsPosition(36),s=skyDirection(36);
  expect(m.z).toBeGreaterThan(.015);
  expect(s.clone().cross(m.sub(e)).length()).toBeLessThan(1e-12);
  expect(s.z).toBeGreaterThan(0);
  expect(skyDirection(-36).z).toBeLessThan(0);
 });
 it('has exactly two east-west reversals inside the complete visible interval',()=>{
  const stations=marsStationDays();
  expect(stations).toHaveLength(2);
  expect(stations[0]).toBeGreaterThan(-45);expect(stations[0]).toBeLessThan(-30);
  expect(stations[1]).toBeGreaterThan(30);expect(stations[1]).toBeLessThan(45);
  expect([-90,stations[0]!,0,stations[1]!,90].map(skyStage)).toEqual(['순행','유','역행','유','순행']);
 });
 it('keeps both physical planets prograde while the apparent track reverses',()=>{
  for(let d=-90;d<90;d+=3){expect(marsPosition(d).cross(marsPosition(d+.01)).z).toBeGreaterThan(0);}
  const x=(d:number)=>-Math.atan2(skyDirection(d).y,skyDirection(d).x);
  expect(x(-89)-x(-90)).toBeLessThan(0);
  expect(x(1)-x(0)).toBeGreaterThan(0);
  expect(x(90)-x(89)).toBeLessThan(0);
 });
});
