import {createHash} from 'node:crypto';
import {execFile} from 'node:child_process';
import {mkdtemp, readFile, rename, rm, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {basename, dirname, join} from 'node:path';
import {promisify} from 'node:util';

import {PNG} from 'pngjs';

import {createFrameCaptures, type CaptureMethod} from './frame-capture.js';
import {PRODUCTION_RENDERER_BACKEND} from './browser-launch.js';
import {renderJob} from './render-frame.js';
import type {RenderJob} from './render-job.js';


export interface CaptureBenchmarkSummary {
  method: CaptureMethod;
  medianWallMilliseconds: number;
  peakRssBytes: number;
  integrity: boolean;
  alpha: boolean;
  frameOrder: boolean;
  complete: boolean;
  failedTrials: number;
}

interface TrialRss {
  node_bytes: number;
  chromium_bytes: number;
}

export type RssSample = TrialRss;

interface CaptureBenchmarkTrial {
  status: 'completed' | 'failed';
  wall_ms: number;
  peak_rss: TrialRss;
  transferred_bytes: number;
  decoded_rgba_hash: string;
  alpha: boolean;
  frame_order: boolean;
  complete: boolean;
  error?: string;
}

interface CaptureBenchmarkCandidate {
  method: CaptureMethod;
  supported: boolean;
  median_wall_ms: number;
  peak_rss: TrialRss;
  transferred_bytes: number;
  decoded_rgba_hash: string;
  integrity: boolean;
  alpha: boolean;
  frame_order: boolean;
  complete: boolean;
  failed_trials: number;
  trials: CaptureBenchmarkTrial[];
}

interface CaptureBenchmarkReport {
  schema_version: 1;
  backend: {
    requested: 'metal' | 'swiftshader';
    actual: 'metal' | 'swiftshader' | 'unknown';
    vendor: string;
    renderer: string;
  };
  input: {width: number; height: number; fps: number; frame_count: number};
  candidates: CaptureBenchmarkCandidate[];
  production_method: CaptureMethod;
}


const execFileAsync = promisify(execFile);
const METHODS = createFrameCaptures().map((capture) => capture.name);


const median = (values: number[]): number => {
  const sorted = [...values].sort((left, right) => left - right);
  if (!sorted.length) return 0;
  return sorted[Math.floor(sorted.length / 2)]!;
};


const atomicWriteJson = async (destination: string, value: unknown): Promise<void> => {
  const temporary = join(dirname(destination), `.${basename(destination)}.tmp`);
  await writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, 'utf8');
  await rename(temporary, destination);
};


const processRss = async (): Promise<TrialRss> => {
  const {stdout} = await execFileAsync('ps', ['-axo', 'pid=,ppid=,rss=']);
  const processes = stdout.trim().split('\n').flatMap((line) => {
    const [pidText, parentText, rssText] = line.trim().split(/\s+/u);
    const pid = Number.parseInt(pidText ?? '', 10);
    const parent = Number.parseInt(parentText ?? '', 10);
    const rss = Number.parseInt(rssText ?? '', 10);
    return Number.isSafeInteger(pid) && Number.isSafeInteger(parent) && Number.isSafeInteger(rss)
      ? [{pid, parent, rss: rss * 1024}]
      : [];
  });
  const descendants = new Set<number>([process.pid]);
  let changed = true;
  while (changed) {
    changed = false;
    for (const item of processes) {
      if (descendants.has(item.parent) && !descendants.has(item.pid)) {
        descendants.add(item.pid);
        changed = true;
      }
    }
  }
  return {
    node_bytes: process.memoryUsage.rss(),
    chromium_bytes: processes
      .filter((item) => item.pid !== process.pid && descendants.has(item.pid))
      .reduce((total, item) => total + item.rss, 0),
  };
};


export const createRssSampler = (
  sampleRss: () => Promise<RssSample>,
  intervalMilliseconds = 25,
): {stop(): Promise<RssSample>} => {
  let peak: TrialRss = {node_bytes: process.memoryUsage.rss(), chromium_bytes: 0};
  let stopped = false;
  const inFlight = new Set<Promise<void>>();
  const sample = (): void => {
    if (stopped) return;
    let operation: Promise<void>;
    operation = Promise.resolve()
      .then(sampleRss)
      .then((current) => {
      peak = {
        node_bytes: Math.max(peak.node_bytes, current.node_bytes),
        chromium_bytes: Math.max(peak.chromium_bytes, current.chromium_bytes),
      };
      })
      .finally(() => inFlight.delete(operation));
    inFlight.add(operation);
  };
  const interval = setInterval(() => {
    sample();
  }, intervalMilliseconds);
  sample();
  return {
    async stop(): Promise<RssSample> {
      stopped = true;
      clearInterval(interval);
      await Promise.allSettled([...inFlight]);
      return peak;
    },
  };
};


const decodedPng = (png: Buffer): {hash: string; alpha: boolean} => {
  const decoded = PNG.sync.read(png);
  return {
    hash: createHash('sha256').update(decoded.data).digest('hex'),
    alpha: decoded.data.some((_component, index) => index % 4 === 3 && decoded.data[index]! < 255),
  };
};


