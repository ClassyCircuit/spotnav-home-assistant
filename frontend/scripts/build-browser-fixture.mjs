import { build } from 'esbuild';
import { webAwesomeRegistration } from './web-awesome-registration.mjs';

await build({entryPoints:['sidebar/browser-fixture.js'],bundle:true,format:'esm',outfile:'prototype/dist/sidebar-browser.js',plugins:[webAwesomeRegistration]});
