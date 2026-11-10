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
  if (msg.method === 'Runtime.exceptionThrown') console.error('Browser error:', msg.params.exceptionDetails.exception?.description || msg.params.exceptionDetails.text);
  if (msg.id && pending.has(msg.id)) {
    const { resolve, reject } = pending.get(msg.id); pending.delete(msg.id);
    msg.error ? reject(new Error(msg.error.message)) : resolve(msg.result);
  }
};
const cmd = (method, params = {}) => new Promise((resolve, reject) => { const key = ++id; pending.set(key, { resolve, reject }); ws.send(JSON.stringify({ id: key, method, params })); });
await cmd('Network.enable');
await cmd('Runtime.enable');
await cmd('Page.enable');
await cmd('Network.setCacheDisabled', { cacheDisabled: true });
for (const [name, width, height] of [['desktop', 1440, 1000], ['mobile', 390, 844]]) {
  await cmd('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: name === 'mobile' });
  const loaded = new Promise(resolve => { const previous = ws.onmessage; ws.onmessage = event => { previous(event); if (JSON.parse(event.data).method === 'Page.loadEventFired') { ws.onmessage = previous; resolve(); } }; });
  await cmd('Page.navigate', { url: 'http://127.0.0.1:8765/prototype/' });
  await loaded;
  const result = await cmd('Runtime.evaluate', { expression: `(async () => { await Promise.all([...document.querySelectorAll('wa-button,wa-input,wa-badge,wa-progress-bar,wa-details')].map(e => e.updateComplete)); return { width: document.documentElement.scrollWidth, viewport: innerWidth, panels: [...document.querySelectorAll('.panel')].map(e => ({ name: e.querySelector('h2').textContent, x: e.getBoundingClientRect().x, width: e.getBoundingClientRect().width })), controls: [...document.querySelectorAll('.controls wa-button,.details-body wa-button')].every(e => e.disabled), inputRendered: !!document.querySelector('wa-input').shadowRoot?.querySelector('input'), canvases: document.querySelectorAll('.chart canvas').length, rows: document.querySelectorAll('.plan-row').length, text: document.body.innerText }; })()`, awaitPromise: true, returnByValue: true });
  const value = result.result.value;
  if (!value || value.width === undefined) throw new Error(`Browser evaluation failed: ${JSON.stringify(result)}`);
  if (value.width > value.viewport) {
    const debug = await cmd('Runtime.evaluate', { expression: `JSON.stringify([...document.querySelectorAll('*')].map(e => ({ tag:e.tagName, className:e.className, right:e.getBoundingClientRect().right })).filter(e => e.right > innerWidth))`, returnByValue: true });
    console.log('Overflow:', debug.result.value);
  }
  assert.ok(value.width <= value.viewport, `${name} must not overflow horizontally: ${value.width}/${value.viewport}`);
  assert.equal(value.panels.length, 6);
  assert.deepEqual(value.panels.map(p => p.name), ['Your vehicle', 'Prices & plan', 'Plan controls', 'Charger health', 'Recent charging', 'Costs & savings']);
  assert.ok(value.controls && value.inputRendered);
  assert.equal(value.canvases, 2); assert.equal(value.rows, 3);
  for (const word of ['SAMPLE', 'needs attention', 'Measured', 'unarmed', '€0.51', '3.40 c/kWh', 'unknown']) assert.ok(value.text.toLowerCase().includes(word.toLowerCase()), word);
  if (name === 'mobile') assert.ok(value.panels.every(p => Math.abs(p.x - value.panels[0].x) < 1));
  for (const mode of ['bar', 'step']) {
    await cmd('Runtime.evaluate', { expression: `document.querySelector('[data-chart-mode="${mode}"]').click()` });
    const chartData = await cmd('Runtime.evaluate', { expression: `window.samplePriceChart.getOption().series[0].data`, returnByValue: true });
    assert.deepEqual(chartData.result.value.at(-1).slice(0, 2), [35, 36], 'last interval ends at publication cutoff');
    assert.ok(!chartData.result.value.some(p => p[0] <= 14 && p[1] > 14), 'missing price gap remains blank');
    assert.ok(chartData.result.value.some(p => p[0] === 22 && p[1] === 23 && p[2] === -2), 'negative price interval');
    assert.ok(chartData.result.value.some(p => p[1] - p[0] === .5), 'half-hour interval');
    await cmd('Runtime.evaluate', { expression: `window.samplePriceChart.dispatchAction({type:'hideTip'})` });
    await cmd('Input.dispatchMouseEvent', { type: 'mouseMoved', x: 1, y: 1 });
    const dimensions = await cmd('Page.getLayoutMetrics');
    const screenshot = await cmd('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true, clip: { x: 0, y: 0, width: dimensions.cssContentSize.width, height: dimensions.cssContentSize.height, scale: 1 } });
    const path = `${process.env.TEMP}/opencode/spotnav-${name}-${mode}.png`;
    await writeFile(path, Buffer.from(screenshot.data, 'base64'));
    const zoom = await cmd('Runtime.evaluate', { expression: `(() => { document.querySelector('#zoom-in').click(); return window.samplePriceChart.getOption().dataZoom[0].end; })()`, returnByValue: true });
    assert.ok(zoom.result.value < 100, 'zoom control changes chart');
    const slider = await cmd('Runtime.evaluate', { expression: `(() => { const c=document.querySelector('#price-chart'); c.scrollIntoView({block:'center'}); const r=c.getBoundingClientRect(); return {x:r.x+48+(r.width-68)*.5,y:r.bottom-23,dx:(r.width-68)*.08}; })()`, returnByValue: true });
    const s = slider.result.value;
    await cmd('Input.dispatchMouseEvent', { type: 'mouseMoved', x: s.x, y: s.y });
    await cmd('Input.dispatchMouseEvent', { type: 'mousePressed', x: s.x, y: s.y, button: 'left', buttons: 1, clickCount: 1 });
    await cmd('Input.dispatchMouseEvent', { type: 'mouseMoved', x: s.x + s.dx, y: s.y, button: 'left', buttons: 1 });
    await cmd('Input.dispatchMouseEvent', { type: 'mouseReleased', x: s.x + s.dx, y: s.y, button: 'left', buttons: 0, clickCount: 1 });
    const pan = await cmd('Runtime.evaluate', { expression: `window.samplePriceChart.getOption().dataZoom[0].start`, returnByValue: true });
    assert.ok(pan.result.value > 25, `dragging overview pans chart: ${pan.result.value}`);
    const reset = await cmd('Runtime.evaluate', { expression: `(() => { document.querySelector('#zoom-reset').click(); const z=window.samplePriceChart.getOption().dataZoom[0]; return [z.start,z.end]; })()`, returnByValue: true });
    assert.deepEqual(reset.result.value, [0, 100], 'reset restores full overview');
    const coords = await cmd('Runtime.evaluate', { expression: `(() => { const c = document.querySelector('#price-chart'); c.scrollIntoView({block:'center'}); const r = c.getBoundingClientRect(); const p = window.samplePriceChart.convertToPixel({xAxisIndex:0,yAxisIndex:0},[22.5,-1]); return {x:r.x+p[0],y:r.y+p[1]}; })()`, returnByValue: true });
    const point = coords.result.value;
    if (name === 'desktop') {
      await cmd('Input.dispatchMouseEvent', { type: 'mouseMoved', x: 1, y: 1 });
      await cmd('Input.dispatchMouseEvent', { type: 'mouseMoved', ...point });
    }
    else {
      await cmd('Emulation.setTouchEmulationEnabled', { enabled: true });
      await cmd('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [point] });
      await cmd('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
      await cmd('Emulation.setTouchEmulationEnabled', { enabled: false });
    }
    const tooltip = await cmd('Runtime.evaluate', { expression: `new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve(document.querySelector('#price-chart').innerText))))`, awaitPromise: true, returnByValue: true });
    assert.ok(tooltip.result.value.includes('-2.0 c/kWh'), `${mode} exact negative price tooltip: ${tooltip.result.value}`);
    console.log(`${name} ${mode}: zoom/reset and exact tooltip; screenshot ${path}`);
  }
  const edited = await cmd('Runtime.evaluate', { expression: `(() => { const input = document.querySelector('wa-input'); input.value = '75'; input.dispatchEvent(new Event('input', { bubbles: true, composed: true })); return input.value; })()`, returnByValue: true });
  assert.equal(edited.result.value, '75', 'sample input can be edited locally');
  const details = await cmd('Runtime.evaluate', { expression: `(() => { document.querySelector('a[href="#details"]').click(); return document.querySelector('#details').open; })()`, returnByValue: true });
  assert.equal(details.result.value, true, 'details link opens evidence');
  await cmd('Runtime.evaluate', { expression: `document.querySelector('#details').open = false` });
  console.log(`${name}: ${width}x${height}, six panels, two charts, three windows, no horizontal overflow, disabled charger actions`);
}
assert.ok(urls.every(url => url.startsWith('http://127.0.0.1:8765/') || url.startsWith('data:')), `Unexpected requests: ${urls.filter(url => !url.startsWith('http://127.0.0.1:8765/') && !url.startsWith('data:')).join(', ')}`);
console.log(`Network: ${urls.length} requests, all local or data URLs`);
ws.close();
