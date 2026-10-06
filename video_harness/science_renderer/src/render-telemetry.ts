export interface RendererBackendInfo {
  requested: 'metal' | 'swiftshader';
  actual: 'metal' | 'swiftshader' | 'unknown';
  vendor: string;
  renderer: string;
}


export interface RenderTimingSummary {
  frame_count: number;
  initialization_ms: number;
  render_ms: number;
  /** Backward-compatible aggregate of the two capture timing fields below. */
  capture_ms: number;
  canvas_encode_capture_ms: number;
  browser_to_node_transfer_ms: number;
  write_ms: number;
  total_ms: number;
}


export const classifyRenderer = ({renderer}: Pick<RendererBackendInfo, 'vendor' | 'renderer'>):
  RendererBackendInfo['actual'] => {
  if (/angle metal renderer/i.test(renderer)) return 'metal';
  if (/swiftshader/i.test(renderer)) return 'swiftshader';
  return 'unknown';
};


export const createRenderTimer = () => {
  let initializationMilliseconds = 0;
  let renderMilliseconds = 0;
  let canvasEncodeCaptureMilliseconds = 0;
  let browserToNodeTransferMilliseconds = 0;
  let writeMilliseconds = 0;

  return {
    addInitializationMilliseconds: (milliseconds: number): void => {
      initializationMilliseconds += milliseconds;
    },
    addRenderMilliseconds: (milliseconds: number): void => {
      renderMilliseconds += milliseconds;
    },
    addCanvasEncodeCaptureMilliseconds: (milliseconds: number): void => {
      canvasEncodeCaptureMilliseconds += milliseconds;
    },
    addBrowserToNodeTransferMilliseconds: (milliseconds: number): void => {
      browserToNodeTransferMilliseconds += milliseconds;
    },
    addWriteMilliseconds: (milliseconds: number): void => {
      writeMilliseconds += milliseconds;
    },
    summary: (frameCount: number): RenderTimingSummary => {
      const captureMilliseconds =
        canvasEncodeCaptureMilliseconds + browserToNodeTransferMilliseconds;
      return {
        frame_count: frameCount,
        initialization_ms: initializationMilliseconds,
        render_ms: renderMilliseconds,
        capture_ms: captureMilliseconds,
        canvas_encode_capture_ms: canvasEncodeCaptureMilliseconds,
        browser_to_node_transfer_ms: browserToNodeTransferMilliseconds,
        write_ms: writeMilliseconds,
        total_ms:
          initializationMilliseconds
          + renderMilliseconds
          + captureMilliseconds
          + writeMilliseconds,
      };
    },
  };
};
