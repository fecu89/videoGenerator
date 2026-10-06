import {randomUUID, timingSafeEqual} from 'node:crypto';
import {createServer} from 'node:http';
import {rename, unlink, writeFile} from 'node:fs/promises';
import {basename, dirname} from 'node:path';

import type {Locator, Page} from 'playwright';


export type CaptureMethod =
  | 'locator-png'
  | 'data-url-png'
  | 'blob-array-buffer-png'
  | 'blob-base64-png'
  | 'loopback-blob-png';

export type CaptureTransportType = 'screenshot' | 'data-url' | 'binary' | 'base64' | 'loopback';
export type CaptureTimingMode = 'split' | 'playwright_combined';

export interface CaptureSuccess {
  readonly status: 'supported';
  readonly name: CaptureMethod;
  readonly transportType: CaptureTransportType;
  readonly destination: string;
  readonly frameIndex: number;
  readonly bytes: Buffer;
  readonly byteLength: number;
  /** Bytes carried by the transport payload, not the final file size. */
  readonly transportByteLength: number;
  /** Whether capture/encode and transfer are independently observable. */
  readonly captureTimingMode: CaptureTimingMode;
  readonly canvasEncodeCaptureMilliseconds: number;
  readonly browserToNodeTransferMilliseconds: number;
  readonly writeMilliseconds: number;
}

export interface CaptureUnsupported {
  readonly status: 'unsupported';
  readonly name: CaptureMethod;
  readonly destination: string;
  readonly frameIndex: number;
  readonly reason: string;
}

export type CaptureMetrics = CaptureSuccess | CaptureUnsupported;

export interface FrameCapture {
  readonly name: CaptureMethod;
  capture(page: Page, canvas: Locator, destination: string): Promise<CaptureMetrics>;
}


const frameIndexFromDestination = (destination: string): number => {
  const match = /frame-(\d+)\.png$/u.exec(basename(destination));
  if (!match?.[1]) throw new Error(`capture destination must end in frame-NNNNNN.png: ${destination}`);
  return Number.parseInt(match[1], 10);
};


const stagingPath = (destination: string): string =>
  `${dirname(destination)}/.${basename(destination)}.${randomUUID()}.tmp`;


const writePngAtomically = async (destination: string, bytes: Buffer): Promise<void> => {
  const temporary = stagingPath(destination);
  try {
    await writeFile(temporary, bytes);
    await rename(temporary, destination);
  } catch (error) {
    await unlink(temporary).catch(() => undefined);
    throw error;
  }
};


interface TimedBrowserValue<T> {
  value: T;
  canvasEncodeCaptureMilliseconds: number;
}


const blobAsDataUrl = async (page: Page, canvas: Locator): Promise<TimedBrowserValue<string>> =>
  canvas.evaluate(async (element) => {
    const started = performance.now();
    const target = element as HTMLCanvasElement;
    const blob = await new Promise<Blob>((resolve, reject) => {
      target.toBlob((value: Blob | null) => {
        if (value) resolve(value);
        else reject(new Error('canvas PNG encoding failed'));
      }, 'image/png');
    });
    const value = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.addEventListener('error', () => reject(reader.error));
      reader.addEventListener('load', () => resolve(String(reader.result)));
      reader.readAsDataURL(blob);
    });
    return {
      value,
      canvasEncodeCaptureMilliseconds: performance.now() - started,
    };
  });


const canvasDataUrl = async (canvas: Locator): Promise<TimedBrowserValue<string>> =>
  canvas.evaluate((element) => {
    const started = performance.now();
    const value = (element as HTMLCanvasElement).toDataURL('image/png');
    return {
      value,
      canvasEncodeCaptureMilliseconds: performance.now() - started,
    };
  });


const binaryFromEvaluation = (value: unknown): Buffer | undefined => {
  if (value instanceof ArrayBuffer) return Buffer.from(value);
  if (ArrayBuffer.isView(value)) {
    return Buffer.from(value.buffer, value.byteOffset, value.byteLength);
  }
  return undefined;
};


