import { build } from 'esbuild';
import { mkdir, copyFile } from 'node:fs/promises';

await mkdir('prototype/dist', { recursive: true });
await build({ entryPoints: ['prototype/dashboard.js'], bundle: true, format: 'esm', outfile: 'prototype/dist/dashboard.js', legalComments: 'eof' });
await build({ entryPoints: ['prototype/styles.css'], bundle: true, outfile: 'prototype/dist/styles.css' });
await copyFile('node_modules/@awesome.me/webawesome/LICENSE.md', 'prototype/dist/WEB-AWESOME-LICENSE.txt');
