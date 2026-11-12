import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
const tabs=await (await fetch(`http://127.0.0.1:${process.env.SPOTNAV_CDP_PORT || 9248}/json`)).json();
const tab=tabs.find(t=>t.type==='page'); assert.ok(tab);
const ws=new WebSocket(tab.webSocketDebuggerUrl); await new Promise((r,j)=>{ws.onopen=r;ws.onerror=j});
let id=0; const pending=new Map(), requests=[], errors=[];
ws.onmessage=({data})=>{const m=JSON.parse(data);if(m.method==='Network.requestWillBeSent') requests.push(m.params.request.url);if(m.method==='Runtime.exceptionThrown') errors.push(m.params.exceptionDetails.text);if(m.id&&pending.has(m.id)){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(m.error):p.resolve(m.result)}};
const cmd=(method,params={})=>new Promise((resolve,reject)=>{const n=++id;pending.set(n,{resolve,reject});ws.send(JSON.stringify({id:n,method,params}))});
const evaluate=async expression=>(await cmd('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true})).result.value;
await cmd('Network.enable'); await cmd('Runtime.enable'); await cmd('Page.enable');
const output=path.join(process.env.TEMP,'opencode','spotnav-54b1');await mkdir(output,{recursive:true});
for(const [size,width,height] of [['desktop',1440,1000],['mobile',390,844]]) for(const mode of ['preview','panel']) {
  await cmd('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:size==='mobile'});
  await cmd('Page.navigate',{url:`http://127.0.0.1:8766/sidebar/browser-test.html${mode==='panel'?'?panel':''}`});
  const ready=await evaluate(`new Promise(resolve=>{let n=0;const timer=setInterval(()=>{const root=${mode==='panel' ? "document.querySelector('spotnav-enhanced-panel')?.shadowRoot" : 'document'};if(root?.querySelector('.shell') || n++>100){clearInterval(timer);resolve(!!root?.querySelector('.shell'))}},50)})`);
  assert.ok(ready,`${mode} rendered`);
  const data=await evaluate(`(()=>{const root=${mode==='panel' ? "document.querySelector('spotnav-enhanced-panel').shadowRoot" : 'document.body'};return {text:root.textContent,width:document.documentElement.scrollWidth}})()`);
  assert.match(data.text,/Price chart unavailable/); assert.doesNotMatch(data.text,/SAMPLE DATA/); assert.ok(data.width<=width);
  const metrics=await cmd('Page.getLayoutMetrics');const screenshot=await cmd('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip:{x:0,y:0,width:metrics.cssContentSize.width,height:metrics.cssContentSize.height,scale:1}});
  await writeFile(path.join(output,`${size}-${mode}.png`),Buffer.from(screenshot.data,'base64'));
}
assert.deepEqual(errors,[]);assert.ok(requests.every(u=>u.startsWith('http://127.0.0.1:8766/')||u.startsWith('data:')),requests.filter(u=>!u.startsWith('http://127.0.0.1:8766/')&&!u.startsWith('data:')).join('\n'));
console.log(`preview and mocked host screenshots: ${output}; ${requests.length} local requests`);ws.close();