const decodeTrial = async (
  framePaths: string[],
): Promise<{hash: string; alpha: boolean; bytes: number}> => {
  const hash = createHash('sha256');
  let alpha = false;
  let bytes = 0;
  for (const framePath of framePaths) {
    const png = await readFile(framePath);
    const decoded = decodedPng(png);
    hash.update(decoded.hash);
    alpha ||= decoded.alpha;
    bytes += png.byteLength;
  }
  return {hash: hash.digest('hex'), alpha, bytes};
};


const expectedFrameOrder = (paths: string[], frameCount: number): boolean =>
  paths.length === frameCount
  && paths.every((path, index) => basename(path) === `frame-${index.toString().padStart(6, '0')}.png`);


const trial = async (
  source: RenderJob,
  method: CaptureMethod,
  destination: string,
  requestedBackend: 'metal' | 'swiftshader',
): Promise<{trial: CaptureBenchmarkTrial; backend: CaptureBenchmarkReport['backend']}> => {
  const sampler = createRssSampler(processRss);
  const started = performance.now();
  try {
    const report = await renderJob({...source, output_directory: destination}, {captureMethod: method});
    const decoded = await decodeTrial(report.frames);
    return {
      trial: {
        status: 'completed',
        wall_ms: performance.now() - started,
        peak_rss: await sampler.stop(),
        transferred_bytes: report.capture_transport_bytes,
        decoded_rgba_hash: decoded.hash,
        alpha: decoded.alpha,
        frame_order: expectedFrameOrder(report.frames, source.frame_count),
        complete: report.frame_count === source.frame_count,
      },
      backend: report.backend,
    };
  } catch (error) {
    return {
      trial: {
        status: 'failed',
        wall_ms: performance.now() - started,
        peak_rss: await sampler.stop(),
        transferred_bytes: 0,
        decoded_rgba_hash: '',
        alpha: false,
        frame_order: false,
        complete: false,
        error: error instanceof Error ? error.message : String(error),
      },
      backend: {
        requested: requestedBackend,
        actual: 'unknown',
        vendor: '',
        renderer: '',
      },
    };
  }
};


const summarizeCandidate = (
  method: CaptureMethod,
  trials: CaptureBenchmarkTrial[],
  baseline?: CaptureBenchmarkCandidate,
): CaptureBenchmarkCandidate => {
  const completed = trials.filter((item) => item.status === 'completed');
  const allComplete = completed.length === trials.length;
  const hashes = new Set(completed.map((item) => item.decoded_rgba_hash));
  const alphas = new Set(completed.map((item) => item.alpha));
  const baselineHash = baseline?.decoded_rgba_hash;
  const baselineAlpha = baseline?.trials[0]?.alpha;
  return {
    method,
    supported: completed.length > 0,
    median_wall_ms: median(completed.map((item) => item.wall_ms)),
    peak_rss: {
      node_bytes: Math.max(0, ...trials.map((item) => item.peak_rss.node_bytes)),
      chromium_bytes: Math.max(0, ...trials.map((item) => item.peak_rss.chromium_bytes)),
    },
    transferred_bytes: completed.reduce((total, item) => total + item.transferred_bytes, 0),
    decoded_rgba_hash: completed[0]?.decoded_rgba_hash ?? '',
    integrity: allComplete && hashes.size === 1 && (!baselineHash || hashes.has(baselineHash)),
    alpha: allComplete && alphas.size === 1 && (baselineAlpha === undefined || alphas.has(baselineAlpha)),
    frame_order: allComplete && completed.every((item) => item.frame_order),
    complete: allComplete && completed.every((item) => item.complete),
    failed_trials: trials.length - completed.length,
    trials,
  };
};


const benchmarkSource = (job: RenderJob): RenderJob => {
  if (job.output.width !== 1920 || job.output.height !== 1080) {
    throw new Error('capture benchmark requires a 1920x1080 render job');
  }
  const frameCount = Math.min(job.frame_count, Number.parseInt(process.env.CAPTURE_BENCHMARK_FRAMES ?? '8', 10));
  if (!Number.isSafeInteger(frameCount) || frameCount < 1) {
    throw new Error('CAPTURE_BENCHMARK_FRAMES must be a positive integer');
  }
  if ('job_kind' in job && job.job_kind === 'sequence') {
    return {
      ...job,
      frame_count: frameCount,
      sample_frames: job.sample_frames.filter((frame) => frame < frameCount),
    };
  }
  return {...job, frame_count: frameCount};
};


const selectionSummary = (candidate: CaptureBenchmarkCandidate): CaptureBenchmarkSummary => ({
  method: candidate.method,
  medianWallMilliseconds: candidate.median_wall_ms,
  peakRssBytes: candidate.peak_rss.node_bytes + candidate.peak_rss.chromium_bytes,
  integrity: candidate.integrity,
  alpha: candidate.alpha,
  frameOrder: candidate.frame_order,
  complete: candidate.complete,
  failedTrials: candidate.failed_trials,
});


