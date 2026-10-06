export type RequestedRendererBackend = 'metal' | 'swiftshader';


/** Metal remains opt-in until its cross-backend visual gate passes. */
export const PRODUCTION_RENDERER_BACKEND: RequestedRendererBackend = 'swiftshader';


export const chromiumLaunchOptions = (backend: RequestedRendererBackend) => ({
  headless: true,
  args: [
    '--enable-webgl',
    '--ignore-gpu-blocklist',
    '--disable-dev-shm-usage',
    `--use-angle=${backend === 'metal' ? 'metal' : 'swiftshader'}`,
  ],
});


/** Safe production policy; explicit render jobs may still request Metal. */
export const productionChromiumLaunchOptions = () =>
  chromiumLaunchOptions(PRODUCTION_RENDERER_BACKEND);


/** Compatibility wrapper for explicit Metal callers and benchmark jobs. */
export const metalChromiumLaunchOptions = () => chromiumLaunchOptions('metal');