const complete = async (
  name: CaptureMethod,
  transportType: CaptureTransportType,
  destination: string,
  bytes: Buffer,
  transportByteLength: number,
  captureTimingMode: CaptureTimingMode,
  canvasEncodeCaptureMilliseconds: number,
  browserToNodeTransferMilliseconds: number,
): Promise<CaptureSuccess> => {
  const writeStarted = performance.now();
  await writePngAtomically(destination, bytes);
  return {
    status: 'supported',
    name,
    transportType,
    destination,
    frameIndex: frameIndexFromDestination(destination),
    bytes,
    byteLength: bytes.byteLength,
    transportByteLength,
    captureTimingMode,
    canvasEncodeCaptureMilliseconds,
    browserToNodeTransferMilliseconds,
    writeMilliseconds: performance.now() - writeStarted,
  };
};


const unsupported = (name: CaptureMethod, destination: string, reason: string): CaptureUnsupported => ({
  status: 'unsupported',
  name,
  destination,
  frameIndex: frameIndexFromDestination(destination),
  reason,
});


const localhostTokenMatches = (provided: string | null, expected: string): boolean => {
  if (provided === null) return false;
  const actualBytes = Buffer.from(provided);
  const expectedBytes = Buffer.from(expected);
  return actualBytes.byteLength === expectedBytes.byteLength && timingSafeEqual(actualBytes, expectedBytes);
};


class LocatorPngCapture implements FrameCapture {
  readonly name = 'locator-png' as const;

  async capture(_page: Page, canvas: Locator, destination: string): Promise<CaptureMetrics> {
    const captureStarted = performance.now();
    const bytes = await canvas.screenshot({type: 'png'});
    const combinedMilliseconds = performance.now() - captureStarted;
    return complete(
      this.name,
      'screenshot',
      destination,
      bytes,
      Buffer.byteLength(bytes.toString('base64'), 'ascii'),
      'playwright_combined',
      0,
      combinedMilliseconds,
    );
  }
}


class DataUrlPngCapture implements FrameCapture {
  readonly name = 'data-url-png' as const;

  async capture(page: Page, canvas: Locator, destination: string): Promise<CaptureMetrics> {
    const captureStarted = performance.now();
    const captured = await canvasDataUrl(canvas);
    const dataUrl = captured.value;
    const prefix = 'data:image/png;base64,';
    if (!dataUrl.startsWith(prefix)) throw new Error('canvas did not encode a PNG data URL');
    const bytes = Buffer.from(dataUrl.slice(prefix.length), 'base64');
    return complete(
      this.name,
      'data-url',
      destination,
      bytes,
      Buffer.byteLength(dataUrl, 'utf8'),
      'split',
      captured.canvasEncodeCaptureMilliseconds,
      Math.max(
        0,
        performance.now()
          - captureStarted
          - captured.canvasEncodeCaptureMilliseconds,
      ),
    );
  }
}


class BlobArrayBufferPngCapture implements FrameCapture {
  readonly name = 'blob-array-buffer-png' as const;

  async capture(_page: Page, canvas: Locator, destination: string): Promise<CaptureMetrics> {
    const captureStarted = performance.now();
    const evaluated = await canvas.evaluate(async (element) => {
      const started = performance.now();
      const target = element as HTMLCanvasElement;
      const blob = await new Promise<Blob>((resolve, reject) => {
        target.toBlob((value: Blob | null) => {
          if (value) resolve(value);
          else reject(new Error('canvas PNG encoding failed'));
        }, 'image/png');
      });
      return {
        value: await blob.arrayBuffer(),
        canvasEncodeCaptureMilliseconds: performance.now() - started,
      };
    });
    const bytes = binaryFromEvaluation(evaluated.value);
    if (!bytes) {
      return unsupported(
        this.name,
        destination,
        'Playwright did not return ArrayBuffer data as a binary value',
      );
    }
    return complete(
      this.name,
      'binary',
      destination,
      bytes,
      bytes.byteLength,
      'split',
      evaluated.canvasEncodeCaptureMilliseconds,
      Math.max(
        0,
        performance.now() - captureStarted - evaluated.canvasEncodeCaptureMilliseconds,
      ),
    );
  }
}