export const runCaptureBenchmark = async (job: RenderJob): Promise<CaptureBenchmarkReport> => {
  const source = benchmarkSource(job);
  const requestedBackend = source.renderer_backend ?? PRODUCTION_RENDERER_BACKEND;
  const root = await mkdtemp(join(tmpdir(), 'video-generator-capture-benchmark-'));
  let attestedBackend: CaptureBenchmarkReport['backend'] | undefined;
  const candidates: CaptureBenchmarkCandidate[] = [];
  try {
    for (const method of METHODS) {
      const warmup = await trial(source, method, join(root, method, 'warmup'), requestedBackend);
      if (!attestedBackend && warmup.trial.status === 'completed') attestedBackend = warmup.backend;
      const measured: CaptureBenchmarkTrial[] = [];
      if (warmup.trial.status === 'completed' && warmup.backend.actual === attestedBackend?.actual) {
        for (let index = 0; index < 3; index += 1) {
          const measuredTrial = await trial(
            source,
            method,
            join(root, method, `trial-${index + 1}`),
            requestedBackend,
          );
          if (
            measuredTrial.trial.status === 'completed'
            && measuredTrial.backend.actual !== attestedBackend?.actual
          ) {
            measuredTrial.trial.status = 'failed';
            measuredTrial.trial.error = `backend changed from ${attestedBackend?.actual} to ${measuredTrial.backend.actual}`;
          }
          measured.push(measuredTrial.trial);
        }
      } else {
        measured.push(...Array.from({length: 3}, () => ({
          status: 'failed' as const,
          wall_ms: 0,
          peak_rss: {node_bytes: 0, chromium_bytes: 0},
          transferred_bytes: 0,
          decoded_rgba_hash: '',
          alpha: false,
          frame_order: false,
          complete: false,
          error: warmup.trial.error ?? 'warm-up did not complete on the attested backend',
        })));
      }
      candidates.push(summarizeCandidate(method, measured, candidates[0]));
    }
    if (!attestedBackend) {
      throw new Error(`locator capture did not produce an attested backend: ${candidates[0]?.trials[0]?.error ?? 'unknown error'}`);
    }
    return {
      schema_version: 1,
      backend: attestedBackend,
      input: {
        width: source.output.width,
        height: source.output.height,
        fps: source.output.fps,
        frame_count: source.frame_count,
      },
      candidates,
      production_method: selectProductionCaptureMethod(candidates.map(selectionSummary)),
    };
  } finally {
    await rm(root, {recursive: true, force: true});
  }
};


export const validateCaptureBenchmarkReport = (value: unknown): CaptureMethod => {
  if (!value || typeof value !== 'object') throw new Error('benchmark report must be an object');
  const report = value as Partial<CaptureBenchmarkReport>;
  if (report.schema_version !== 1 || !Array.isArray(report.candidates)) {
    throw new Error('benchmark report has an invalid schema');
  }
  const names = report.candidates.map((candidate) => candidate.method);
  if (names.length !== METHODS.length || METHODS.some((method) => !names.includes(method))) {
    throw new Error('benchmark report must include every capture method');
  }
  const selected = selectProductionCaptureMethod((report.candidates as CaptureBenchmarkCandidate[]).map(selectionSummary));
  if (report.production_method !== selected) {
    throw new Error(`production method must be ${selected} under the deterministic benchmark rule`);
  }
  return selected;
};


const main = async (): Promise<void> => {
  const [command, first, second] = process.argv.slice(2);
  if (command === '--validate' && first && !second) {
    const selected = validateCaptureBenchmarkReport(JSON.parse(await readFile(first, 'utf8')));
    process.stdout.write(`${selected}\n`);
    return;
  }
  if (!command || !first || second) {
    throw new Error('usage: npm run benchmark-capture -- <render-job.json> <report.json>');
  }
  const job = JSON.parse(await readFile(command, 'utf8')) as RenderJob;
  const report = await runCaptureBenchmark(job);
  await atomicWriteJson(first, report);
  process.stdout.write(`${report.production_method}\n`);
};


if (process.argv[1]?.endsWith('capture-benchmark.ts')) {
  void main().catch((error: unknown) => {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  });
}


const isStable = (summary: CaptureBenchmarkSummary, locatorPeakRss: number): boolean =>
  summary.integrity
  && summary.alpha
  && summary.frameOrder
  && summary.complete
  && summary.failedTrials === 0
  && summary.peakRssBytes <= locatorPeakRss * 1.25;


/** Select once from the checked-in benchmark record; never adapt production at runtime. */
export const selectProductionCaptureMethod = (summaries: CaptureBenchmarkSummary[]): CaptureMethod => {
  const locator = summaries.find((summary) => summary.method === 'locator-png');
  if (!locator || !isStable(locator, locator.peakRssBytes)) return 'locator-png';
  const winner = summaries
    .filter((summary) => isStable(summary, locator.peakRssBytes))
    .sort((left, right) => (
      left.medianWallMilliseconds - right.medianWallMilliseconds
      || left.method.localeCompare(right.method)
    ))[0];
  if (!winner || winner.medianWallMilliseconds > locator.medianWallMilliseconds * 0.8) {
    return 'locator-png';
  }
  return winner.method;
};
