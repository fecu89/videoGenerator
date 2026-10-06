import {mkdir, readFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

import {chromium} from 'playwright';
import {productionChromiumLaunchOptions} from './browser-launch.js';

export type Point = [number, number];
export type OverlayType = 'line' | 'circle' | 'polyline' | 'screen_anchor';

export interface OverlayKeyframe {
  at_seconds: number;
  points: Point[];
}

export interface OverlayContract {
  overlay_id: string;
  type: OverlayType;
  relationship_id: string;
  style: Record<string, string | number>;
  keyframes: OverlayKeyframe[];
}

export interface OverlayState {
  lines: Array<{from: Point; to: Point; style: Record<string, string | number>}>;
  circles: Array<{center: Point; style: Record<string, string | number>}>;
  polylines: Array<{points: Point[]; style: Record<string, string | number>}>;
  anchors: Array<{position: Point; style: Record<string, string | number>}>;
}

export interface OverlayRenderJob {
  width: number;
  height: number;
  frame_count: number;
  duration_seconds: number;
  output_directory: string;
  overlays: OverlayContract[];
}


const interpolatePoints = (
  contract: OverlayContract,
  atSeconds: number,
): Point[] => {
  const keyframes = [...contract.keyframes].sort(
    (left, right) => left.at_seconds - right.at_seconds,
  );
  const first = keyframes[0];
  if (!first) throw new Error(`${contract.overlay_id} has no keyframes`);
  if (atSeconds <= first.at_seconds || keyframes.length === 1) return first.points;
  const last = keyframes[keyframes.length - 1]!;
  if (atSeconds >= last.at_seconds) return last.points;

  const endIndex = keyframes.findIndex((item) => item.at_seconds >= atSeconds);
  const before = keyframes[endIndex - 1]!;
  const after = keyframes[endIndex]!;
  if (before.points.length !== after.points.length) {
    throw new Error(`${contract.overlay_id} keyframe point count differs`);
  }
  const span = after.at_seconds - before.at_seconds;
  const progress = span === 0 ? 1 : (atSeconds - before.at_seconds) / span;
  return before.points.map((point, index) => {
    const target = after.points[index]!;
    return [
      point[0] + (target[0] - point[0]) * progress,
      point[1] + (target[1] - point[1]) * progress,
    ];
  });
};


export const interpolateOverlayState = (
  contracts: OverlayContract[],
  atSeconds: number,
): OverlayState => {
  const state: OverlayState = {lines: [], circles: [], polylines: [], anchors: []};
  for (const contract of contracts) {
    const points = interpolatePoints(contract, atSeconds);
    if (contract.type === 'line') {
      if (points.length !== 2) throw new Error(`${contract.overlay_id} line needs two points`);
      state.lines.push({from: points[0]!, to: points[1]!, style: contract.style});
    } else if (contract.type === 'circle') {
      if (points.length !== 1) throw new Error(`${contract.overlay_id} circle needs one point`);
      state.circles.push({center: points[0]!, style: contract.style});
    } else if (contract.type === 'polyline') {
      if (points.length < 2) throw new Error(`${contract.overlay_id} polyline needs two points`);
      state.polylines.push({points, style: contract.style});
    } else {
      if (points.length !== 1) throw new Error(`${contract.overlay_id} anchor needs one point`);
      state.anchors.push({position: points[0]!, style: contract.style});
    }
  }
  return state;
};


export const renderOverlayJob = async (job: OverlayRenderJob): Promise<string[]> => {
  if (job.width < 1 || job.height < 1 || job.frame_count < 1) {
    throw new Error('overlay job dimensions and frame count must be positive');
  }
  await mkdir(resolve(job.output_directory), {recursive: true});
  const browser = await chromium.launch(productionChromiumLaunchOptions());
  const page = await browser.newPage({
    viewport: {width: job.width, height: job.height},
    deviceScaleFactor: 1,
  });
  await page.setContent(
    `<style>html,body{margin:0;background:transparent;overflow:hidden}</style>` +
      `<canvas id="overlay" width="${job.width}" height="${job.height}"></canvas>`,
  );
  const canvas = page.locator('#overlay');
  const paths: string[] = [];
  try {
    for (let frameIndex = 0; frameIndex < job.frame_count; frameIndex += 1) {
      const denominator = Math.max(1, job.frame_count - 1);
      const atSeconds = job.duration_seconds * frameIndex / denominator;
      const state = interpolateOverlayState(job.overlays, atSeconds);
      await page.evaluate(
        ({frameState, width, height}) => {
          const element = document.querySelector<HTMLCanvasElement>('#overlay');
          if (!element) throw new Error('overlay canvas is missing');
          const context = element.getContext('2d');
          if (!context) throw new Error('2d context is missing');
          context.clearRect(0, 0, width, height);
          for (const line of frameState.lines) {
            context.strokeStyle = String(line.style.stroke ?? '#ffffff');
            context.fillStyle = String(line.style.fill ?? line.style.stroke ?? '#ffffff');
            context.lineWidth = Number(line.style.width ?? 2);
            context.lineCap = 'round';
            context.lineJoin = 'round';
            context.beginPath();
            context.moveTo(line.from[0] * width, line.from[1] * height);
            context.lineTo(line.to[0] * width, line.to[1] * height);
            context.stroke();
          }
          for (const polyline of frameState.polylines) {
            context.strokeStyle = String(polyline.style.stroke ?? '#ffffff');
            context.fillStyle = String(polyline.style.fill ?? polyline.style.stroke ?? '#ffffff');
            context.lineWidth = Number(polyline.style.width ?? 2);
            context.lineCap = 'round';
            context.lineJoin = 'round';
            context.beginPath();
            for (let index = 0; index < polyline.points.length; index += 1) {
              const point = polyline.points[index]!;
              if (index === 0) context.moveTo(point[0] * width, point[1] * height);
              else context.lineTo(point[0] * width, point[1] * height);
            }
            context.stroke();
          }
          for (const circle of frameState.circles) {
            context.strokeStyle = String(circle.style.stroke ?? '#ffffff');
            context.fillStyle = String(circle.style.fill ?? circle.style.stroke ?? '#ffffff');
            context.lineWidth = Number(circle.style.width ?? 2);
            context.lineCap = 'round';
            context.lineJoin = 'round';
            const radius = Number(circle.style.radius ?? 0.015) * Math.min(width, height);
            context.beginPath();
            context.arc(circle.center[0] * width, circle.center[1] * height, radius, 0, Math.PI * 2);
            context.stroke();
          }
          for (const anchor of frameState.anchors) {
            context.strokeStyle = String(anchor.style.stroke ?? '#ffffff');
            context.fillStyle = String(anchor.style.fill ?? anchor.style.stroke ?? '#ffffff');
            context.lineWidth = Number(anchor.style.width ?? 2);
            const radius = Number(anchor.style.radius ?? 0.01) * Math.min(width, height);
            context.beginPath();
            context.arc(anchor.position[0] * width, anchor.position[1] * height, radius, 0, Math.PI * 2);
            context.fill();
          }
        },
        {frameState: state, width: job.width, height: job.height},
      );
      const path = resolve(
        job.output_directory,
        `overlay-${String(frameIndex).padStart(6, '0')}.png`,
      );
      await canvas.screenshot({path, omitBackground: true});
      paths.push(path);
    }
  } finally {
    await browser.close();
  }
  return paths;
};


const currentFile = fileURLToPath(import.meta.url);
const invokedFile = process.argv[1] ? resolve(process.argv[1]) : undefined;
if (invokedFile === currentFile) {
  const jobPath = process.argv[2];
  if (!jobPath) {
    console.error('usage: npm run render-overlay -- <overlay-job.json>');
    process.exitCode = 2;
  } else {
    try {
      const job = JSON.parse(await readFile(resolve(jobPath), 'utf8')) as OverlayRenderJob;
      const frames = await renderOverlayJob(job);
      process.stdout.write(`${JSON.stringify({frame_count: frames.length, frames})}\n`);
    } catch (error) {
      console.error(error instanceof Error ? error.message : String(error));
      process.exitCode = 1;
    }
  }
}
