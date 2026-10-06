import {describe, expect, it} from 'vitest';

import {classifyRenderer, createRenderTimer} from '../src/render-telemetry.js';


describe('renderer telemetry', () => {
  it('classifies the attested Apple ANGLE renderer as metal', () => {
    expect(classifyRenderer({
      vendor: 'Google Inc. (Apple)',
      renderer: 'ANGLE (Apple, ANGLE Metal Renderer: Apple M1)',
    })).toBe('metal');
  });

  it('classifies the attested SwiftShader renderer as swiftshader', () => {
    expect(classifyRenderer({
      vendor: 'Google Inc. (Google)',
      renderer: 'ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero)), SwiftShader driver)',
    })).toBe('swiftshader');
  });

  it('aggregates samples without emitting per-frame output', () => {
    const timer = createRenderTimer();
    timer.addInitializationMilliseconds(4.0);
    timer.addRenderMilliseconds(2.5);
    timer.addCanvasEncodeCaptureMilliseconds(4.5);
    timer.addBrowserToNodeTransferMilliseconds(3.0);
    timer.addWriteMilliseconds(1.0);

    expect(timer.summary(1)).toEqual({
      frame_count: 1,
      initialization_ms: 4.0,
      render_ms: 2.5,
      capture_ms: 7.5,
      canvas_encode_capture_ms: 4.5,
      browser_to_node_transfer_ms: 3.0,
      write_ms: 1.0,
      total_ms: 15.0,
    });
  });
});
