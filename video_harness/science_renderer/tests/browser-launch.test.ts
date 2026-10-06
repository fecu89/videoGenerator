import {describe, expect, it} from 'vitest';

import {
  chromiumLaunchOptions,
  metalChromiumLaunchOptions,
  PRODUCTION_RENDERER_BACKEND,
  productionChromiumLaunchOptions,
} from '../src/browser-launch.js';


describe('Metal Chromium launch policy', () => {
  it('requests Metal ANGLE while retaining the WebGL stability flags', () => {
    expect(metalChromiumLaunchOptions()).toEqual({
      headless: true,
      args: [
        '--enable-webgl',
        '--ignore-gpu-blocklist',
        '--disable-dev-shm-usage',
        '--use-angle=metal',
      ],
    });
  });
});


describe('SwiftShader Chromium launch policy', () => {
  it('keeps the production default on the backend that passed the visual gate', () => {
    expect(PRODUCTION_RENDERER_BACKEND).toBe('swiftshader');
    expect(productionChromiumLaunchOptions()).toEqual(
      chromiumLaunchOptions('swiftshader'),
    );
  });

  it('requests the actual SwiftShader ANGLE backend', () => {
    expect(chromiumLaunchOptions('swiftshader')).toEqual({
      headless: true,
      args: [
        '--enable-webgl',
        '--ignore-gpu-blocklist',
        '--disable-dev-shm-usage',
        '--use-angle=swiftshader',
      ],
    });
  });
});
