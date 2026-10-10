import * as THREE from 'three';
import type {RunSequenceRenderJob} from './render-job.js';
import type {SequenceRuntime} from './sequences/contracts.js';
import {stateFingerprint} from './sequences/contracts.js';
import {captureContinuity} from './sequences/continuity-capture.js';
import {CalloutLayer} from './callout.js';

export interface RunSequenceRuntime extends SequenceRuntime {
  scene: THREE.Scene;
  camera: THREE.Camera;
}
const api = {THREE, captureContinuity, stateFingerprint, CalloutLayer};
export type RunSourceApi = typeof api;
export type RunSourceFactory = (job: RunSequenceRenderJob, api: RunSourceApi) => RunSequenceRuntime | Promise<RunSequenceRuntime>;
let factory: RunSourceFactory | undefined;

export function registerRunSource(value: RunSourceFactory): void {
  if (typeof value !== 'function') throw new Error('Run source export must be a factory');
  factory = value;
}

export async function createRunSource(job: RunSequenceRenderJob): Promise<RunSequenceRuntime> {
  if (!factory) throw new Error('No run source factory registered');
  const runtime = await factory(job, api);
  if (!runtime.scene?.isScene || !runtime.camera?.isCamera || typeof runtime.renderFrame !== 'function' || typeof runtime.stateSnapshot !== 'function') {
    throw new Error('Run source must return scene, camera, renderFrame and stateSnapshot');
  }
  return runtime;
}
