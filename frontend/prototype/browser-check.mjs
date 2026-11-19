// Run against the local server and an isolated Chromium DevTools profile.
import assert from 'node:assert/strict';
import { writeFile } from 'node:fs/promises';
const tabs = await (await fetch(`http://127.0.0.1:${process.env.SPOTNAV_CDP_PORT || '9227'}/json`)).json();
const tab = tabs.find(t => t.type === 'page' && t.url.includes('127.0.0.1:8765'));
assert.ok(tab, 'open prototype in debugging browser');
const ws = new WebSocket(tab.webSocketDebuggerUrl);
await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
let id = 0; const pending = new Map(), urls = [], errors = [];
ws.onmessage = ({data}) => { const m = JSON.parse(data); if (m.method === 'Network.requestWillBeSent') urls.push(m.params.request.url); if (m.method === 'Runtime.exceptionThrown') errors.push(m.params.exceptionDetails.text); if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.reject(new Error(m.error.message)) : p.resolve(m.result); } };
const cmd = (method, params = {}) => new Promise((resolve,reject) => { const key=++id; pending.set(key,{resolve,reject}); ws.send(JSON.stringify({id:key,method,params})); });
const evaluate = async expression => { const r = await cmd('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true}); if (r.exceptionDetails) throw new Error(r.exceptionDetails.text); return r.result.value; };
const showTab = async name => { await evaluate(`document.querySelector('#sn-tab-${name}').click()`); await evaluate(`new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))`); };
const snapped = async mode => { const z=await evaluate(`(()=>{let z=window.samplePriceCharts.${mode}.getOption().dataZoom[0];return [z.startValue,z.endValue]})()`); assert.ok(z.every(v=>Math.abs(v*4-Math.round(v*4))<1e-6),`${mode} unsnapped ${z}`); return z; };
const labels = async mode => { const ticks=await evaluate(`[...document.querySelectorAll('#price-${mode} .time-ticks span')].map(e=>({hour:Number(e.dataset.hour),text:e.innerText,rect:e.getBoundingClientRect().toJSON()}))`); assert.ok(ticks.length>0,'visible time labels'); for(const t of ticks) {assert.ok(Number.isInteger(t.hour/2) || ticks.length>8 && Number.isInteger(t.hour*4),`unaligned tick ${t.hour}`); if(t.hour===24) assert.match(t.text,/Tue 10 Nov/);} for(let i=1;i<ticks.length;i++) assert.ok(ticks[i].rect.left>=ticks[i-1].rect.right-1,'overlapping time labels'); return ticks; };
const band = async mode => { const info=await evaluate(`(()=>{const c=window.samplePriceCharts.${mode},root=c.getDom().getBoundingClientRect();return {cells:[...root && c.getDom().querySelectorAll('.day-cell')].map(e=>({start:+e.dataset.start,end:+e.dataset.end,text:e.textContent,left:e.getBoundingClientRect().left-root.left,right:e.getBoundingClientRect().right-root.left,expectedLeft:c.convertToPixel({xAxisIndex:0},+e.dataset.start),expectedRight:c.convertToPixel({xAxisIndex:0},+e.dataset.end)})),lines:[...c.getDom().querySelectorAll('.midnight-line')].map(e=>({hour:+e.dataset.hour,left:e.getBoundingClientRect().left-root.left,expected:c.convertToPixel({xAxisIndex:0},+e.dataset.hour)}))}})()`); assert.ok(info.cells.length); for(const c of info.cells){assert.ok(Math.abs(c.left-c.expectedLeft)<1 && Math.abs(c.right-c.expectedRight)<1,'day band alignment'); if(c.right-c.left>=140) assert.match(c.text,/Nov/);} for(const l of info.lines) assert.ok(Math.abs(l.left-l.expected)<1,'midnight line alignment'); return info; };
await cmd('Network.enable'); await cmd('Runtime.enable'); await cmd('Page.enable'); await cmd('Network.setCacheDisabled',{cacheDisabled:true});
await cmd('Page.bringToFront');
for (const [name,width,height] of [['desktop',1440,1000],['mobile',390,844]]) {
  await cmd('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:name==='mobile'});
  const loaded = new Promise(resolve => { const prev=ws.onmessage; ws.onmessage=e=>{prev(e); if(JSON.parse(e.data).method==='Page.loadEventFired'){ws.onmessage=prev;resolve();}}; });
  await cmd('Page.navigate',{url:'http://127.0.0.1:8765/prototype/?comparison=bar'}); await loaded;
  await showTab('overview');
  const state=await evaluate(`(async()=>{await Promise.all([...document.querySelectorAll('wa-button,wa-input,wa-badge,wa-progress-bar,wa-details')].map(e=>e.updateComplete));return {width:document.documentElement.scrollWidth,viewport:innerWidth,panels:document.querySelectorAll('.panel').length,charts:document.querySelectorAll('.chart canvas').length,rows:document.querySelectorAll('.windows .win-row').length,disabled:[...document.querySelectorAll('.controls wa-button,.details-body wa-button')].every(e=>e.disabled),text:document.body.innerText,rects:[...document.querySelectorAll('.prices')].map(e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height}})};})()`);
  assert.ok(state.width<=state.viewport,`${name} overflow ${state.width}/${state.viewport}`); assert.ok(state.panels >= 8, 'shared tab panels are mounted'); assert.equal(state.charts,3); assert.ok(state.rows > 0); assert.ok(state.disabled); assert.ok(state.rects[1].y>state.rects[0].y); assert.ok(Math.abs(state.rects[0].width-state.rects[1].width)<1);
  await showTab('settings');
  state.text += ' ' + await evaluate(`document.body.innerText`);
  await showTab('overview');
  for(const text of ['unverified','unarmed','26.45 c/kwh','00:37:30','not an optimized']) assert.ok(state.text.toLowerCase().includes(text),text);
  const layout=await evaluate(`(()=>{const hero=document.querySelector('.overview'),controls=hero.querySelector('#automatic-controls');return {hasControls:!!controls,inside:!!controls && hero.contains(controls)}})()`);
  assert.ok(layout.hasControls && layout.inside, 'charging controls belong to the Overview hero');
  const cardsClip=await evaluate(`(()=>{const r=document.querySelector('.overview').getBoundingClientRect();return {x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height,scale:1}})()`);
  const cardsImage=await cmd('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip:cardsClip}); await writeFile(`${process.env.TEMP}/opencode/spotnav-51b4a-${name}-cards.png`,Buffer.from(cardsImage.data,'base64'));
  const vehicle=await evaluate(`(()=>{const e=document.querySelector('.overview'),r=e.getBoundingClientRect();return {text:e.innerText,clip:{x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height,scale:1}}})()`);
  assert.match(vehicle.text,/28\.8 kWh/); assert.match(vehicle.text,/19\.2 kWh/); assert.match(vehicle.text,/21\.3 kWh/); assert.match(vehicle.text,/Target/);
  const contrast=await evaluate(`(()=>{const parse=s=>s.match(/[0-9]+/g).slice(0,3).map(Number),lum=c=>{const a=c.map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4});return .2126*a[0]+.7152*a[1]+.0722*a[2]},fg=lum(parse(getComputedStyle(document.querySelector('.battery-note')).color)),bg=lum(parse(getComputedStyle(document.querySelector('.overview')).backgroundColor));return (Math.max(fg,bg)+.05)/(Math.min(fg,bg)+.05)})()`); assert.ok(contrast>=4.5,`battery note contrast ${contrast}`);
  const vehicleImg=await cmd('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip:vehicle.clip}); await writeFile(`${process.env.TEMP}/opencode/spotnav-51e-${name}-vehicle.png`,Buffer.from(vehicleImg.data,'base64'));
  await showTab('settings');
  const evidence=await evaluate(`(()=>{const e=document.querySelector('.morek'),r=e.getBoundingClientRect();return {text:e.innerText,clip:{x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height,scale:1}}})()`);
  assert.match(evidence.text,/mismatch with last sent/); assert.match(evidence.text,/14:15/); assert.match(evidence.text,/14:28/); assert.match(evidence.text,/not a profile inventory/); assert.match(evidence.text,/does not prove physical charging/);
  const evidenceImg=await cmd('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip:evidence.clip}); await writeFile(`${process.env.TEMP}/opencode/spotnav-51e-${name}-evidence.png`,Buffer.from(evidenceImg.data,'base64'));
  await showTab('overview');
  const chartPrice=await evaluate(`document.querySelector('.prices-bar .price-context span').innerText`);
  await showTab('explore');
  const insightsState=await evaluate(`(()=>{const el=document.querySelector('.insights'),r=el.getBoundingClientRect();return {text:el.innerText,clip:{x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height,scale:1}}})()`);
  assert.match(insightsState.text,/November 2026 so far/); assert.match(insightsState.text,/100\.0% of the expected time/); assert.match(insightsState.text,/not the charging plan/i); assert.ok(insightsState.text.includes(chartPrice.replace('Now ','').trim()));
  const insightImage=await cmd('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip:insightsState.clip}); await writeFile(`${process.env.TEMP}/opencode/spotnav-51c-${name}-insights.png`,Buffer.from(insightImage.data,'base64'));
  await evaluate(`document.querySelector('.insights wa-details').open=true`);
  const method=await evaluate(`document.querySelector('.insights wa-details').innerText`); assert.match(method,/30 completed local days/); assert.match(method,/at least 7/); await evaluate(`document.querySelector('.insights wa-details').open=false`);
  await showTab('overview');
  const windows=await evaluate(`(()=>({list:document.querySelectorAll('.windows [data-win-select]').length,dialog:document.querySelectorAll('#plan-dialog .plan-row').length,links:document.querySelectorAll('[data-chart-windows]').length}))()`);
  assert.ok(windows.list > 0 && windows.dialog > 0); assert.equal(windows.links,2);
  await showTab('overview');
  await evaluate(`document.querySelector('#open-plan').focus()`);
  await cmd('Input.dispatchKeyEvent',{type:'keyDown',key:' ',code:'Space',windowsVirtualKeyCode:32}); await cmd('Input.dispatchKeyEvent',{type:'keyUp',key:' ',code:'Space',windowsVirtualKeyCode:32});
  assert.equal(await evaluate(`document.querySelector('#plan-dialog').open`),true); assert.equal(await evaluate(`document.activeElement.id`),'close-plan');
  await cmd('Input.dispatchKeyEvent',{type:'keyDown',key:'Tab',code:'Tab',windowsVirtualKeyCode:9}); await cmd('Input.dispatchKeyEvent',{type:'keyUp',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});
  assert.ok(await evaluate(`document.activeElement===document.body || document.querySelector('#plan-dialog').contains(document.activeElement)`),'modal does not focus background controls');
  const modal=await cmd('Page.captureScreenshot',{format:'png'}); await writeFile(`${process.env.TEMP}/opencode/spotnav-51b4-${name}-modal.png`,Buffer.from(modal.data,'base64'));
  await cmd('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape',windowsVirtualKeyCode:27}); await cmd('Input.dispatchKeyEvent',{type:'keyUp',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});
  assert.equal(await evaluate(`document.querySelector('#plan-dialog').open`),false); assert.equal(await evaluate(`document.activeElement.id`),'open-plan');
  await evaluate(`document.querySelector('#open-plan').click()`);
  const inside=await evaluate(`(()=>{const r=document.querySelector('#plan-dialog').getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+20}})()`);
  await cmd('Input.dispatchMouseEvent',{type:'mousePressed',...inside,button:'left',clickCount:1}); await cmd('Input.dispatchMouseEvent',{type:'mouseReleased',...inside,button:'left',clickCount:1});
  assert.equal(await evaluate(`document.querySelector('#plan-dialog').open`),true,'inside click stays open');
  await cmd('Input.dispatchMouseEvent',{type:'mousePressed',x:2,y:2,button:'left',clickCount:1}); await cmd('Input.dispatchMouseEvent',{type:'mouseReleased',x:2,y:2,button:'left',clickCount:1});
  assert.equal(await evaluate(`document.querySelector('#plan-dialog').open`),false,'outside click closes'); assert.equal(await evaluate(`document.activeElement.id`),'open-plan');
  await evaluate(`document.querySelector('#open-plan').click();document.querySelector('#close-plan').click()`);
  assert.equal(await evaluate(`document.querySelector('#plan-dialog').open`),false);
  await evaluate(`new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))`);
  await showTab('settings');
  await evaluate(`document.querySelector('#open-plan-details').focus()`);
  await cmd('Input.dispatchKeyEvent',{type:'keyDown',key:' ',code:'Space',windowsVirtualKeyCode:32}); await cmd('Input.dispatchKeyEvent',{type:'keyUp',key:' ',code:'Space',windowsVirtualKeyCode:32});
  assert.equal(await evaluate(`document.querySelector('#plan-dialog').open`),true);
  await evaluate(`document.querySelector('#close-plan').click()`); assert.equal(await evaluate(`document.activeElement.id`),'open-plan-details');
  await showTab('overview');
  const metrics=await cmd('Page.getLayoutMetrics');
  const full=await cmd('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip:{x:0,y:0,width:metrics.cssContentSize.width,height:metrics.cssContentSize.height,scale:1}});
  await writeFile(`${process.env.TEMP}/opencode/spotnav-51d-${name}-full.png`,Buffer.from(full.data,'base64'));
  for(const mode of ['bar','step']) {
    assert.deepEqual(await snapped(mode),[13,48]);
    const defaultTicks=await labels(mode);
    const defaultBand=await band(mode); assert.ok(defaultBand.lines.some(l=>l.hour===24),'midnight shown in default view');
    const proposal=await evaluate(`(()=>{const c=window.samplePriceCharts.${mode},root=c.getDom().getBoundingClientRect();return [...c.getDom().querySelectorAll('.proposal-gradient,.proposal-track')].map(e=>({type:e.className,start:+e.dataset.start,end:+e.dataset.end,left:e.getBoundingClientRect().left-root.left,right:e.getBoundingClientRect().right-root.left,expectedLeft:c.convertToPixel({xAxisIndex:0},+e.dataset.start),expectedRight:c.convertToPixel({xAxisIndex:0},+e.dataset.end),background:getComputedStyle(e).backgroundImage}))})()`);
    assert.deepEqual(proposal.filter(p=>p.type==='proposal-gradient').map(p=>[p.start,p.end]),[[24,24.625],[25,25.375]]);
    assert.equal(proposal.filter(p=>p.type==='proposal-track').length,2);
    for(const p of proposal) { assert.ok(Math.abs(p.left-p.expectedLeft)<1 && Math.abs(p.right-p.expectedRight)<1,'proposal exact bounds'); if(p.type==='proposal-gradient') assert.match(p.background,/linear-gradient/); }
    if(name==='desktop') assert.equal(defaultTicks[1].hour-defaultTicks[0].hour,2,'default desktop uses two-hour cadence');
    await evaluate(`document.querySelector('.prices-${mode}').scrollIntoView({block:'start'})`);
    const defaultRect=await evaluate(`(()=>{let r=document.querySelector('.prices-${mode}').getBoundingClientRect();return {x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height,scale:1}})()`);
    const defaultImage=await cmd('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip:defaultRect});
    await writeFile(`${process.env.TEMP}/opencode/spotnav-51b3-gradient-${name}-${mode}-default.png`,Buffer.from(defaultImage.data,'base64'));
    const data=await evaluate(`window.samplePriceCharts.${mode}.getOption().series[0].data`);
    assert.equal(data.length,288); assert.deepEqual(data[0].slice(0,2),[-24,-23.75]); assert.deepEqual(data.at(-1).slice(0,2),[47.75,48]);
    const wheel=await evaluate(`(()=>{let c=document.querySelector('#price-${mode}');c.scrollIntoView({block:'center'});let r=c.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()`);
    if(name==='mobile') {
      await cmd('Emulation.setTouchEmulationEnabled',{enabled:true}); const before=await snapped(mode); await cmd('Input.synthesizePinchGesture',{x:wheel.x,y:wheel.y,scaleFactor:1.5,relativeSpeed:800,gestureSourceType:'touch'}); const after=await snapped(mode); assert.ok(after[1]-after[0]<before[1]-before[0],'emulated pinch zooms'); await labels(mode); console.log(`mobile ${mode}: simulated pinch ${before} -> ${after}`); await cmd('Emulation.setTouchEmulationEnabled',{enabled:false});
      await evaluate(`document.querySelector('[data-reset="${mode}"]').click()`);
    }
    await cmd('Input.dispatchMouseEvent',{type:'mouseWheel',...wheel,deltaX:0,deltaY:-120});
    assert.ok(await evaluate(`window.samplePriceCharts.${mode}.getOption().dataZoom[0].end-window.samplePriceCharts.${mode}.getOption().dataZoom[0].start`)<100,`${mode} real wheel zoom`);
    await snapped(mode);
    await labels(mode);
    await band(mode);
    const selected=await snapped(mode);
    await evaluate(`window.samplePriceCharts.${mode}.resize()`);
    assert.deepEqual(await snapped(mode),selected,'resize preserves selected view');
    await evaluate(`document.querySelector('[data-reset="${mode}"]').click()`);
    const zoom=await evaluate(`(()=>{document.querySelector('[data-zoom="${mode}"]').click();return window.samplePriceCharts.${mode}.getOption().dataZoom[0].end})()`); assert.ok(zoom<100);
    await snapped(mode);
    if(name==='desktop') {
      const before=await snapped(mode);
      await cmd('Input.dispatchMouseEvent',{type:'mousePressed',...wheel,button:'left',buttons:1,clickCount:1});
      await cmd('Input.dispatchMouseEvent',{type:'mouseMoved',x:wheel.x+80,y:wheel.y,button:'left',buttons:1});
      await cmd('Input.dispatchMouseEvent',{type:'mouseReleased',x:wheel.x+80,y:wheel.y,button:'left',buttons:0,clickCount:1});
      assert.notDeepEqual(await snapped(mode),before,'plot drag pans');
      await labels(mode);
      await band(mode);
      const beforeSlider=await snapped(mode);
      const slider=await evaluate(`(()=>{let c=document.querySelector('#price-${mode}');c.scrollIntoView({block:'center'});let r=c.getBoundingClientRect();return {x:r.x+48+(r.width-68)*.5,y:r.bottom-26,dx:(r.width-68)*.08}})()`);
      await cmd('Input.dispatchMouseEvent',{type:'mouseMoved',x:slider.x,y:slider.y}); await cmd('Input.dispatchMouseEvent',{type:'mousePressed',x:slider.x,y:slider.y,button:'left',buttons:1,clickCount:1}); await cmd('Input.dispatchMouseEvent',{type:'mouseMoved',x:slider.x+slider.dx,y:slider.y,button:'left',buttons:1}); await cmd('Input.dispatchMouseEvent',{type:'mouseReleased',x:slider.x+slider.dx,y:slider.y,button:'left',buttons:0,clickCount:1});
      assert.notDeepEqual(await snapped(mode),beforeSlider,'slider drag pans');
      await labels(mode);
      await band(mode);
    }
    if(name==='mobile') {
      const before=await snapped(mode);
      await cmd('Input.dispatchMouseEvent',{type:'mousePressed',...wheel,button:'left',buttons:1,clickCount:1});
      await cmd('Input.dispatchMouseEvent',{type:'mouseMoved',x:wheel.x+25,y:wheel.y,button:'left',buttons:1});
      await cmd('Input.dispatchMouseEvent',{type:'mouseReleased',x:wheel.x+25,y:wheel.y,button:'left',buttons:0,clickCount:1});
      assert.notDeepEqual(await snapped(mode),before,'mobile-width plot drag pans');
      await labels(mode); await band(mode);
    }
    await cmd('Input.dispatchMouseEvent',{type:'mouseMoved',x:1,y:1});
    await evaluate(`window.samplePriceCharts.${mode}.dispatchAction({type:'hideTip'})`);
    assert.ok((await band(mode)).lines.some(l=>l.hour===24),'zoom/pan view crosses sample midnight');
    const zoomRect=await evaluate(`(()=>{let r=document.querySelector('.prices-${mode}').getBoundingClientRect();return {x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height,scale:1}})()`);
    const zoomImage=await cmd('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip:zoomRect});
    await writeFile(`${process.env.TEMP}/opencode/spotnav-51b3-gradient-${name}-${mode}-zoom.png`,Buffer.from(zoomImage.data,'base64'));
    const reset=await evaluate(`(()=>{document.querySelector('[data-reset="${mode}"]').click();let z=window.samplePriceCharts.${mode}.getOption().dataZoom[0];return [z.start,z.end]})()`); assert.deepEqual(reset,[0,100]);
    await snapped(mode);
    if(name==='desktop') {
      await evaluate(`document.querySelector('[data-zoom="${mode}"]').shadowRoot.querySelector('button').focus()`);
      await cmd('Input.dispatchKeyEvent',{type:'keyDown',key:' ',code:'Space',windowsVirtualKeyCode:32}); await cmd('Input.dispatchKeyEvent',{type:'keyUp',key:' ',code:'Space',windowsVirtualKeyCode:32});
      assert.ok(await evaluate(`window.samplePriceCharts.${mode}.getOption().dataZoom[0].end`)<100,'keyboard zoom');
      await snapped(mode); await labels(mode);
      await evaluate(`document.querySelector('[data-reset="${mode}"]').shadowRoot.querySelector('button').focus()`);
      await cmd('Input.dispatchKeyEvent',{type:'keyDown',key:' ',code:'Space',windowsVirtualKeyCode:32}); await cmd('Input.dispatchKeyEvent',{type:'keyUp',key:' ',code:'Space',windowsVirtualKeyCode:32});
      assert.deepEqual(await snapped(mode),[-24,48]);
    }
    const point=await evaluate(`(()=>{let c=document.querySelector('#price-${mode}');c.scrollIntoView({block:'center'});let r=c.getBoundingClientRect(), p=window.samplePriceCharts.${mode}.convertToPixel({xAxisIndex:0,yAxisIndex:0},[24.125,10]);return {x:r.x+p[0],y:r.y+p[1]}})()`);
    if(name==='desktop') await cmd('Input.dispatchMouseEvent',{type:'mouseMoved',...point}); else {await cmd('Emulation.setTouchEmulationEnabled',{enabled:true});await cmd('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[point]}); await cmd('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});}
    let tip=await evaluate(`new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(()=>r(document.querySelector('#price-${mode}').innerText))))`);
    if(name==='mobile' && !/22\.35|22\.65|23\.05/.test(tip)) { console.log(`mobile ${mode}: emulated touch missed the narrow target; testing programmatic tooltip`); await evaluate(`window.samplePriceCharts.${mode}.dispatchAction({type:'showTip',seriesIndex:0,dataIndex:192})`); tip=await evaluate(`new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(()=>r(document.querySelector('#price-${mode}').innerText))))`); } else if(name==='mobile') console.log(`mobile ${mode}: emulated tap showed the interval tooltip`);
    assert.ok(/22\.35|22\.65|23\.05/.test(tip) && tip.includes('c/kWh') && tip.includes('Tue 10 Nov 2026') && tip.includes('00:15'),`${name} ${mode}: ${tip}`);
    if(name==='mobile') { await cmd('Emulation.setTouchEmulationEnabled',{enabled:false}); }
    await cmd('Input.dispatchMouseEvent',{type:'mouseMoved',x:1,y:1});
    await evaluate(`window.samplePriceCharts.${mode}.dispatchAction({type:'hideTip'})`);
    await evaluate(`new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))`);
    const rect=await evaluate(`(()=>{let r=document.querySelector('.prices-${mode}').getBoundingClientRect();return {x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height,scale:1}})()`);
    const image=await cmd('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip:rect});
    await writeFile(`${process.env.TEMP}/opencode/spotnav-51b3-${name}-${mode}.png`,Buffer.from(image.data,'base64'));
    {
      await evaluate(`(()=>{let c=window.samplePriceCharts.${mode}; c.setOption({xAxis:{min:-1,max:2,interval:.5},series:[{data:[[-1,0,-5],[.5,1.25,8]]}${mode==='step' ? ",{data:[[-1,-5],[0,-5],[.25,null],[.5,8],[1.25,8]]}" : ''}]});})()`);
      const fixture=await evaluate(`(()=>{let c=window.samplePriceCharts.${mode};return {negative:c.convertToPixel({yAxisIndex:0},-5),zero:c.convertToPixel({yAxisIndex:0},0),data:c.getOption().series[0].data}})()`);
      assert.ok(fixture.negative>fixture.zero,'negative values render below zero'); assert.deepEqual(fixture.data,[[-1,0,-5],[.5,1.25,8]]);
      const gaps=await evaluate(`new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(()=>r([...document.querySelectorAll('#price-${mode} .price-gap')].map(e=>[+e.dataset.start,+e.dataset.end,e.textContent])))))`);
      assert.ok(gaps.some(g=>g[0]===0 && g[1]===.5 && (name==='mobile' || g[2].includes('unavailable'))),'rendered missing interval is hatched; wide gaps labelled');
      const img=await cmd('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip:rect}); await writeFile(`${process.env.TEMP}/opencode/spotnav-51b3-dates-${name}-${mode}-missing.png`,Buffer.from(img.data,'base64'));
    }
    console.log(`${name} ${mode}: interval endpoints, zoom/reset, tooltip and screenshot passed`);
  }
  for (const scenario of ['missing','invalid','long']) {
    const loadedScenario = new Promise(resolve => { const prev=ws.onmessage; ws.onmessage=e=>{prev(e); if(JSON.parse(e.data).method==='Page.loadEventFired'){ws.onmessage=prev;resolve();}}; });
    await cmd('Page.navigate',{url:`http://127.0.0.1:8765/prototype/?comparison=bar&plan=${scenario}`}); await loadedScenario;
    await showTab('overview');
    const result=await evaluate(`(async()=>{await Promise.all([...document.querySelectorAll('wa-button,wa-input,wa-badge')].map(e=>e.updateComplete));const card=document.querySelector('.windows'),dialog=document.querySelector('#plan-dialog'),r=card.getBoundingClientRect();return {width:document.documentElement.scrollWidth,viewport:innerWidth,cardRows:[...card.querySelectorAll('.win-row')].map(e=>e.textContent),dialogRows:[...dialog.querySelectorAll('.plan-row')].map(e=>e.textContent),cardTotal:card.querySelector('.win-footer')?.textContent ?? null,dialogTotal:dialog.querySelector('.plan-total')?.textContent ?? null,note:dialog.querySelector('.projection-note')?.textContent ?? null,text:document.body.innerText,clip:{x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height,scale:1}}})()`);
    assert.ok(result.width<=result.viewport);
    assert.equal(result.cardRows.length,scenario==='long'?8:2);
    assert.equal(result.dialogRows.length,result.cardRows.length);
    assert.doesNotMatch(JSON.stringify(result),/NaN|Infinity/);
    assert.ok(result.cardTotal && result.dialogTotal && result.note);
    if(scenario==='missing') { assert.match(result.cardRows[0],/3\.75 kWh/); assert.match(result.dialogRows[0],/3\.75 kWh/); assert.match(result.cardTotal,/6\.00 kWh/); assert.match(result.dialogTotal,/6\.00 kWh/); assert.match(result.note,/Unknown efficiency/); }
    if(scenario==='invalid') { assert.match(result.dialogRows[0],/Unknown/); assert.match(result.dialogTotal,/Unknown/); assert.match(result.text,/Target feasibility is unknown/); }
    if(scenario==='long') { assert.match(result.cardRows.at(-1),/03:30/); assert.match(result.dialogRows.at(-1),/03:30/); }
    const clip=result.clip;
    const image=await cmd('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip}); await writeFile(`${process.env.TEMP}/opencode/spotnav-51b4a-${name}-${scenario}.png`,Buffer.from(image.data,'base64'));
    await evaluate(`document.querySelector('#open-plan').focus()`);
    await cmd('Input.dispatchKeyEvent',{type:'keyDown',key:' ',code:'Space',windowsVirtualKeyCode:32}); await cmd('Input.dispatchKeyEvent',{type:'keyUp',key:' ',code:'Space',windowsVirtualKeyCode:32});
    assert.equal(await evaluate(`document.querySelector('#plan-dialog').open`),true); assert.equal(await evaluate(`document.activeElement.id`),'close-plan');
    if(scenario==='missing') { const image=await cmd('Page.captureScreenshot',{format:'png'}); await writeFile(`${process.env.TEMP}/opencode/spotnav-51b4a-${name}-missing-modal.png`,Buffer.from(image.data,'base64')); }
    await cmd('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape',windowsVirtualKeyCode:27}); await cmd('Input.dispatchKeyEvent',{type:'keyUp',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});
    assert.equal(await evaluate(`document.activeElement.id`),'open-plan');
  }
  const missingLoaded = new Promise(resolve => { const prev=ws.onmessage; ws.onmessage=e=>{prev(e); if(JSON.parse(e.data).method==='Page.loadEventFired'){ws.onmessage=prev;resolve();}}; });
  await cmd('Page.navigate',{url:'http://127.0.0.1:8765/prototype/?comparison=bar&insights=missing&plan=missing'}); await missingLoaded;
  await showTab('explore');
  const missingInsight=await evaluate(`(async()=>{let el=document.querySelector('.insights');await el.querySelector('wa-details').updateComplete;const r=el.getBoundingClientRect();return {text:el.innerText,width:document.documentElement.scrollWidth,viewport:innerWidth,clip:{x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height,scale:1},disabled:[...document.querySelectorAll('.controls wa-button,.details-body wa-button')].every(e=>e.disabled)}})()`);
  assert.ok(missingInsight.width<=missingInsight.viewport && missingInsight.disabled); assert.match(missingInsight.text,/Unknown/); assert.match(missingInsight.text,/Unavailable/); assert.match(missingInsight.text,/fewer than 7 complete/); assert.doesNotMatch(missingInsight.text,/NaN|Infinity/);
  const missingImage=await cmd('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip:missingInsight.clip}); await writeFile(`${process.env.TEMP}/opencode/spotnav-51c-${name}-missing.png`,Buffer.from(missingImage.data,'base64'));
  assert.equal(await evaluate(`document.querySelectorAll('.price-chart canvas').length`),2);
  await showTab('overview');
  await evaluate(`document.querySelector('#open-plan').focus()`);
  await cmd('Input.dispatchKeyEvent',{type:'keyDown',key:' ',code:'Space',windowsVirtualKeyCode:32}); await cmd('Input.dispatchKeyEvent',{type:'keyUp',key:' ',code:'Space',windowsVirtualKeyCode:32});
  assert.equal(await evaluate(`document.querySelector('#plan-dialog').open`),true);
  await cmd('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape',windowsVirtualKeyCode:27}); await cmd('Input.dispatchKeyEvent',{type:'keyUp',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});
  assert.equal(await evaluate(`document.activeElement.id`),'open-plan');
  await showTab('history');
  const history=await evaluate(`(()=>{const e=document.querySelector('.history'),r=e.getBoundingClientRect();return {text:e.innerText,disabled:e.querySelector('select').disabled,clip:{x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height,scale:1}}})()`);
  assert.match(history.text,/3\/4 intervals · 75%/); assert.match(history.text,/21:45–22:00/); assert.match(history.text,/22:30–22:45 is unknown/); assert.ok(history.disabled);
  const historyImage=await cmd('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip:history.clip}); await writeFile(`${process.env.TEMP}/opencode/spotnav-51d-${name}-history.png`,Buffer.from(historyImage.data,'base64'));
  for (const [daily,expected] of [['waiting','waiting to charge'],['charging','6.0 kW'],['unavailable','Vehicle state unavailable'],['infeasible','falls short'],['partial','01:22:30'],['exception','Above cap'],['stale','Vehicle data stale']]) {
    const loadedDaily=new Promise(resolve=>{const prev=ws.onmessage;ws.onmessage=e=>{prev(e);if(JSON.parse(e.data).method==='Page.loadEventFired'){ws.onmessage=prev;resolve();}};});
    await cmd('Page.navigate',{url:`http://127.0.0.1:8765/prototype/?comparison=bar&state=${daily}`}); await loadedDaily;
    await showTab('overview');
    const result=await evaluate(`(async()=>{await Promise.all([...document.querySelectorAll('wa-button,wa-input,wa-badge')].map(e=>e.updateComplete));const a=document.querySelector('.overview').getBoundingClientRect();return {text:document.body.innerText,width:document.documentElement.scrollWidth,viewport:innerWidth,charts:document.querySelectorAll('.price-chart canvas').length,buttons:[...document.querySelectorAll('.controls wa-button,.details-body wa-button')].every(e=>e.disabled),clip:{x:a.left+scrollX,y:a.top+scrollY,width:a.width,height:a.height,scale:1}}})()`);
    await showTab('settings');
    result.text += ' ' + await evaluate(`document.body.innerText`);
    await showTab('overview');
    assert.ok(result.width<=result.viewport && result.buttons); assert.equal(result.charts,2); assert.ok(result.text.includes(expected),`${daily}: ${expected}`);
    assert.equal(await evaluate(`Boolean(document.querySelector('.alert'))`),['unavailable','infeasible','stale'].includes(daily),`${daily} warning visibility`);
    if(daily==='unavailable') assert.match(result.text,/Sample battery SOC/);
    if(daily==='infeasible') assert.match(result.text,/Low-SOC warning 20%/);
    if(daily==='stale') { assert.match(result.text,/Last sample SOC · stale/); assert.match(result.text,/Evidence is stale/); assert.match(result.text,/Stale SOC is not used in estimates/); assert.ok(await evaluate(`['.windows','#plan-dialog'].every(s=>document.querySelector(s).textContent.includes('stale sample'))`)); }
    if(daily==='exception') { assert.match(result.text,/15:00–15:30/); assert.match(result.text,/40\.0%/); assert.match(result.text,/ABOVE-CAP MINIMUM/); assert.ok(await evaluate(`['.windows','#plan-dialog'].every(s=>document.querySelector(s).textContent.includes('ABOVE-CAP MINIMUM'))`)); }
    if(['charging','unavailable','exception','infeasible','partial','waiting'].includes(daily)) { const img=await cmd('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip:result.clip}); await writeFile(`${process.env.TEMP}/opencode/spotnav-51d-${name}-${daily}.png`,Buffer.from(img.data,'base64')); }
    if(['stale','unavailable','infeasible'].includes(daily)) { for(const selector of ['.overview','.morek']) { await showTab(selector === '.overview' ? 'overview' : 'settings'); const clip=await evaluate(`(()=>{let r=document.querySelector('${selector}').getBoundingClientRect();return {x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height,scale:1}})()`); const img=await cmd('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip}); await writeFile(`${process.env.TEMP}/opencode/spotnav-51e-${name}-${daily}-${selector === '.overview' ? 'vehicle' : 'evidence'}.png`,Buffer.from(img.data,'base64')); } }
    await showTab('overview');
    await evaluate(`document.querySelector('#open-plan').focus()`); await cmd('Input.dispatchKeyEvent',{type:'keyDown',key:' ',code:'Space',windowsVirtualKeyCode:32}); await cmd('Input.dispatchKeyEvent',{type:'keyUp',key:' ',code:'Space',windowsVirtualKeyCode:32});
    assert.equal(await evaluate(`document.querySelector('#plan-dialog').open`),true); await cmd('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape',windowsVirtualKeyCode:27}); await cmd('Input.dispatchKeyEvent',{type:'keyUp',key:'Escape',code:'Escape',windowsVirtualKeyCode:27}); assert.equal(await evaluate(`document.activeElement.id`),'open-plan');
  }
  const selectedLoad=new Promise(resolve=>{const prev=ws.onmessage;ws.onmessage=e=>{prev(e);if(JSON.parse(e.data).method==='Page.loadEventFired'){ws.onmessage=prev;resolve();}};});
  await evaluate(`(()=>{const e=document.querySelector('#sample-state');e.value='charging';e.dispatchEvent(new Event('change',{bubbles:true}))})()`); await selectedLoad;
  assert.equal(await evaluate(`document.querySelector('#sample-state').value`),'charging'); assert.match(await evaluate(`document.querySelector('.overview').innerText`),/6\.0 kW/);
  console.log(`${name}: full page and both cards, no horizontal overflow`);
}
assert.deepEqual(errors,[]); assert.ok(urls.every(u=>u.startsWith('http://127.0.0.1:8765/')||u.startsWith('data:')),'unexpected network request'); console.log(`${urls.length} local/data requests`); ws.close();
