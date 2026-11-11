// Optional local CDP smoke test of the shipped bundle with the backend's public fixture.
// Opens and closes only its own about:blank tab; never connects to Home Assistant.
import assert from 'node:assert/strict';
import { readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
const port = process.env.SPOTNAV_CDP_PORT ?? '9227';
const base = `http://127.0.0.1:${port}`;
const tab = await (await fetch(`${base}/json/new?about%3Ablank`, {method:'PUT'})).json();
const ws = new WebSocket(tab.webSocketDebuggerUrl);
await new Promise((ok, fail) => { ws.onopen=ok; ws.onerror=fail; });
let id=0; const pending=new Map(), requests=[];
ws.onmessage=({data})=>{const m=JSON.parse(data); if(m.method==='Network.requestWillBeSent') requests.push(m.params.request.url); if(m.id && pending.has(m.id)){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(Error(m.error.message)):p.resolve(m.result);}};
const cmd=(method,params={})=>new Promise((ok,fail)=>{const i=++id;pending.set(i,{resolve:ok,reject:fail});ws.send(JSON.stringify({id:i,method,params}));});
const evaluate=async(expression)=>{const r=await cmd('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(r.exceptionDetails.text);return r.result.value;};
try {
  const bundle=await readFile(resolve('../custom_components/spotnav/www/spotnav-card.js'),'utf8');
  const fixture=JSON.parse(await readFile(resolve('../tests/fixtures/dashboard/target_soc_two_vehicles.json'),'utf8'));
  await cmd('Network.enable'); await cmd('Runtime.enable'); await cmd('Page.enable');
  await evaluate(`(async()=>{const meta=document.createElement('meta');meta.name='viewport';meta.content='width=device-width,initial-scale=1';document.head.append(meta);customElements.define('home-assistant',class extends HTMLElement{});const url=URL.createObjectURL(new Blob([${JSON.stringify(bundle)}],{type:'text/javascript'}));await import(url);URL.revokeObjectURL(url);window.messages=[];window.fixture=${JSON.stringify(fixture)};document.body.style.cssText='margin:0;background:#111;color:#eee;--primary-text-color:#eee;--secondary-text-color:#bbb;--secondary-background-color:#252525;--divider-color:#555';const card=document.createElement('spotnav-card');card.style.display='block';card.style.maxWidth='900px';card.style.margin='10px auto';card.setConfig({type:'custom:spotnav-card',charger:window.fixture.charger.charger_id});card.hass={language:'en',user:{is_admin:true},callWS:async m=>{window.messages.push(m);if(m.type==='spotnav/get_dashboard')return window.fixture;if(m.type==='spotnav/morek_schedule'&&m.action==='status')return {api_version:1,schedule:{supported:true,verified:false,sent_at:null,ack:null,sent:null,effective:null,operator:{state:'mismatch'},verification:{reason:'limits_or_transitions_differ'},outcomes:{uncertain:false}}};throw Error('unexpected request');}};document.body.append(card);await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));})()`);
  for(const [name,width,height] of [['desktop',1440,1000],['mobile',390,844]]) {
    await cmd('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:name==='mobile'});
    const info=await evaluate(`(()=>{const c=document.querySelector('spotnav-card'),s=c.shadowRoot,o=s.querySelector('.spotnav-daily'),r=o.getBoundingClientRect();return {text:o.innerText,width:document.documentElement.scrollWidth,viewport:innerWidth,client:document.documentElement.clientWidth,box:{x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height,scale:1},messages:window.messages,grid:getComputedStyle(o.querySelector('.spotnav-daily-grid')).gridTemplateColumns,overflow:[...s.querySelectorAll('*')].filter(e=>e.getBoundingClientRect().right>document.documentElement.clientWidth+1).slice(0,8).map(e=>[e.tagName,e.className?.baseVal??e.className,e.getBoundingClientRect().right])}})()`);
    if(info.viewport!==width) console.log(JSON.stringify(info));
    assert.ok(info.width<=info.viewport, `${name} page overflow`);
    assert.equal(info.viewport,width,`${name} viewport`);
    assert.match(info.text,/Daily overview/); assert.match(info.text,/Measured power unavailable/); assert.match(info.text,/mismatch/);
    assert.ok(info.messages.every(m=>m.type==='spotnav/get_dashboard'||m.type==='spotnav/morek_schedule'&&m.action==='status'));
    const shot=await cmd('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip:info.box});
    await writeFile(resolve(process.env.TEMP ?? '.',`opencode/spotnav-52-${name}.png`),Buffer.from(shot.data,'base64'));
    console.log(`${name}: width ${info.width}/${info.viewport}; grid ${info.grid}; ${info.messages.length} read-only requests`);
  }
  assert.ok(requests.every(url=>url.startsWith('blob:')||url==='about:blank'),`unexpected browser request: ${requests}`);
} finally { ws.close(); await fetch(`${base}/json/close/${tab.id}`); }
