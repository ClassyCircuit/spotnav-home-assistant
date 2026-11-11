// Run against the local server and an isolated Chromium DevTools profile.
import assert from 'node:assert/strict';
import { writeFile } from 'node:fs/promises';
const tabs = await (await fetch('http://127.0.0.1:9227/json')).json();
const tab = tabs.find(t => t.type === 'page' && t.url.includes('127.0.0.1:8765'));
assert.ok(tab, 'open prototype in debugging browser');
const ws = new WebSocket(tab.webSocketDebuggerUrl);
await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
let id = 0; const pending = new Map(), urls = [], errors = [];
ws.onmessage = ({data}) => { const m = JSON.parse(data); if (m.method === 'Network.requestWillBeSent') urls.push(m.params.request.url); if (m.method === 'Runtime.exceptionThrown') errors.push(m.params.exceptionDetails.text); if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.reject(new Error(m.error.message)) : p.resolve(m.result); } };
const cmd = (method, params = {}) => new Promise((resolve,reject) => { const key=++id; pending.set(key,{resolve,reject}); ws.send(JSON.stringify({id:key,method,params})); });
const evaluate = async expression => { const r = await cmd('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true}); if (r.exceptionDetails) throw new Error(r.exceptionDetails.text); return r.result.value; };
const snapped = async mode => { const z=await evaluate(`(()=>{let z=window.samplePriceCharts.${mode}.getOption().dataZoom[0];return [z.startValue,z.endValue]})()`); assert.ok(z.every(v=>Math.abs(v*4-Math.round(v*4))<1e-6),`${mode} unsnapped ${z}`); return z; };
await cmd('Network.enable'); await cmd('Runtime.enable'); await cmd('Page.enable'); await cmd('Network.setCacheDisabled',{cacheDisabled:true});
for (const [name,width,height] of [['desktop',1440,1000],['mobile',390,844]]) {
  await cmd('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:name==='mobile'});
  const loaded = new Promise(resolve => { const prev=ws.onmessage; ws.onmessage=e=>{prev(e); if(JSON.parse(e.data).method==='Page.loadEventFired'){ws.onmessage=prev;resolve();}}; });
  await cmd('Page.navigate',{url:'http://127.0.0.1:8765/prototype/'}); await loaded;
  const state=await evaluate(`(async()=>{await Promise.all([...document.querySelectorAll('wa-button,wa-input,wa-badge,wa-progress-bar,wa-details')].map(e=>e.updateComplete));return {width:document.documentElement.scrollWidth,viewport:innerWidth,panels:document.querySelectorAll('.panel').length,charts:document.querySelectorAll('.chart canvas').length,rows:document.querySelectorAll('.plan-row').length,disabled:[...document.querySelectorAll('.controls wa-button,.details-body wa-button')].every(e=>e.disabled),text:document.body.innerText,rects:[...document.querySelectorAll('.prices')].map(e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height}})};})()`);
  assert.ok(state.width<=state.viewport,`${name} overflow ${state.width}/${state.viewport}`); assert.equal(state.panels,7); assert.equal(state.charts,3); assert.equal(state.rows,6); assert.ok(state.disabled); assert.ok(state.rects[1].y>state.rects[0].y); assert.ok(Math.abs(state.rects[0].width-state.rects[1].width)<1);
  for(const text of ['unverified','unarmed','26.45 c/kwh','00:37:30','not an optimized']) assert.ok(state.text.toLowerCase().includes(text),text);
  const layout=await evaluate(`(()=>{let a=document.querySelector('.overview').getBoundingClientRect(),b=document.querySelector('.controls').getBoundingClientRect();return {ax:a.x,ay:a.y,aw:a.width,bx:b.x,by:b.y,bw:b.width}})()`);
  if(name==='desktop') {assert.ok(Math.abs(layout.ay-layout.by)<1 && layout.bx>layout.ax && Math.abs(layout.aw-layout.bw)<1,'overview and controls side by side');} else assert.ok(layout.by>layout.ay,'controls follow overview');
  const consistency=await evaluate(`(()=>{let nodes=['.prices-bar','.prices-step','#plan-dialog'].map(s=>document.querySelector(s));return nodes.map(n=>({rows:[...n.querySelectorAll('.plan-row')].map(e=>e.textContent),total:n.querySelector('.plan-total').textContent}))})()`);
  assert.deepEqual(consistency[0],consistency[1]); assert.deepEqual(consistency[0],consistency[2]);
  await evaluate(`document.querySelector('#open-plan').focus()`);
  await cmd('Input.dispatchKeyEvent',{type:'keyDown',key:' ',code:'Space',windowsVirtualKeyCode:32}); await cmd('Input.dispatchKeyEvent',{type:'keyUp',key:' ',code:'Space',windowsVirtualKeyCode:32});
  assert.equal(await evaluate(`document.querySelector('#plan-dialog').open`),true); assert.equal(await evaluate(`document.activeElement.id`),'close-plan');
  await cmd('Input.dispatchKeyEvent',{type:'keyDown',key:'Tab',code:'Tab',windowsVirtualKeyCode:9}); await cmd('Input.dispatchKeyEvent',{type:'keyUp',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});
  assert.ok(await evaluate(`document.activeElement===document.body || document.querySelector('#plan-dialog').contains(document.activeElement)`),'modal does not focus background controls');
  const modal=await cmd('Page.captureScreenshot',{format:'png'}); await writeFile(`${process.env.TEMP}/opencode/spotnav-51b2-${name}-modal.png`,Buffer.from(modal.data,'base64'));
  await cmd('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape',windowsVirtualKeyCode:27}); await cmd('Input.dispatchKeyEvent',{type:'keyUp',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});
  assert.equal(await evaluate(`document.querySelector('#plan-dialog').open`),false); assert.equal(await evaluate(`document.activeElement.id`),'open-plan');
  await evaluate(`document.querySelector('#open-plan').click();document.querySelector('#close-plan').click()`);
  assert.equal(await evaluate(`document.querySelector('#plan-dialog').open`),false);
  const metrics=await cmd('Page.getLayoutMetrics');
  const full=await cmd('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip:{x:0,y:0,width:metrics.cssContentSize.width,height:metrics.cssContentSize.height,scale:1}});
  await writeFile(`${process.env.TEMP}/opencode/spotnav-51b2-${name}-full.png`,Buffer.from(full.data,'base64'));
  for(const mode of ['bar','step']) {
    const data=await evaluate(`window.samplePriceCharts.${mode}.getOption().series[0].data`);
    assert.equal(data.length,288); assert.deepEqual(data[0].slice(0,2),[-24,-23.75]); assert.deepEqual(data.at(-1).slice(0,2),[47.75,48]);
    const wheel=await evaluate(`(()=>{let c=document.querySelector('#price-${mode}');c.scrollIntoView({block:'center'});let r=c.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()`);
    if(name==='mobile') {
      try { await cmd('Emulation.setTouchEmulationEnabled',{enabled:true}); await cmd('Input.synthesizePinchGesture',{x:wheel.x,y:wheel.y,scaleFactor:1.5,relativeSpeed:800,gestureSourceType:'touch'}); const span=await evaluate(`(()=>{let z=window.samplePriceCharts.${mode}.getOption().dataZoom[0];return z.end-z.start})()`); console.log(`mobile ${mode}: simulated pinch span ${span.toFixed(1)}%`); await cmd('Emulation.setTouchEmulationEnabled',{enabled:false}); }
      catch { console.log(`mobile ${mode}: simulated pinch unavailable`); }
      await evaluate(`document.querySelector('[data-reset="${mode}"]').click()`);
    }
    await cmd('Input.dispatchMouseEvent',{type:'mouseWheel',...wheel,deltaX:0,deltaY:-120});
    assert.ok(await evaluate(`window.samplePriceCharts.${mode}.getOption().dataZoom[0].end-window.samplePriceCharts.${mode}.getOption().dataZoom[0].start`)<100,`${mode} real wheel zoom`);
    await snapped(mode);
    await evaluate(`document.querySelector('[data-reset="${mode}"]').click()`);
    const zoom=await evaluate(`(()=>{document.querySelector('[data-zoom="${mode}"]').click();return window.samplePriceCharts.${mode}.getOption().dataZoom[0].end})()`); assert.ok(zoom<100);
    await snapped(mode);
    if(name==='desktop') {
      const before=await snapped(mode);
      await cmd('Input.dispatchMouseEvent',{type:'mousePressed',...wheel,button:'left',buttons:1,clickCount:1});
      await cmd('Input.dispatchMouseEvent',{type:'mouseMoved',x:wheel.x+80,y:wheel.y,button:'left',buttons:1});
      await cmd('Input.dispatchMouseEvent',{type:'mouseReleased',x:wheel.x+80,y:wheel.y,button:'left',buttons:0,clickCount:1});
      assert.notDeepEqual(await snapped(mode),before,'plot drag pans');
      const beforeSlider=await snapped(mode);
      const slider=await evaluate(`(()=>{let c=document.querySelector('#price-${mode}');c.scrollIntoView({block:'center'});let r=c.getBoundingClientRect();return {x:r.x+48+(r.width-68)*.5,y:r.bottom-26,dx:(r.width-68)*.08}})()`);
      await cmd('Input.dispatchMouseEvent',{type:'mouseMoved',x:slider.x,y:slider.y}); await cmd('Input.dispatchMouseEvent',{type:'mousePressed',x:slider.x,y:slider.y,button:'left',buttons:1,clickCount:1}); await cmd('Input.dispatchMouseEvent',{type:'mouseMoved',x:slider.x+slider.dx,y:slider.y,button:'left',buttons:1}); await cmd('Input.dispatchMouseEvent',{type:'mouseReleased',x:slider.x+slider.dx,y:slider.y,button:'left',buttons:0,clickCount:1});
      assert.notDeepEqual(await snapped(mode),beforeSlider,'slider drag pans');
    }
    const zoomRect=await evaluate(`(()=>{let r=document.querySelector('.prices-${mode}').getBoundingClientRect();return {x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height,scale:1}})()`);
    const zoomImage=await cmd('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip:zoomRect});
    await writeFile(`${process.env.TEMP}/opencode/spotnav-51b3-${name}-${mode}-zoom.png`,Buffer.from(zoomImage.data,'base64'));
    const reset=await evaluate(`(()=>{document.querySelector('[data-reset="${mode}"]').click();let z=window.samplePriceCharts.${mode}.getOption().dataZoom[0];return [z.start,z.end]})()`); assert.deepEqual(reset,[0,100]);
    await snapped(mode);
    if(name==='desktop') {
      await evaluate(`document.querySelector('[data-zoom="${mode}"]').shadowRoot.querySelector('button').focus()`);
      await cmd('Input.dispatchKeyEvent',{type:'keyDown',key:' ',code:'Space',windowsVirtualKeyCode:32}); await cmd('Input.dispatchKeyEvent',{type:'keyUp',key:' ',code:'Space',windowsVirtualKeyCode:32});
      assert.ok(await evaluate(`window.samplePriceCharts.${mode}.getOption().dataZoom[0].end`)<100,'keyboard zoom');
      await evaluate(`document.querySelector('[data-reset="${mode}"]').click()`);
    }
    const point=await evaluate(`(()=>{let c=document.querySelector('#price-${mode}');c.scrollIntoView({block:'center'});let r=c.getBoundingClientRect(), p=window.samplePriceCharts.${mode}.convertToPixel({xAxisIndex:0,yAxisIndex:0},[24.125,10]);return {x:r.x+p[0],y:r.y+p[1]}})()`);
    if(name==='desktop') await cmd('Input.dispatchMouseEvent',{type:'mouseMoved',...point}); else {await cmd('Emulation.setTouchEmulationEnabled',{enabled:true});await cmd('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[point]});}
    let tip=await evaluate(`new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(()=>r(document.querySelector('#price-${mode}').innerText))))`);
    if(name==='mobile' && !/22\.35|22\.65|23\.05/.test(tip)) { console.log(`mobile ${mode}: emulated touch missed the narrow target; testing programmatic tooltip`); await evaluate(`window.samplePriceCharts.${mode}.dispatchAction({type:'showTip',seriesIndex:0,dataIndex:192})`); tip=await evaluate(`new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(()=>r(document.querySelector('#price-${mode}').innerText))))`); }
    assert.ok(/22\.35|22\.65|23\.05/.test(tip) && tip.includes('c/kWh'),`${name} ${mode}: ${tip}`);
    if(name==='mobile') { await cmd('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]}); await cmd('Emulation.setTouchEmulationEnabled',{enabled:false}); }
    await cmd('Input.dispatchMouseEvent',{type:'mouseMoved',x:1,y:1});
    await evaluate(`window.samplePriceCharts.${mode}.dispatchAction({type:'hideTip'})`);
    await evaluate(`new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))`);
    const rect=await evaluate(`(()=>{let r=document.querySelector('.prices-${mode}').getBoundingClientRect();return {x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height,scale:1}})()`);
    const image=await cmd('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip:rect});
    await writeFile(`${process.env.TEMP}/opencode/spotnav-51b3-${name}-${mode}.png`,Buffer.from(image.data,'base64'));
    if(name==='desktop') {
      await evaluate(`(()=>{let c=window.samplePriceCharts.${mode}; c.setOption({xAxis:{min:-1,max:2,interval:.5},series:[{data:[[-1,0,-5],[.5,1.25,8]]}${mode==='step' ? ",{data:[[-1,-5],[0,-5],[.25,null],[.5,8],[1.25,8]]}" : ''}]});})()`);
      const fixture=await evaluate(`(()=>{let c=window.samplePriceCharts.${mode};return {negative:c.convertToPixel({yAxisIndex:0},-5),zero:c.convertToPixel({yAxisIndex:0},0),data:c.getOption().series[0].data}})()`);
      assert.ok(fixture.negative>fixture.zero,'negative values render below zero'); assert.deepEqual(fixture.data,[[-1,0,-5],[.5,1.25,8]]);
      const img=await cmd('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip:rect}); await writeFile(`${process.env.TEMP}/opencode/spotnav-51b2-fixture-${mode}.png`,Buffer.from(img.data,'base64'));
    }
    console.log(`${name} ${mode}: interval endpoints, zoom/reset, tooltip and screenshot passed`);
  }
  console.log(`${name}: full page and both cards, no horizontal overflow`);
}
assert.deepEqual(errors,[]); assert.ok(urls.every(u=>u.startsWith('http://127.0.0.1:8765/')||u.startsWith('data:')),'unexpected network request'); console.log(`${urls.length} local/data requests`); ws.close();
