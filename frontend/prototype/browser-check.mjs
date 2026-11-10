// Run against an explicitly started local Chromium DevTools endpoint.
import assert from 'node:assert/strict';
import { writeFile } from 'node:fs/promises';

const tabs = await (await fetch('http://127.0.0.1:9227/json')).json();
const tab = tabs.find(t => t.type === 'page' && t.url.includes('127.0.0.1:8765'));
assert.ok(tab, 'open the prototype in the debugging browser first');
const ws = new WebSocket(tab.webSocketDebuggerUrl);
await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
let id = 0;
const pending = new Map();
const urls = [];
ws.onmessage = ({ data }) => {
  const msg = JSON.parse(data);
  if (msg.method === 'Network.requestWillBeSent') urls.push(msg.params.request.url);
  if (msg.id && pending.has(msg.id)) {
    const { resolve, reject } = pending.get(msg.id); pending.delete(msg.id);
    msg.error ? reject(new Error(msg.error.message)) : resolve(msg.result);
  }
};
const cmd = (method, params = {}) => new Promise((resolve, reject) => { const key = ++id; pending.set(key, { resolve, reject }); ws.send(JSON.stringify({ id: key, method, params })); });
await cmd('Network.enable');
await cmd('Page.enable');
await cmd('Network.setCacheDisabled', { cacheDisabled: true });
for (const [name, width, height] of [['desktop', 1440, 1000], ['mobile', 390, 844]]) {
  await cmd('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: name === 'mobile' });
  const loaded = new Promise(resolve => { const previous = ws.onmessage; ws.onmessage = event => { previous(event); if (JSON.parse(event.data).method === 'Page.loadEventFired') { ws.onmessage = previous; resolve(); } }; });
  await cmd('Page.navigate', { url: 'http://127.0.0.1:8765/prototype/' });
  await loaded;
  const result = await cmd('Runtime.evaluate', { expression: `(async () => { await Promise.all([...document.querySelectorAll('wa-button,wa-input,wa-badge,wa-progress-bar')].map(e => e.updateComplete)); return { width: document.documentElement.scrollWidth, viewport: innerWidth, panels: [...document.querySelectorAll('.panel')].map(e => ({ name: e.querySelector('h2').textContent, x: e.getBoundingClientRect().x, width: e.getBoundingClientRect().width })), controls: [...document.querySelectorAll('wa-button')].every(e => e.disabled), inputRendered: !!document.querySelector('wa-input').shadowRoot?.querySelector('input'), text: document.body.innerText }; })()`, awaitPromise: true, returnByValue: true });
  const value = result.result.value;
  assert.ok(value.width <= value.viewport, `${name} must not overflow horizontally`);
  assert.equal(value.panels.length, 6);
  assert.deepEqual(value.panels.map(p => p.name), ['Your vehicle', 'Prices & plan', 'Plan controls', 'Morek status', 'Recent charging', 'Costs & savings']);
  assert.ok(value.controls && value.inputRendered);
  for (const word of ['SAMPLE', 'Mismatch', 'Measured', 'Unarmed']) assert.ok(value.text.includes(word), word);
  if (name === 'mobile') assert.ok(value.panels.every(p => Math.abs(p.x - value.panels[0].x) < 1));
  const edited = await cmd('Runtime.evaluate', { expression: `(() => { const input = document.querySelector('wa-input'); input.value = '75'; input.dispatchEvent(new Event('input', { bubbles: true, composed: true })); return input.value; })()`, returnByValue: true });
  assert.equal(edited.result.value, '75', 'sample input can be edited locally');
  const screenshot = await cmd('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
  const path = `${process.env.TEMP}/opencode/spotnav-${name}.png`;
  await writeFile(path, Buffer.from(screenshot.data, 'base64'));
  console.log(`${name}: ${width}x${height}, six panels, no horizontal overflow, disabled actions, inputs rendered; screenshot ${path}`);
}
assert.ok(urls.every(url => url.startsWith('http://127.0.0.1:8765/') || url.startsWith('data:')), `Unexpected requests: ${urls.filter(url => !url.startsWith('http://127.0.0.1:8765/') && !url.startsWith('data:')).join(', ')}`);
console.log(`Network: ${urls.length} requests, all local or data URLs`);
ws.close();
