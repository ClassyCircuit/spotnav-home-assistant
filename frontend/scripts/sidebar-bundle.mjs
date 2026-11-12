import { build } from 'esbuild';
import { readFile } from 'node:fs/promises';

export async function sidebarFiles() {
  const js = await build({entryPoints:['sidebar/panel.js'], bundle:true, format:'esm', write:false, legalComments:'eof', platform:'browser'});
  const css = await build({entryPoints:['shared-dashboard/styles.css','shared-dashboard/dark.css'], bundle:true, write:false, outdir:'out'});
  const content = css.outputFiles.map(f=>f.text.replaceAll(':root',':host').replace(/\bbody\s*\{/g,':host{')).join('\n');
  const files = new Map([['panel.js',js.outputFiles[0].contents],['panel.css',Buffer.from(content)]]);
  for (const [name, path] of Object.entries({'WEB-AWESOME-LICENSE.txt':'node_modules/@awesome.me/webawesome/LICENSE.md','ECHARTS-LICENSE.txt':'node_modules/echarts/LICENSE','ECHARTS-NOTICE.txt':'node_modules/echarts/NOTICE','ZRENDER-LICENSE.txt':'node_modules/zrender/LICENSE','THIRD-PARTY-NOTICES.txt':'shared-dashboard/THIRD-PARTY-NOTICES.txt'})) files.set(name,await readFile(path));
  return files;
}
