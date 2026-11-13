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
  await cmd('Page.navigate',{url:`http://127.0.0.1:8766/sidebar/browser-test.html${mode==='panel'?`?panel${process.env.SPOTNAV_READONLY_BROWSER === '1' ? '&readonly' : ''}`:''}`});
  const ready=await evaluate(`new Promise(resolve=>{let n=0;const timer=setInterval(()=>{const root=${mode==='panel' ? "document.querySelector('spotnav-enhanced-panel')?.shadowRoot" : 'document'};if(root?.querySelector('.shell') || n++>100){clearInterval(timer);resolve(!!root?.querySelector('.shell'))}},50)})`);
  assert.ok(ready,`${mode} rendered`);
  const data=await evaluate(`(()=>{const root=${mode==='panel' ? "document.querySelector('spotnav-enhanced-panel').shadowRoot" : 'document.body'};return {text:root.textContent,width:document.documentElement.scrollWidth}})()`);
  assert.match(data.text,/Price chart unavailable/); assert.match(data.text,/60 min/); assert.doesNotMatch(data.text,/216000000/); assert.doesNotMatch(data.text,/SAMPLE DATA/); assert.ok(data.width<=width);
  assert.match(data.text,/Control available · vehicle disconnected · measured charging unknown/);
  const metrics=await cmd('Page.getLayoutMetrics');const screenshot=await cmd('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip:{x:0,y:0,width:metrics.cssContentSize.width,height:metrics.cssContentSize.height,scale:1}});
  await writeFile(path.join(output,`${size}-${mode}.png`),Buffer.from(screenshot.data,'base64'));
  if(mode==='panel') {
    const owned=await evaluate(`(async()=>{const p=document.querySelector('spotnav-enhanced-panel'),r=p.shadowRoot;for(let i=0;i<100&&!p.statusAt;i++)await new Promise(resolve=>setTimeout(resolve,20));const old=p.rawStatus;window.panelMessages=[];p.rawStatus={...old,schedule:{...old.schedule,ownership:{recorded_owner:'morek_schedule'},schedule_pause:{intent:'pause_until_resumed',request:'uncertain',ack:null,readback:'unverified',measured:'unknown'}}};p.paint();const result={text:r.querySelector('#pause-state').textContent,pause:r.querySelector('#pause-auto').disabled,resume:r.querySelector('#resume-auto').disabled,writes:window.panelMessages.filter(m=>m.type==='spotnav/manual_action'||(m.type==='spotnav/morek_schedule'&&m.action!=='status')).length};p.rawStatus=old;p.paint();return result})()`);
    assert.match(owned.text,/Pause requested.*uncertain.*physical charging unknown.*Resume unavailable: Schedule ownership is not currently authorized/);assert.equal(owned.pause,false);assert.equal(owned.resume,true);assert.equal(owned.writes,0);
    if(size==='desktop') {
      const switched=await evaluate(`(async()=>{const p=document.querySelector('spotnav-enhanced-panel'),r=p.shadowRoot;for(let i=0;i<100&&(!p.settingsRecord||!p.statusAt);i++)await new Promise(resolve=>setTimeout(resolve,20));window.panelMessages=[];const input=r.querySelector('[data-setting="target"]');input.value='85';input.dispatchEvent(new Event('input',{bubbles:true}));r.querySelector('#open-plan').click();const oldDialog=r.querySelector('#plan-dialog');window.deferDashboard=true;p.refresh();for(let i=0;i<100&&!window.finishDashboard;i++)await new Promise(resolve=>setTimeout(resolve,10));const select=r.querySelector('#charger');select.value='second-fixture';select.dispatchEvent(new Event('change'));await new Promise(resolve=>setTimeout(resolve,100));window.finishDashboard();await new Promise(resolve=>setTimeout(resolve,100));return {charger:p.charger,dialogReplaced:r.querySelector('#plan-dialog')!==oldDialog,open:r.querySelector('#plan-dialog')?.open,draft:r.querySelector('[data-setting="target"]')?.value,writes:window.panelMessages.filter(m=>m.type==='spotnav/update_settings'||m.type==='spotnav/manual_action'||(m.type==='spotnav/morek_schedule'&&m.action!=='status')).length};})()`);
      assert.deepEqual(switched,{charger:'second-fixture',dialogReplaced:true,open:false,draft:'80',writes:0});
    }
    if (process.env.SPOTNAV_READONLY_BROWSER !== '1') {
    const manual=await evaluate(`(async()=>{const p=document.querySelector('spotnav-enhanced-panel'),r=p.shadowRoot;for(let i=0;i<100&&(!p.settingsRecord||!p.statusAt);i++)await new Promise(resolve=>setTimeout(resolve,20));let confirmations=0;window.confirm=()=>{confirmations++;return true};const wait=()=>new Promise(resolve=>setTimeout(resolve,100));r.querySelector('#pause-auto').click();await wait();const action=name=>[...r.querySelectorAll('#morek-debug button')].find(b=>b.textContent===name);action('Send current plan').click();await wait();action('Remove SpotNav schedule').click();await wait();r.querySelector('#resume-auto').click();await wait();const requests=window.panelMessages.filter(m=>m.type==='spotnav/manual_action'||(m.type==='spotnav/morek_schedule'&&m.action!=='status'));window.panelMessages=[];return {confirmations,requests};})()`);
    assert.equal(manual.confirmations,2);assert.deepEqual(manual.requests.map(m=>m.action),['stop','send','clear','resume']);assert.equal(manual.requests[0].choice,'until_resumed');assert.equal(manual.requests[1].preview_id,'fixture-preview');assert.equal(manual.requests[2].confirm_profile_id,42001);
    }
    const interaction=await evaluate(`(()=>{const p=document.querySelector('spotnav-enhanced-panel'),r=p.shadowRoot,input=r.querySelector('[data-setting="target"]');input.value='85';input.dispatchEvent(new Event('input',{bubbles:true}));const dialog=r.querySelector('#plan-dialog');r.querySelector('#open-plan').click();const focus=r.activeElement;dialog.scrollTop=5;const scroll=dialog.scrollTop;const morek=p.rawStatus;p.rawStatus={...morek,schedule:{...morek.schedule,operator:{state:'mismatch'},outcomes:{uncertain:true}}};p.paint();const result={same:dialog===r.querySelector('#plan-dialog'),open:dialog.open,focus:r.activeElement===focus,draft:r.querySelector('[data-setting="target"]').value,scroll:dialog.scrollTop===scroll,health:dialog.textContent.includes('mismatch'),writes:window.panelMessages.filter(m=>m.type==='spotnav/update_settings'||m.type==='spotnav/manual_action'||(m.type==='spotnav/morek_schedule'&&m.action!=='status')).length};p.rawStatus=morek;dialog.close();p.paint();return result;})()`);
    assert.deepEqual(interaction,{same:true,open:true,focus:true,draft:'85',scroll:true,health:true,writes:0});
    if (process.env.SPOTNAV_READONLY_BROWSER !== '1') {
    const result=await evaluate(`(async()=>{const p=document.querySelector('spotnav-enhanced-panel'),r=p.shadowRoot;for(let i=0;i<100&&!p.settingsRecord;i++)await new Promise(resolve=>setTimeout(resolve,20));window.saveMode=${JSON.stringify(size==='desktop'?'success':'conflict')};const input=r.querySelector('[data-setting="target"]');input.value='85';input.dispatchEvent(new Event('input',{bubbles:true}));input.focus();p.paint();const retained=r.querySelector('[data-setting="target"]')===input&&input.value==='85';r.querySelector('#save-plan').click();await new Promise(resolve=>setTimeout(resolve,100));return {retained,text:r.textContent,writes:window.panelMessages.filter(m=>m.type==='spotnav/update_settings'),actions:window.panelMessages.filter(m=>m.type==='spotnav/morek_schedule'&&m.action!=='status')};})()`);
    assert.ok(result.retained,'draft input retained during update');
    assert.equal(result.writes.length,1);assert.equal(result.writes[0].expected_revision,7);assert.equal(result.writes[0].settings.target.target_percent,85);assert.equal(result.actions.length,0);
    assert.match(result.text,size==='desktop'?/Saved and confirmed/:/Settings conflict/);
    }
  }
}
// Edge may load its own packaged extension resources; they are not network requests.
const external=requests.filter(u=>!u.startsWith('http://127.0.0.1:8766/')&&!u.startsWith('data:')&&!u.startsWith('chrome-extension:'));
assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
console.log(`preview and mocked host screenshots: ${output}; ${requests.length} local requests`);ws.close();
