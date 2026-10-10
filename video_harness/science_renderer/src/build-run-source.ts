import {build} from 'esbuild';
import {mkdir, readFile, realpath} from 'node:fs/promises';
import {dirname, join, resolve, relative, sep} from 'node:path';
import {fileURLToPath} from 'node:url';

export interface RunSourceBuildDescriptor {
  snapshot_root: string;
  entrypoint: string;
  export_name: string;
  output_path: string;
  renderer_root: string;
}
const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');

export async function buildRunBrowserBundle(input: RunSourceBuildDescriptor): Promise<string> {
  const root = await realpath(input.snapshot_root);
  const entry = await realpath(resolve(root, input.entrypoint));
  const output = resolve(root, relative(resolve(input.snapshot_root), resolve(input.output_path)));
  if (!entry.startsWith(root + sep) || !output.startsWith(root + sep)) throw new Error('Run bundle paths must stay under snapshot root');
  if (!/^[A-Za-z_]\w*$/.test(input.export_name)) throw new Error('Invalid run factory export');
  const rendererRoot = await realpath(input.renderer_root);
  await mkdir(dirname(output), {recursive:true});
  await build({stdin:{contents:
    `import {registerRunSource} from ${JSON.stringify(join(rendererRoot,'src/run-source-loader.ts'))};\n` +
    `import {${input.export_name} as factory} from ${JSON.stringify(entry)};\n` +
    `import ${JSON.stringify(join(rendererRoot,'src/run-browser.ts'))};\nregisterRunSource(factory);`,
    resolveDir:root, sourcefile:'run-entry.ts',loader:'ts'},
    bundle:true,platform:'browser',format:'iife',target:['chrome120'],outfile:output,logLevel:'silent',
    nodePaths:[join(packageRoot,'node_modules')],
    plugins:[{name:'declared-run-inputs',setup(builder) {
      builder.onLoad({filter:/.*/, namespace:'file'}, async ({path}) => {
        const actual = await realpath(path);
        const dependencies = await realpath(join(packageRoot,'node_modules'));
        if (![root, rendererRoot, dependencies].some(base => actual.startsWith(base + sep))) {
          throw new Error(`Undeclared run import: ${path}`);
        }
        return undefined;
      });
    }}],
  });
  return output;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const path = process.argv[2];
  if (!path) throw new Error('Expected run build descriptor');
  await buildRunBrowserBundle(JSON.parse(await readFile(path,'utf8')) as RunSourceBuildDescriptor);
}
