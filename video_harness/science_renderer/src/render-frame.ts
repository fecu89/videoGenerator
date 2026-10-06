import {build} from 'esbuild';
import {mkdir, readFile, writeFile, access} from 'node:fs/promises';
import {dirname, join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {chromium} from 'playwright';

import type {
  FrameReport,
  LegacyFrameReport,
  LegacyRenderJob,
  RenderJob,
  SequenceFrameReport,
  SequenceRenderJob,
  SequenceStateSample,
} from './render-job.js';
import {
  chromiumLaunchOptions,
  PRODUCTION_RENDERER_BACKEND,
} from './browser-launch.js';
import {createRenderTimer} from './render-telemetry.js';
import {
  getFrameCapture,
  PRODUCTION_CAPTURE_METHOD,
  type CaptureMethod,
  type CaptureTimingMode,
} from './frame-capture.js';


export type {
  LegacyRenderJob,
  RenderJob,
  SequenceRenderJob,
} from './render-job.js';


const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');


const buildBrowserBundle = async (): Promise<string> => {
  const outputDirectory = join(packageRoot, 'dist');
  const outputPath = join(outputDirectory, 'browser.js');
  await mkdir(outputDirectory, {recursive: true});
  await build({
    entryPoints: [join(packageRoot, 'src', 'browser.ts')],
    bundle: true,
    format: 'iife',
    platform: 'browser',
    target: ['chrome120'],
    outfile: outputPath,
    logLevel: 'silent',
  });
  return outputPath;
};


const frameFilename = (frameIndex: number): string =>
  `frame-${frameIndex.toString().padStart(6, '0')}.png`;


const isSequenceJob = (job: RenderJob): job is SequenceRenderJob =>
  'job_kind' in job && job.job_kind === 'sequence';


export interface RenderJobOptions {
  /** Benchmarks may exercise a diagnostic transport; production is fixed at build time. */
  captureMethod?: CaptureMethod;
}


export function renderJob(job: LegacyRenderJob, options?: RenderJobOptions): Promise<LegacyFrameReport>;
export function renderJob(job: SequenceRenderJob, options?: RenderJobOptions): Promise<SequenceFrameReport>;
export function renderJob(job: RenderJob, options?: RenderJobOptions): Promise<FrameReport>;
export async function renderJob(job: RenderJob, options: RenderJobOptions = {}): Promise<FrameReport> {
  if (job.frame_count < 1) throw new Error('frame_count must be positive');
  if (job.output.width < 1 || job.output.height < 1) {
    throw new Error('output dimensions must be positive');
  }

  const timer = createRenderTimer();
  const initializationStarted = performance.now();
  await mkdir(job.output_directory, {recursive: true});
  const bundlePath = await buildBrowserBundle();
  const requestedBackend = job.renderer_backend ?? PRODUCTION_RENDERER_BACKEND;
  const browser = await chromium.launch(chromiumLaunchOptions(requestedBackend));
  const browserVersion = await browser.version();
  const frames: string[] = [];
  let captureTransportBytes = 0;
  let captureTimingMode: CaptureTimingMode | undefined;
  const stateSamples: SequenceStateSample[] = [];
  const requestedSamples = isSequenceJob(job) ? new Set(job.sample_frames) : undefined;
  const captureMethod = options.captureMethod ?? PRODUCTION_CAPTURE_METHOD;
  const capture = getFrameCapture(captureMethod);
  try {
    const page = await browser.newPage({
      viewport: {width: job.output.width, height: job.output.height},
      deviceScaleFactor: 1,
    });
    await page.setContent(
      `<style>html,body{margin:0;background:#020611;overflow:hidden}canvas{display:block;width:${job.output.width}px;height:${job.output.height}px}</style><canvas id="science-canvas" width="${job.output.width}" height="${job.output.height}"></canvas>`,
    );
    await page.addScriptTag({content: await readFile(bundlePath, 'utf8')});
    // Resolve opted-in texture assets on the host, then await browser image decoding.
    const browserJob = structuredClone(job);
    if (isSequenceJob(browserJob)) {
      for (const item of browserJob.timeline) {
        if (item.controller_options.presentation !== 'apparent-motion-20260919') continue;
        const files = item.controller_options.texture_files as Record<string, string>;
        const urls: Record<string, string> = {};
        for (const [key, relative] of Object.entries(files)) {
          let root = resolve(job.output_directory);
          let found: string | undefined;
          while (true) {
            const candidate = resolve(root, relative);
            try { await access(candidate); found = candidate; break; } catch {}
            const parent = dirname(root); if (parent === root) break; root = parent;
          }
          if (!found) throw new Error(`Missing planet texture: ${relative}`);
          urls[key] = `data:image/jpeg;base64,${(await readFile(found)).toString('base64')}`;
        }
        item.controller_options.texture_urls = urls;
      }
    }
    await page.evaluate((payload) => window.scienceRenderer.initialize(payload), browserJob);
    const backend = await page.evaluate(() => window.scienceRenderer.backendInfo());
    if (backend.actual !== backend.requested) {
      throw new Error(
        `requested ${backend.requested} renderer but attested ${backend.actual}: ${backend.renderer}`,
      );
    }
    timer.addInitializationMilliseconds(performance.now() - initializationStarted);
    const canvas = page.locator('#science-canvas');

    for (let frameIndex = 0; frameIndex < job.frame_count; frameIndex += 1) {
      const renderStart = performance.now();
      await page.evaluate((index) => window.scienceRenderer.renderFrame(index), frameIndex);
      timer.addRenderMilliseconds(performance.now() - renderStart);
      if (requestedSamples?.has(frameIndex)) {
        stateSamples.push(await page.evaluate(() => window.scienceRenderer.stateSnapshot()));
      }
      const path = join(job.output_directory, frameFilename(frameIndex));
      const captured = await capture.capture(page, canvas, path);
      if (captured.status === 'unsupported') {
        throw new Error(`${captured.name} is unsupported: ${captured.reason}`);
      }
      captureTimingMode = captured.captureTimingMode;
      timer.addCanvasEncodeCaptureMilliseconds(
        captured.canvasEncodeCaptureMilliseconds,
      );
      timer.addBrowserToNodeTransferMilliseconds(
        captured.browserToNodeTransferMilliseconds,
      );
      timer.addWriteMilliseconds(captured.writeMilliseconds);
      captureTransportBytes += captured.transportByteLength;
      frames.push(path);
    }
    if (!captureTimingMode) throw new Error('renderer captured no frames');
    const timings = timer.summary(frames.length);
    const report: FrameReport = isSequenceJob(job)
      ? {
          sequence_id: job.sequence_id,
          frame_count: frames.length,
          width: job.output.width,
          height: job.output.height,
          frames,
          browser_version: browserVersion,
          capture_method: captureMethod,
          capture_timing_mode: captureTimingMode,
          capture_transport_bytes: captureTransportBytes,
          state_samples: stateSamples,
          backend,
          timings,
        }
      : {
          scene_id: job.scene_id,
          frame_count: frames.length,
          width: job.output.width,
          height: job.output.height,
          frames,
          browser_version: browserVersion,
          capture_method: captureMethod,
          capture_timing_mode: captureTimingMode,
          capture_transport_bytes: captureTransportBytes,
          backend,
          timings,
        };
    await writeFile(
      join(job.output_directory, 'frame-report.json'),
      `${JSON.stringify(report, null, 2)}\n`,
      'utf8',
    );
    return report;
  } finally {
    await browser.close();
  }
}
