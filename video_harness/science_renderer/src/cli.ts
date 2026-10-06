import {readFile} from 'node:fs/promises';
import {resolve} from 'node:path';

import {renderJob} from './render-frame.js';
import type {RenderJob} from './render-job.js';


const jobPath = process.argv[2];
if (!jobPath) {
  console.error('usage: npm run render -- <render-job.json>');
  process.exitCode = 2;
} else {
  try {
    const job = JSON.parse(
      await readFile(resolve(jobPath), 'utf8'),
    ) as RenderJob;
    const report = await renderJob(job);
    process.stdout.write(`${JSON.stringify(report)}\n`);
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  }
}
