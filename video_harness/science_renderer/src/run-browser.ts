/** Browser adapter shared by all run-authored graphs. */
import * as THREE from 'three';
import type {RenderJob, RunSequenceRenderJob, SequenceStateSample} from './render-job.js';
import {createRunSource, type RunSequenceRuntime} from './run-source-loader.js';
import {captureContinuity} from './sequences/continuity-capture.js';
import {stateFingerprint} from './sequences/contracts.js';
import {classifyRenderer} from './render-telemetry.js';
import {PRODUCTION_RENDERER_BACKEND} from './browser-launch.js';

let renderer: THREE.WebGLRenderer;
let runtime: RunSequenceRuntime;
let active: RunSequenceRenderJob;

window.scienceRenderer = {
  async initialize(job: RenderJob) {
    active = job as RunSequenceRenderJob;
    const canvas = document.querySelector<HTMLCanvasElement>('#science-canvas');
    if (!canvas) throw new Error('science canvas is missing');
    renderer = new THREE.WebGLRenderer({canvas, antialias:true, preserveDrawingBuffer:true});
    renderer.setPixelRatio(1);
    renderer.setSize(job.output.width, job.output.height, false);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    runtime = await createRunSource(active);
  },
  renderFrame(index: number) {
    runtime.renderFrame(index);
    renderer.render(runtime.scene, runtime.camera);
  },
  stateSnapshot(): SequenceStateSample {
    const sample = {...runtime.stateSnapshot(), continuity:captureContinuity(runtime.scene, runtime.camera)};
    const {state_fingerprint: _, ...state} = sample;
    return {...state, state_fingerprint:stateFingerprint(state)};
  },
  backendInfo() {
    const context = renderer.getContext();
    const debug = context.getExtension('WEBGL_debug_renderer_info');
    const vendor = String(context.getParameter(debug ? debug.UNMASKED_VENDOR_WEBGL : context.VENDOR));
    const name = String(context.getParameter(debug ? debug.UNMASKED_RENDERER_WEBGL : context.RENDERER));
    return {requested:active.renderer_backend ?? PRODUCTION_RENDERER_BACKEND,
      actual:classifyRenderer({vendor,renderer:name}), vendor,renderer:name};
  },
};
