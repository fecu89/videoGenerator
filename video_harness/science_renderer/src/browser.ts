import * as THREE from 'three';

import type {Physics} from './types.js';
import {DEFAULT_PHYSICS} from './math/circular-orbit.js';
import type {
  LegacyRenderJob,
  RenderJob,
  SequenceRenderJob,
  SequenceStateSample,
} from './render-job.js';
import {createSceneController} from './scenes/scene-registry.js';
import type {SceneController} from './scenes/contracts.js';
import {
  createSequenceRuntime,
  createSequenceSceneGraph,
} from './sequences/sequence-registry.js';
import {PRODUCTION_RENDERER_BACKEND} from './browser-launch.js';
import type {SequenceRuntime} from './sequences/contracts.js';
import {
  lightingExposure,
  parseSequenceVariantProfile,
} from './sequences/variant-profile.js';
import {
  createSharedScene,
  type SharedSceneObjects,
} from './visuals/solar-system.js';
import {classifyRenderer, type RendererBackendInfo} from './render-telemetry.js';
import {ApparentMotionRuntime} from './sequences/apparent-motion.js';
import {StellarSpectraRuntime} from './sequences/stellar-spectra.js';


interface ScienceRendererApi {
  initialize(job: RenderJob): Promise<void>;
  renderFrame(frameIndex: number): void;
  stateSnapshot(): SequenceStateSample;
  backendInfo(): RendererBackendInfo;
}


declare global {
  interface Window {
    scienceRenderer: ScienceRendererApi;
  }
}


let activeJob: RenderJob | undefined;
let renderer: THREE.WebGLRenderer | undefined;
let objects: SharedSceneObjects | undefined;
let controller: SceneController | undefined;
let sequenceRuntime: SequenceRuntime | undefined;
let apparentRuntime: ApparentMotionRuntime | undefined;
let stellarRuntime: StellarSpectraRuntime | undefined;


const isSequenceJob = (job: RenderJob): job is SequenceRenderJob =>
  'job_kind' in job && job.job_kind === 'sequence';


const physicsFromJob = (job: LegacyRenderJob): Physics =>
  job.physics
    ? {
        earthPeriodDays: job.physics.earth_period_days,
        marsPeriodDays: job.physics.mars_period_days,
        earthOrbitRadius: job.physics.earth_orbit_radius,
        marsOrbitRadius: job.physics.mars_orbit_radius,
        oppositionDay: job.physics.opposition_day,
      }
    : DEFAULT_PHYSICS;


const initialize = async (job: RenderJob): Promise<void> => {
  const canvas = document.querySelector<HTMLCanvasElement>('#science-canvas');
  if (!canvas) throw new Error('science canvas is missing');

  activeJob = job;
  controller = undefined;
  sequenceRuntime = undefined;
  stellarRuntime = undefined;
  apparentRuntime = undefined;
  renderer = new THREE.WebGLRenderer({
    canvas,
    antialias: true,
    preserveDrawingBuffer: true,
    powerPreference: 'high-performance',
  });
  renderer.setPixelRatio(1);
  renderer.setSize(job.output.width, job.output.height, false);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = isSequenceJob(job)
    ? lightingExposure(parseSequenceVariantProfile(job.variant_profile))
    : 1.1;

  if (isSequenceJob(job) && job.timeline.some(item => item.controller_options.presentation === 'apparent-motion-20260919')) {
    apparentRuntime = await ApparentMotionRuntime.create(job);
    sequenceRuntime = apparentRuntime;
    return;
  }

  if (isSequenceJob(job) && job.scene_graph === 'stellar-spectra-threejs-v1') {
    renderer.toneMapping = THREE.NoToneMapping;
    stellarRuntime = new StellarSpectraRuntime(job);
    sequenceRuntime = stellarRuntime;
    return;
  }

  const sceneOptions = {
    seed: job.style.seed,
    width: job.output.width,
    height: job.output.height,
    earthScale: job.style.earth_scale,
    marsScale: job.style.mars_scale ?? 0.055,
    ...(!isSequenceJob(job) && job.eclipse
      ? {
          eclipseEarthScale: job.style.earth_scale,
          eclipseMoonScale: job.style.moon_scale ?? 1,
          eclipseSunScale: job.style.sun_scale ?? 1,
        }
      : {}),
  };
  if (isSequenceJob(job)) {
    objects = createSequenceSceneGraph(job.scene_graph, sceneOptions);
    sequenceRuntime = createSequenceRuntime(job, objects);
    return;
  }

  objects = createSharedScene(sceneOptions);
  controller = createSceneController(job.template, {
    objects,
    physics: physicsFromJob(job),
    simulationDayStart: job.simulation_day_start,
    simulationDayEnd: job.simulation_day_end,
    ...(job.camera ? {camera: job.camera} : {}),
    ...(job.renderer_options ? {rendererOptions: job.renderer_options} : {}),
    ...(job.eclipse
      ? {
          eclipse: {
            parameters: job.eclipse.parameters,
            rendererOptions: job.eclipse.renderer_options,
          },
        }
      : {}),
  });
};


const renderFrame = (frameIndex: number): void => {
  if (apparentRuntime && renderer) {
    apparentRuntime.renderFrame(frameIndex);
    apparentRuntime.draw(renderer);
    return;
  }
  if (stellarRuntime && renderer) {
    stellarRuntime.renderFrame(frameIndex);
    renderer.render(stellarRuntime.scene, stellarRuntime.camera);
    return;
  }
  if (!activeJob || !renderer || !objects) {
    throw new Error('science renderer has not been initialized');
  }
  if (isSequenceJob(activeJob)) {
    if (!sequenceRuntime) throw new Error('sequence runtime has not been initialized');
    sequenceRuntime.renderFrame(frameIndex);
    renderer.render(objects.scene, objects.camera);
    return;
  }
  if (!controller) throw new Error('legacy scene controller has not been initialized');
  const denominator = Math.max(1, activeJob.frame_count - 1);
  const progress = Math.min(1, Math.max(0, frameIndex / denominator));
  const simulationDay = THREE.MathUtils.lerp(
    activeJob.simulation_day_start,
    activeJob.simulation_day_end,
    progress,
  );
  controller.update(progress, simulationDay);
  renderer.render(objects.scene, objects.camera);
};


const stateSnapshot = (): SequenceStateSample => {
  if (!activeJob || !isSequenceJob(activeJob) || !sequenceRuntime) {
    throw new Error('sequence renderer has not been initialized');
  }
  return sequenceRuntime.stateSnapshot();
};


const backendInfo = (): RendererBackendInfo => {
  if (!activeJob || !renderer) {
    throw new Error('science renderer has not been initialized');
  }
  const context = renderer.getContext();
  const debugInfo = context.getExtension('WEBGL_debug_renderer_info');
  const vendor = String(context.getParameter(
    debugInfo ? debugInfo.UNMASKED_VENDOR_WEBGL : context.VENDOR,
  ));
  const rendererName = String(context.getParameter(
    debugInfo ? debugInfo.UNMASKED_RENDERER_WEBGL : context.RENDERER,
  ));
  return {
    requested: activeJob.renderer_backend ?? PRODUCTION_RENDERER_BACKEND,
    actual: classifyRenderer({vendor, renderer: rendererName}),
    vendor,
    renderer: rendererName,
  };
};


window.scienceRenderer = {initialize, renderFrame, stateSnapshot, backendInfo};
