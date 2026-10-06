import {createHash} from 'node:crypto';
import {mkdtemp, readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

import {chromium, type Browser, type Page} from 'playwright';
import {afterAll, beforeAll, describe, expect, it} from 'vitest';

import {
  createFrameCaptures,
  LoopbackBlobPngCapture,
  PRODUCTION_CAPTURE_METHOD,
  type CaptureSuccess,
} from '../src/frame-capture.js';
import {
  createRssSampler,
  selectProductionCaptureMethod,
} from '../src/capture-benchmark.js';


let browser: Browser;


const sha256 = (bytes: Uint8Array): string =>
  createHash('sha256').update(bytes).digest('hex');


const decodeRgba = async (page: Page, png: Buffer): Promise<number[]> =>
  page.evaluate(async (base64) => {
    const image = new Image();
    image.src = `data:image/png;base64,${base64}`;
    await image.decode();
    const canvas = document.createElement('canvas');
    canvas.width = image.width;
    canvas.height = image.height;
    const context = canvas.getContext('2d', {willReadFrequently: true});
    if (!context) throw new Error('2D canvas unavailable');
    context.drawImage(image, 0, 0);
    return [...context.getImageData(0, 0, canvas.width, canvas.height).data];
  }, png.toString('base64'));


beforeAll(async () => {
  browser = await chromium.launch();
});


afterAll(async () => {
  await browser.close();
});


describe('lossless frame capture transports', () => {
  it('uses canvas.toDataURL directly for data-url capture instead of the Blob path', async () => {
    const page = await browser.newPage({viewport: {width: 64, height: 64}, deviceScaleFactor: 1});
    const destinationRoot = await mkdtemp(join(tmpdir(), 'frame-capture-direct-data-url-'));
    await page.setContent('<canvas id="science-canvas" width="64" height="64"></canvas>');
    await page.evaluate(() => {
      const canvas = document.querySelector<HTMLCanvasElement>('#science-canvas')!;
      canvas.getContext('2d')!.fillRect(0, 0, 64, 64);
      canvas.toBlob = () => { throw new Error('Blob encoding deliberately disabled'); };
    });
    const captures = createFrameCaptures();
    const dataUrl = captures.find((capture) => capture.name === 'data-url-png')!;
    const blobBase64 = captures.find((capture) => capture.name === 'blob-base64-png')!;

    await expect(dataUrl.capture(page, page.locator('#science-canvas'), join(destinationRoot, 'frame-000000.png')))
      .resolves.toMatchObject({
        status: 'supported',
        transportType: 'data-url',
        captureTimingMode: 'split',
      });
    await expect(blobBase64.capture(page, page.locator('#science-canvas'), join(destinationRoot, 'frame-000001.png')))
      .rejects.toThrow('Blob encoding deliberately disabled');
    await page.close();
  });

  it('keeps the locator baseline composited over the page backdrop', async () => {
    const page = await browser.newPage({viewport: {width: 64, height: 64}, deviceScaleFactor: 1});
    const destinationRoot = await mkdtemp(join(tmpdir(), 'frame-capture-backdrop-'));
    await page.setContent(`
      <style>html,body{margin:0;background:#020611}canvas{display:block}</style>
      <canvas id="science-canvas" width="64" height="64"></canvas>
    `);

    const locator = createFrameCaptures().find((capture) => capture.name === 'locator-png')!;
    const result = await locator.capture(page, page.locator('#science-canvas'), join(destinationRoot, 'frame-000000.png'));

    expect(result.status).toBe('supported');
    if (result.status === 'supported') {
      const pixels = await decodeRgba(page, await readFile(result.destination));
      expect(pixels.slice(0, 4)).toEqual([2, 6, 17, 255]);
    }
    await page.close();
  });

  it('preserves the locator PNG pixels, alpha, and capture order for every candidate', async () => {
    const page = await browser.newPage({viewport: {width: 64, height: 64}, deviceScaleFactor: 1});
    const destinationRoot = await mkdtemp(join(tmpdir(), 'frame-capture-'));
    await page.setContent(`
      <style>html,body{margin:0;background:#020611}canvas{display:block}</style>
      <canvas id="science-canvas" width="64" height="64"></canvas>
      <script>
        const context = document.querySelector('canvas').getContext('2d');
        context.fillStyle = '#020611'; context.fillRect(0, 0, 64, 64);
        context.fillStyle = '#ff0000'; context.fillRect(0, 0, 16, 16);
        context.fillStyle = 'rgba(0, 255, 0, 0.5)'; context.fillRect(16, 0, 16, 16);
        context.fillStyle = 'rgba(0, 0, 255, 0.25)'; context.fillRect(0, 16, 16, 16);
      </script>
    `);
    const canvas = page.locator('#science-canvas');
    const captures = createFrameCaptures();
    const results: CaptureSuccess[] = [];

    for (const [index, capture] of captures.entries()) {
      const result = await capture.capture(
        page,
        canvas,
        join(destinationRoot, `frame-${index.toString().padStart(6, '0')}.png`),
      );
      if (result.status === 'unsupported') {
        expect(result.name).toBe('blob-array-buffer-png');
        expect(result.reason).toMatch(/binary/u);
      } else {
        results.push(result);
      }
    }

    const baseline = results.find((result) => result.name === 'locator-png');
    expect(baseline).toBeDefined();
    const baselinePixels = await decodeRgba(page, await readFile(baseline!.destination));
    expect(baselinePixels.slice(16 * 4, 17 * 4)).toEqual([1, 131, 8, 255]);

    for (const result of results) {
      expect(await decodeRgba(page, await readFile(result.destination))).toEqual(baselinePixels);
      expect(result.frameIndex).toBe(captures.findIndex((capture) => capture.name === result.name));
      if (result.transportType === 'screenshot') {
        expect(result.transportByteLength).toBe(Buffer.byteLength(result.bytes.toString('base64'), 'ascii'));
        expect(result.captureTimingMode).toBe('playwright_combined');
        expect(result.canvasEncodeCaptureMilliseconds).toBe(0);
        expect(result.browserToNodeTransferMilliseconds).toBeGreaterThan(0);
      } else if (result.transportType === 'binary' || result.transportType === 'loopback') {
        expect(result.transportByteLength).toBe(result.byteLength);
      } else {
        expect(result.transportByteLength).toBe(
          Buffer.byteLength(`data:image/png;base64,${result.bytes.toString('base64')}`, 'utf8'),
        );
      }
      if (result.transportType !== 'screenshot') {
        expect(result.captureTimingMode).toBe('split');
        expect(result.canvasEncodeCaptureMilliseconds).toBeGreaterThanOrEqual(0);
        expect(result.browserToNodeTransferMilliseconds).toBeGreaterThanOrEqual(0);
      }
    }
    expect(results.find((result) => result.name === 'loopback-blob-png')!.writeMilliseconds)
      .toBeGreaterThan(0);
    await page.close();
  });

  it('accepts ArrayBuffer capture only as byte-exact binary transport', async () => {
    const page = await browser.newPage({viewport: {width: 64, height: 64}, deviceScaleFactor: 1});
    const destinationRoot = await mkdtemp(join(tmpdir(), 'frame-capture-array-buffer-'));
    await page.setContent('<canvas id="science-canvas" width="64" height="64"></canvas>');
    await page.evaluate(() => {
      const context = document.querySelector('canvas')!.getContext('2d')!;
      context.fillStyle = 'rgba(12, 34, 56, 0.5)';
      context.fillRect(0, 0, 64, 64);
    });
    const expected = Buffer.from(await page.evaluate(async () => {
      const canvas = document.querySelector('canvas')!;
      const blob = await new Promise<Blob>((resolve, reject) => canvas.toBlob((value) => {
        if (value) resolve(value); else reject(new Error('canvas encoding failed'));
      }, 'image/png'));
      return [...new Uint8Array(await blob.arrayBuffer())];
    }));
    const capture = createFrameCaptures().find((candidate) => candidate.name === 'blob-array-buffer-png')!;
    const result = await capture.capture(page, page.locator('#science-canvas'), join(destinationRoot, 'frame-000000.png'));

    if (result.status === 'unsupported') {
      expect(result.reason).toMatch(/binary/u);
    } else {
      expect(result.transportType).toBe('binary');
      expect(result.byteLength).toBe(expected.byteLength);
      expect(sha256(result.bytes)).toBe(sha256(expected));
    }
    await page.close();
  });

  it('selects only a stable, byte-correct method that is at least 20 percent faster than locator', () => {
    const selected = selectProductionCaptureMethod([
      {
        method: 'locator-png', medianWallMilliseconds: 100, peakRssBytes: 100,
        integrity: true, alpha: true, frameOrder: true, complete: true, failedTrials: 0,
      },
      {
        method: 'data-url-png', medianWallMilliseconds: 70, peakRssBytes: 110,
        integrity: true, alpha: true, frameOrder: true, complete: true, failedTrials: 0,
      },
      {
        method: 'blob-array-buffer-png', medianWallMilliseconds: 50, peakRssBytes: 105,
        integrity: false, alpha: true, frameOrder: true, complete: true, failedTrials: 0,
      },
      {
        method: 'blob-base64-png', medianWallMilliseconds: 79, peakRssBytes: 126,
        integrity: true, alpha: true, frameOrder: true, complete: true, failedTrials: 0,
      },
      {
        method: 'loopback-blob-png', medianWallMilliseconds: 60, peakRssBytes: 95,
        integrity: true, alpha: true, frameOrder: false, complete: true, failedTrials: 0,
      },
    ]);

    expect(selected).toBe('data-url-png');
  });

  it('keeps locator when no valid capture clears the 20 percent improvement gate', () => {
    const selected = selectProductionCaptureMethod([
      {
        method: 'locator-png', medianWallMilliseconds: 100, peakRssBytes: 100,
        integrity: true, alpha: true, frameOrder: true, complete: true, failedTrials: 0,
      },
      {
        method: 'data-url-png', medianWallMilliseconds: 81, peakRssBytes: 100,
        integrity: true, alpha: true, frameOrder: true, complete: true, failedTrials: 0,
      },
    ]);

    expect(selected).toBe('locator-png');
  });

  it('uses the method selected by the checked 1080p benchmark in production', () => {
    expect(PRODUCTION_CAPTURE_METHOD).toBe('data-url-png');
  });

  it('preserves true non-opaque alpha through every canvas transport', async () => {
    const page = await browser.newPage({viewport: {width: 64, height: 64}, deviceScaleFactor: 1});
    const destinationRoot = await mkdtemp(join(tmpdir(), 'frame-capture-alpha-'));
    await page.setContent('<canvas id="science-canvas" width="64" height="64"></canvas>');
    await page.evaluate(() => {
      const context = document.querySelector<HTMLCanvasElement>('#science-canvas')!.getContext('2d')!;
      context.clearRect(0, 0, 64, 64);
      context.fillStyle = 'rgba(255, 0, 0, 0.25)';
      context.fillRect(0, 0, 64, 64);
    });
    const names = ['data-url-png', 'blob-base64-png', 'loopback-blob-png'] as const;
    for (const [index, name] of names.entries()) {
      const capture = createFrameCaptures().find((candidate) => candidate.name === name)!;
      const result = await capture.capture(
        page,
        page.locator('#science-canvas'),
        join(destinationRoot, `frame-${index.toString().padStart(6, '0')}.png`),
      );
      expect(result.status).toBe('supported');
      if (result.status === 'supported') {
        const pixels = await decodeRgba(page, await readFile(result.destination));
        expect(pixels[3]).toBeLessThan(255);
      }
    }
    await page.close();
  });

  it('reserves loopback frame indices before asynchronous body delivery', async () => {
    const page = await browser.newPage({viewport: {width: 64, height: 64}, deviceScaleFactor: 1});
    const destinationRoot = await mkdtemp(join(tmpdir(), 'frame-capture-loopback-order-'));
    await page.setContent('<canvas id="science-canvas" width="64" height="64"></canvas>');
    await page.evaluate(() => {
      const context = document.querySelector<HTMLCanvasElement>('#science-canvas')!.getContext('2d')!;
      context.fillStyle = 'rgba(0, 0, 255, 0.5)';
      context.fillRect(0, 0, 64, 64);
    });
    const capture = createFrameCaptures().find((candidate) => candidate.name === 'loopback-blob-png')!;
    const canvas = page.locator('#science-canvas');

    const first = capture.capture(page, canvas, join(destinationRoot, 'frame-000000.png'));
    const duplicate = capture.capture(page, canvas, join(destinationRoot, 'frame-000000.png'));
    await expect(duplicate).rejects.toThrow('must increase');
    const firstResult = await first;
    expect(firstResult.status).toBe('supported');
    const second = await capture.capture(page, canvas, join(destinationRoot, 'frame-000001.png'));
    expect(second).toMatchObject({status: 'supported', frameIndex: 1});
    if (firstResult.status === 'supported' && second.status === 'supported') {
      expect((await decodeRgba(page, await readFile(firstResult.destination)))[3]).toBeLessThan(255);
      expect((await decodeRgba(page, await readFile(second.destination)))[3]).toBeLessThan(255);
    }
    await expect(capture.capture(page, canvas, join(destinationRoot, 'frame-000000.png')))
      .rejects.toThrow('must increase');
    await page.close();
  });

  it('settles a rejected loopback acknowledgement and releases its server', async () => {
    const page = await browser.newPage({viewport: {width: 64, height: 64}, deviceScaleFactor: 1});
    const destinationRoot = await mkdtemp(join(tmpdir(), 'frame-capture-loopback-reject-'));
    await page.setContent('<canvas id="science-canvas" width="64" height="64"></canvas>');
    const capture = new LoopbackBlobPngCapture(async (requestUrl) => {
      const rejected = new URL(requestUrl);
      rejected.searchParams.set('token', 'not-the-run-token');
      await fetch(rejected, {method: 'POST', body: Buffer.from('not-a-png')});
    });

    await expect(capture.capture(page, page.locator('#science-canvas'), join(destinationRoot, 'frame-000000.png')))
      .rejects.toThrow();
    await expect(new LoopbackBlobPngCapture().capture(
      page,
      page.locator('#science-canvas'),
      join(destinationRoot, 'frame-000001.png'),
    ))
      .resolves.toMatchObject({status: 'supported', frameIndex: 1});
    await page.close();
  });

  it('waits for an in-flight RSS sample during sampler shutdown', async () => {
    let release: (() => void) | undefined;
    const blocked = new Promise<void>((resolve) => { release = resolve; });
    const sampler = createRssSampler(async () => {
      await blocked;
      return {node_bytes: 11, chromium_bytes: 22};
    }, 60_000);
    const stopping = sampler.stop();
    let settled = false;
    void stopping.then(() => { settled = true; });
    await Promise.resolve();
    expect(settled).toBe(false);
    release!();
    await expect(stopping).resolves.toMatchObject({chromium_bytes: 22});
  });
});
