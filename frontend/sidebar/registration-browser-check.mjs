// Browser regression against the shipped bundle, with mocked read-only HA calls.
import assert from 'node:assert/strict';

const tab=await (await fetch(`http://127.0.0.1:${process.env.SPOTNAV_CDP_PORT || 9248}/json/new?about:blank`,{method:'PUT'})).json();
const ws=new WebSocket(tab.webSocketDebuggerUrl);
await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject});
let id=0;const pending=new Map(), errors=[];
ws.onmessage=({data})=>{const m=JSON.parse(data);if(m.method==='Runtime.exceptionThrown') errors.push(m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text);if(m.id&&pending.has(m.id)){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(m.error):p.resolve(m.result)}};
const cmd=(method,params={})=>new Promise((resolve,reject)=>{const n=++id;pending.set(n,{resolve,reject});ws.send(JSON.stringify({id:n,method,params}))});
const evaluate=async expression=>{const result=await cmd('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(result.exceptionDetails)throw Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);return result.result.value};
await cmd('Runtime.enable');await cmd('Page.enable');await cmd('Network.enable');await cmd('Network.setCacheDisabled',{cacheDisabled:true});
for (const scenario of ['clean','icon','mixed','prior-panel','with-card','icon-prior-panel']) {
  const prereg=(scenario.includes('icon') || scenario==='mixed' ? `window.originalIcon=class extends HTMLElement {}; customElements.define('wa-icon',window.originalIcon);` : '') + (scenario==='mixed' ? `window.originalButton=class extends HTMLElement {}; customElements.define('wa-button',window.originalButton);` : '');
  const script=await cmd('Page.addScriptToEvaluateOnNewDocument',{source:prereg});
  await cmd('Page.navigate',{url:`http://127.0.0.1:${process.env.SPOTNAV_HTTP_PORT || 8766}/sidebar/browser-test.html?panel&readonly&${scenario}`});
  const result=await evaluate(`new Promise(resolve=>{let n=0;const t=setInterval(()=>{const p=document.querySelector('spotnav-enhanced-panel'),r=p?.shadowRoot;if(r?.querySelector('.shell')||n++>100){clearInterval(t);if(!r?.querySelector('.shell'))return resolve(null);const b=r.querySelector('#open-plan');b.click();resolve({text:r.textContent,dialog:r.querySelector('#plan-dialog').open,button:!!customElements.get('wa-button'),details:!!customElements.get('wa-details'),iconPreserved:!window.originalIcon||customElements.get('wa-icon')===window.originalIcon,buttonPreserved:!window.originalButton||customElements.get('wa-button')===window.originalButton,writes:window.panelMessages.filter(m=>m.type==='spotnav/manual_action'||m.type==='spotnav/update_settings'||(m.type==='spotnav/morek_schedule'&&m.action!=='status')).length})}},50)})`);
  assert.ok(result,`${scenario}: dashboard did not mount; errors: ${errors.join('\n')}`);
  assert.match(result.text,/Your vehicle/);assert.match(result.text,/Plan controls/);
  assert.equal(result.dialog,true);assert.equal(result.button,true);assert.equal(result.details,true);assert.equal(result.iconPreserved,true);assert.equal(result.buttonPreserved,true);assert.equal(result.writes,0);
  await cmd('Page.removeScriptToEvaluateOnNewDocument',{identifier:script.identifier});
}
assert.deepEqual(errors,[]);
console.log('Built sidebar registration: clean, icon, mixed, repeat, card, icon + repeat passed; no writes');
ws.close();