class BlobBase64PngCapture implements FrameCapture {
  readonly name = 'blob-base64-png' as const;

  async capture(page: Page, canvas: Locator, destination: string): Promise<CaptureMetrics> {
    const captureStarted = performance.now();
    const captured = await blobAsDataUrl(page, canvas);
    const dataUrl = captured.value;
    const prefix = 'data:image/png;base64,';
    if (!dataUrl.startsWith(prefix)) throw new Error('canvas did not encode a PNG data URL');
    const bytes = Buffer.from(dataUrl.slice(prefix.length), 'base64');
    return complete(
      this.name,
      'base64',
      destination,
      bytes,
      Buffer.byteLength(dataUrl, 'utf8'),
      'split',
      captured.canvasEncodeCaptureMilliseconds,
      Math.max(
        0,
        performance.now()
          - captureStarted
          - captured.canvasEncodeCaptureMilliseconds,
      ),
    );
  }
}


/** A loopback transport with an optional lifecycle observer for diagnostics. */
export class LoopbackBlobPngCapture implements FrameCapture {
  readonly name = 'loopback-blob-png' as const;
  #lastFrameIndex = -1;
  #lastReservedFrameIndex = -1;

  constructor(private readonly onListening?: (requestUrl: string) => Promise<void>) {}

  async capture(_page: Page, canvas: Locator, destination: string): Promise<CaptureMetrics> {
    const captureStarted = performance.now();
    const frameIndex = frameIndexFromDestination(destination);
    if (frameIndex <= this.#lastReservedFrameIndex) {
      throw new Error(`loopback frame index must increase: ${frameIndex} <= ${this.#lastReservedFrameIndex}`);
    }
    this.#lastReservedFrameIndex = frameIndex;
    const box = await canvas.boundingBox();
    if (!box) throw new Error('canvas is not visible for loopback capture');
    const maximumBytes = Math.ceil(box.width * box.height * 5) + 1_048_576;
    const token = randomUUID();
    const temporary = stagingPath(destination);
    const server = createServer();
    let received: Buffer | undefined;
    let writeMilliseconds = 0;
    let requestAccepted = false;

    const acknowledgement = new Promise<void>((resolve, reject) => {
      server.once('error', reject);
      server.on('request', (request, response) => {
        void (async () => {
          try {
            const rejectRequest = (status: number, message: string): void => {
              response.writeHead(status).end();
              reject(new Error(message));
            };
            response.setHeader('access-control-allow-origin', '*');
            response.setHeader('access-control-allow-methods', 'POST, OPTIONS');
            response.setHeader('access-control-allow-headers', 'content-type');
            if (request.method === 'OPTIONS') {
              response.writeHead(204).end();
              return;
            }
            const origin = new URL(request.url ?? '/', 'http://127.0.0.1');
            const suppliedIndex = Number.parseInt(origin.searchParams.get('frame') ?? '', 10);
            if (
              request.method !== 'POST'
              || origin.pathname !== '/frame'
              || !localhostTokenMatches(origin.searchParams.get('token'), token)
              || suppliedIndex !== frameIndex
              || suppliedIndex <= this.#lastFrameIndex
              || request.socket.remoteAddress !== '127.0.0.1'
            ) {
              rejectRequest(403, 'loopback request rejected by token, origin, or frame-order check');
              return;
            }
            if (requestAccepted) {
              rejectRequest(409, 'loopback request already reserved');
              return;
            }
            requestAccepted = true;
            const declaredLength = Number.parseInt(request.headers['content-length'] ?? '0', 10);
            if (!Number.isSafeInteger(declaredLength) || declaredLength < 1 || declaredLength > maximumBytes) {
              rejectRequest(413, 'loopback request exceeds the expected PNG bound');
              return;
            }
            const chunks: Buffer[] = [];
            let length = 0;
            for await (const chunk of request) {
              const bytes = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
              length += bytes.byteLength;
              if (length > maximumBytes) {
                rejectRequest(413, 'loopback request exceeds the expected PNG bound');
                request.destroy();
                return;
              }
              chunks.push(bytes);
            }
            if (length !== declaredLength) {
              rejectRequest(400, 'loopback request body length did not match content-length');
              return;
            }
            received = Buffer.concat(chunks);
            const writeStarted = performance.now();
            await writeFile(temporary, received);
            await rename(temporary, destination);
            writeMilliseconds = performance.now() - writeStarted;
            this.#lastFrameIndex = frameIndex;
            response.writeHead(200, {'content-type': 'application/json'}).end(JSON.stringify({frameIndex}));
            resolve();
          } catch (error) {
            response.writeHead(500).end();
            reject(error);
          }
        })();
      });
    });
    void acknowledgement.catch(() => undefined);

    try {
      await new Promise<void>((resolve, reject) => {
        server.listen(0, '127.0.0.1', () => resolve());
        server.once('error', reject);
      });
      const address = server.address();
      if (!address || typeof address === 'string') throw new Error('loopback server did not expose a TCP port');
      const requestUrl = `http://127.0.0.1:${address.port}/frame?token=${token}&frame=${frameIndex}`;
      await this.onListening?.(requestUrl);
      const result = await canvas.evaluate(async (element, request) => {
        const started = performance.now();
        const target = element as HTMLCanvasElement;
        const blob = await new Promise<Blob>((resolve, reject) => {
          target.toBlob((value: Blob | null) => {
            if (value) resolve(value);
            else reject(new Error('canvas PNG encoding failed'));
          }, 'image/png');
        });
        const canvasEncodeCaptureMilliseconds = performance.now() - started;
        const response = await fetch(request, {method: 'POST', body: blob});
        return {
          ok: response.ok,
          body: await response.text(),
          canvasEncodeCaptureMilliseconds,
        };
      }, requestUrl);
      await acknowledgement;
      if (!result.ok || result.body !== JSON.stringify({frameIndex}) || !received) {
        throw new Error('loopback PNG capture was not acknowledged');
      }
      return {
        status: 'supported',
        name: this.name,
        transportType: 'loopback',
        destination,
        frameIndex,
        bytes: received,
        byteLength: received.byteLength,
        transportByteLength: received.byteLength,
        captureTimingMode: 'split',
        canvasEncodeCaptureMilliseconds: result.canvasEncodeCaptureMilliseconds,
        browserToNodeTransferMilliseconds: Math.max(
          0,
          performance.now()
            - captureStarted
            - result.canvasEncodeCaptureMilliseconds
            - writeMilliseconds,
        ),
        writeMilliseconds,
      };
    } finally {
      await new Promise<void>((resolve) => server.close(() => resolve()));
      await unlink(temporary).catch(() => undefined);
    }
  }
}


export const createFrameCaptures = (): FrameCapture[] => [
  new LocatorPngCapture(),
  new DataUrlPngCapture(),
  new BlobArrayBufferPngCapture(),
  new BlobBase64PngCapture(),
  new LoopbackBlobPngCapture(),
];


/** Updated only when the attested benchmark selects a new winner. */
export const PRODUCTION_CAPTURE_METHOD: CaptureMethod = 'data-url-png';


export const getFrameCapture = (method: CaptureMethod): FrameCapture => {
  const capture = createFrameCaptures().find((candidate) => candidate.name === method);
  if (!capture) throw new Error(`unknown capture method: ${method}`);
  return capture;
};
