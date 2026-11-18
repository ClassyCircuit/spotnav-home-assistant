import { build } from 'esbuild';
import { mkdir, copyFile } from 'node:fs/promises';
import { webAwesomeRegistration } from '../scripts/web-awesome-registration.mjs';

await mkdir('prototype/dist', { recursive: true });
await build({ entryPoints: ['prototype/dashboard.js'], bundle: true, format: 'esm', outfile: 'prototype/dist/dashboard.js', legalComments: 'eof', plugins: [webAwesomeRegistration] });
await build({ entryPoints: ['shared-dashboard/styles.css', 'shared-dashboard/dark.css', 'shared-dashboard/shell.css'], bundle: true, outdir: 'prototype/dist', entryNames: '[name]', external: ['*.webp'] });
await copyFile('shared-dashboard/art/bmw-morek-scene.webp', 'prototype/dist/bmw-morek-scene.webp');
await copyFile('shared-dashboard/art/bmw-neutral.webp', 'prototype/dist/bmw-neutral.webp');
await copyFile('node_modules/@awesome.me/webawesome/LICENSE.md', 'prototype/dist/WEB-AWESOME-LICENSE.txt');
await copyFile('node_modules/echarts/LICENSE', 'prototype/dist/ECHARTS-LICENSE.txt');
await copyFile('node_modules/echarts/NOTICE', 'prototype/dist/ECHARTS-NOTICE.txt');
await copyFile('node_modules/zrender/LICENSE', 'prototype/dist/ZRENDER-LICENSE.txt');
await copyFile('shared-dashboard/THIRD-PARTY-NOTICES.txt', 'prototype/dist/THIRD-PARTY-NOTICES.txt');
