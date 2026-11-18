import * as echarts from 'echarts/core';
import { CustomChart, LineChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, MarkLineComponent, MarkAreaComponent, MarkPointComponent, DataZoomComponent, VisualMapComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import { escapeText } from './text.js';
import { priceText } from './price-format.js';
import { priceBand, bandColor, priceAxisExtent } from './price-bands.js';

echarts.use([CustomChart, LineChart, GridComponent, TooltipComponent, MarkLineComponent, MarkAreaComponent, MarkPointComponent, VisualMapComponent, DataZoomComponent, CanvasRenderer]);
const axis = { axisLine: { lineStyle: { color: '#4a6286' } }, axisLabel: { color: '#aebfd8', fontSize: 12 }, splitLine: { lineStyle: { color: '#1b3150' } } };
export function mountCharts(root, data, format, modes) {
  let { prices, windows, tracks = null, now, deadline, horizon, cap, readings, sentHistory, historyAxis, unit = 'c/kWh', viewKey } = data;
  let { time, date: sampleDate, days: sampleDays, priceGaps, stepSegments, stepPoints, snapRange, initialRange, timeTicks, tickLabel } = format;
  time = format.chartTime || time;
  let tooltipDate = format.tooltipDate || sampleDate;
  const controller = new AbortController();
  const signal = controller.signal;
  const priceCharts = {};
  const refreshers = [];
  for (const mode of modes) {
  const priceChart = echarts.init(root.querySelector(`#price-${mode}`));
  priceCharts[mode] = priceChart;
  const renderItem = (params, api) => {
    const s = api.coord([api.value(0), api.value(2)]), e = api.coord([api.value(1), api.value(2)]), zero = api.coord([api.value(0), 0]);
    const rect = echarts.graphic.clipRectByRect({ x: s[0], y: Math.min(s[1], zero[1]), width: Math.max(1, e[0] - s[0]), height: Math.max(2, Math.abs(zero[1] - s[1])) }, params.coordSys);
    if (!rect) return null;
    const color = bandColor(api.value(2), unit);
    if (mode === 'bar') return { type: 'group', children: [{ type: 'rect', shape: rect, style: { fill: color } }] };
    // Stepped area: translucent fill to the zero baseline plus a solid top edge, both coloured by this interval's absolute value.
    const top = echarts.graphic.clipPointsByRect([[s[0], s[1]], [e[0], e[1]]], params.coordSys);
    const children = [{ type: 'rect', shape: rect, style: { fill: color, opacity: .2 } }];
    if (top.length === 2) children.push({ type: 'line', shape: { x1: top[0][0], y1: top[0][1], x2: top[1][0], y2: top[1][1] }, style: { stroke: color, lineWidth: 3 }, silent: true });
    const prev = api.value(3);
    if (Number.isFinite(prev) && s[0] >= params.coordSys.x && s[0] <= params.coordSys.x + params.coordSys.width) { const from = api.coord([api.value(0), prev]), joint = echarts.graphic.clipPointsByRect([[s[0], from[1]], [s[0], s[1]]], params.coordSys); if (joint.length === 2) children.push({ type: 'line', shape: { x1: joint[0][0], y1: joint[0][1], x2: joint[1][0], y2: joint[1][1] }, style: { stroke: color, lineWidth: 3 }, silent: true }); }
    return { type: 'group', children };
  };
  const stepData = () => { const seg = stepSegments(prices); return seg.map(([s, e], i) => [s[0], e[0], s[1], i && seg[i - 1][1][0] === s[0] ? seg[i - 1][0][1] : null]); };
  const setPriceOption = (initial) => priceChart.setOption({ animation: false, grid: { left: 48, right: 20, top: 82, bottom: 92, show: true, backgroundColor: '#0b1626', borderWidth: 0 },
    tooltip: { trigger: 'item', confine: true, hideDelay: 0, transitionDuration: 0, backgroundColor: '#14233a', borderColor: '#4a6286', textStyle: { color: '#f4f8ff' }, formatter: p => !Array.isArray(p.value) || p.value.length < 3 || !p.value.slice(0, 3).every(Number.isFinite) ? '' : `${escapeText(tooltipDate(p.value[0]))} ${escapeText(time(p.value[0]))}–${escapeText(tooltipDate(p.value[1]))} ${escapeText(time(p.value[1]))}<br>${priceText(p.value[2])} ${escapeText(unit)}${priceBand(p.value[2], unit) ? ` · ${priceBand(p.value[2], unit).label}` : ''}${windows.filter(w => w.start < p.value[1] && w.end > p.value[0]).map(w => `<br>Proposal: ${escapeText(tooltipDate(w.start))} ${escapeText(time(w.start))}–${escapeText(time(w.end))}`).join('')}` },
    xAxis: { ...axis, type: 'value', min: horizon[0], max: horizon[1], axisLabel: { show: false }, axisTick: { show: false }, splitLine: { show: false } },
    yAxis: { ...axis, axisLabel: {...axis.axisLabel, formatter: priceText}, type: 'value', name: unit, nameTextStyle: { color: '#aebfd8', align: 'left' }, ...priceAxisExtent(prices, unit, cap) },
    dataZoom: [{ type: 'inside', xAxisIndex: 0, startValue: initial[0], endValue: initial[1], filterMode: 'weakFilter', zoomOnMouseWheel: true, moveOnMouseMove: true, moveOnMouseWheel: false, preventDefaultMouseMove: false }, { type: 'slider', xAxisIndex: 0, startValue: initial[0], endValue: initial[1], filterMode: 'weakFilter', height: 28, bottom: 12, borderColor: '#4b6871', backgroundColor: '#142630', fillerColor: 'rgba(91,205,180,.22)', textStyle: { color: '#d0e1df' }, showDetail: false }],
    series: [{ type: 'custom', clip: true, name: 'Sample price', renderItem, encode: { x: [0, 1], y: 2 }, data: stepData() },
    { type: 'line', symbol: 'none', data: [[horizon[0], 0], [horizon[1], 0]], lineStyle: { opacity: 0 }, tooltip: { show: false },
      markArea: { silent: true, label: { show: false }, data: [[{xAxis:horizon[0], itemStyle:{color:'#000000'}},{xAxis:now}]] },
      markPoint: { silent: true, symbol: 'pin', symbolSize: 54, label: { color: '#fff', fontSize: 11, fontWeight: 'bold', formatter: p => priceText(p.value) }, data: [(() => { const p = prices.reduce((a,b)=>a.cents<b.cents?a:b); return { name: 'LOW', coord: [(p.start+p.end)/2,p.cents], value:p.cents, itemStyle:{color:bandColor(p.cents, unit)} }; })(), (() => { const p = prices.reduce((a,b)=>a.cents>b.cents?a:b); return { name: 'HIGH', coord: [(p.start+p.end)/2,p.cents], value:p.cents, itemStyle:{color:bandColor(p.cents, unit)} }; })()] },
      markLine: { silent: true, symbol: 'none', label: { color: '#e5d2ac', fontSize: 11 }, lineStyle: { color: '#d4a969', type: 'dashed' }, data: [...(Number.isFinite(cap) ? [{ yAxis: cap, label: { formatter: `Cap ${priceText(cap)} ${unit}`, position: 'insideEndTop' } }] : []), { xAxis: now, label: { formatter: 'Now', position: 'insideStartTop', color:'#8fc5ff' }, lineStyle: { color: '#398dff', type:'solid', width:2 } }, ...(Number.isFinite(deadline) ? [{ xAxis: deadline, label: { formatter: 'Ready by', position: 'insideStartTop' }, lineStyle: { color: '#e1c390' } }] : [])] } }] });
  setPriceOption(initialRange(now));
  const labels = document.createElement('div');
  labels.className = 'time-ticks';
  priceChart.getDom().appendChild(labels);
  const days = document.createElement('div');
  days.className = 'day-overlay';
  days.setAttribute('aria-hidden','true');
  priceChart.getDom().appendChild(days);
  const drawTicks = () => {
    const z = priceChart.getOption().dataZoom[0];
    const width = priceChart.getWidth() - 68;
    labels.replaceChildren(...timeTicks(z.startValue, z.endValue, width).map(h => {
      const el = document.createElement('span');
      el.dataset.hour = h;
      el.style.left = `${priceChart.convertToPixel({xAxisIndex:0}, h)}px`;
      el.textContent = tickLabel ? tickLabel(h) : h % 24 === 0 ? `${time(h)}\n${sampleDate(h)}` : time(h);
      return el;
    }));
    const pixel = h => priceChart.convertToPixel({xAxisIndex:0}, h);
    const elements = [];
    for (const w of windows) {
      const start = Math.max(w.start,z.startValue), end = Math.min(w.end,z.endValue);
      if (end <= start) continue;
      for (const cls of ['proposal-gradient','proposal-track']) {
        const el = document.createElement('div'); el.className = cls;
        el.dataset.start = start; el.dataset.end = end;
        el.style.left = `${pixel(start)}px`; el.style.width = `${pixel(end)-pixel(start)}px`;
        elements.push(el);
      }
    }
    for (const segment of sampleDays(z.startValue,z.endValue)) {
      const left = pixel(segment.start), right = pixel(segment.end), span = right-left;
      const cell = document.createElement('div');
      cell.className = 'day-cell'; cell.dataset.start = segment.start; cell.dataset.end = segment.end;
      cell.style.left = `${left}px`; cell.style.width = `${span}px`;
      cell.textContent = span >= 140 ? segment.label : span >= 57 ? sampleDate(segment.midnight) : '';
      elements.push(cell);
      if (segment.midnight > z.startValue && segment.midnight < z.endValue) {
        const line = document.createElement('div'); line.className = 'midnight-line';
        line.dataset.hour = segment.midnight; line.style.left = `${pixel(segment.midnight)}px`;
        elements.push(line);
      }
    }
    const available = priceChart.getOption().series[0].data.map(p => ({start:p[0],end:p[1]}));
    for (const [start,end] of priceGaps(z.startValue,z.endValue,available)) {
      const gap = document.createElement('div'); gap.className = 'price-gap';
      gap.dataset.start = start; gap.dataset.end = end;
      gap.style.left = `${pixel(start)}px`; gap.style.width = `${pixel(end)-pixel(start)}px`;
      if (pixel(end)-pixel(start) >= 95) gap.textContent = 'Price unavailable';
      elements.push(gap);
    }
    days.replaceChildren(...elements);
    drawLanes(z);
  };
  // Evidence tracks (7.3b): DOM lanes below the chart positioned with the chart's own axis conversion, so zoom, pan and
  // resize move them with the price intervals. They add nothing to the chart's series, grid or y extent.
  const laneRoot = root.querySelector(`[data-track-lanes="${mode}"]`);
  const drawLanes = z => {
    if (!laneRoot) return;
    const px = h => priceChart.convertToPixel({xAxisIndex:0}, h);
    const left = px(z.startValue), width = px(z.endValue) - left;
    if (!tracks?.lanes?.length || !Number.isFinite(left) || !(width > 0)) { laneRoot.replaceChildren(); return; }
    laneRoot.replaceChildren(...tracks.lanes.map(lane => {
      const el = document.createElement('div'); el.className = 'track-lane'; el.dataset.lane = lane.key;
      const caption = document.createElement('div'); caption.className = 'track-caption'; caption.textContent = lane.caption;
      if (lane.note) { const note = document.createElement('small'); note.textContent = lane.note; caption.append(note); }
      const bar = document.createElement('div'); bar.className = 'track-bar'; bar.style.marginLeft = `${left}px`; bar.style.width = `${width}px`;
      for (const s of lane.segments) {
        const a = Math.max(s.start, z.startValue), b = Math.min(s.end, z.endValue);
        if (!(b > a)) continue;
        const from = px(a), span = px(b) - from;
        const seg = document.createElement('div');
        seg.className = `track-seg seg-${s.kind}${s.stale ? ' seg-stale' : ''}${s.openStart ? ' edge-open-start' : ''}${s.openEnd ? ' edge-open-end' : ''}`;
        seg.dataset.kind = s.kind; seg.dataset.start = s.start; seg.dataset.end = s.end;
        if (s.version != null) seg.dataset.version = s.version;
        seg.style.left = `${from - left}px`; seg.style.width = `${span}px`;
        seg.title = s.text || ''; 
        if (s.label && span >= 64) seg.textContent = s.label;
        bar.append(seg);
      }
      el.append(caption, bar);
      return el;
    }));
  };
  let correcting = false;
  const updateView = () => {
    if (correcting) return;
    const z = priceChart.getOption().dataZoom[0];
    const [start,end] = snapRange(z.startValue, z.endValue);
    correcting = true;
    if (Math.abs(start-z.startValue)>1e-7 || Math.abs(end-z.endValue)>1e-7) priceChart.dispatchAction({ type:'dataZoom', startValue:start, endValue:end });
    drawTicks();
    correcting = false;
  };
  priceChart.on('datazoom', updateView);
  drawTicks();
  priceChart.on('finished', drawTicks);
  // A routine refresh keeps the user's range; only an explicit navigation (a new `viewKey`) sets a new one.
  refreshers.push((navigated) => {
    const z=priceChart.getOption().dataZoom[0];
    const a=Math.max(horizon[0],z.startValue), b=Math.min(horizon[1],z.endValue);
    setPriceOption(!navigated && a<b ? snapRange(a,b) : initialRange(now));
    drawTicks();
  });
  // Handle two-finger scaling independently of narrow canvas targets. Keep the
  // initial viewport as the gesture baseline so quantization cannot accumulate drift.
  let pinch = null;
  const distance = touches => Math.hypot(touches[0].clientX-touches[1].clientX, touches[0].clientY-touches[1].clientY);
  const node = priceChart.getDom();
  // For source-boundary navigation the default small ECharts wheel step can
  // snap straight back to the previous range on coarse hourly data. Apply a
  // larger anchored step before snapping, without changing interval geometry.
  node.addEventListener('wheel', e => {
    if (!format.chartTime || !e.deltaY) return;
    const z=priceChart.getOption().dataZoom[0], rect=node.getBoundingClientRect();
    const anchor=priceChart.convertFromPixel({xAxisIndex:0},e.clientX-rect.left);
    if (!Number.isFinite(anchor)) return;
    const factor=e.deltaY<0 ? 0.55 : 1/0.55;
    const [start,end]=snapRange(anchor+(z.startValue-anchor)*factor,anchor+(z.endValue-anchor)*factor);
    priceChart.dispatchAction({type:'dataZoom',startValue:start,endValue:end});
    e.preventDefault();e.stopImmediatePropagation();
  }, {capture:true,passive:false,signal});
  node.addEventListener('touchstart', e => {
    if (e.touches.length !== 2) return;
    const z = priceChart.getOption().dataZoom[0], rect = node.getBoundingClientRect();
    const center = (e.touches[0].clientX+e.touches[1].clientX)/2-rect.left;
    pinch = { distance: distance(e.touches), start:z.startValue, end:z.endValue, anchor:priceChart.convertFromPixel({xAxisIndex:0},center) };
    e.preventDefault(); e.stopImmediatePropagation();
  }, {capture:true,passive:false,signal});
  node.addEventListener('touchmove', e => {
    if (!pinch || e.touches.length !== 2) return;
    const scale = distance(e.touches)/pinch.distance;
    if (Number.isFinite(scale) && scale > 0) {
      const a = pinch.anchor + (pinch.start-pinch.anchor)/scale, b = pinch.anchor + (pinch.end-pinch.anchor)/scale;
      const [start,end] = snapRange(a,b);
      priceChart.dispatchAction({type:'dataZoom', startValue:start, endValue:end});
    }
    e.preventDefault(); e.stopImmediatePropagation();
  }, {capture:true,passive:false,signal});
  node.addEventListener('touchend', e => { if (pinch && e.touches.length < 2) { pinch = null; e.preventDefault(); e.stopImmediatePropagation(); } }, {capture:true,passive:false,signal});
  // A tap selects by exact x interval rather than requiring a narrow bar/line hit.
  let touchStart;
  priceChart.getDom().addEventListener('touchstart', e => { if (e.touches.length === 1) touchStart = [e.touches[0].clientX,e.touches[0].clientY]; else touchStart = null; }, {passive:true,signal});
  priceChart.getDom().addEventListener('touchend', e => {
    if (!touchStart || e.changedTouches.length !== 1) return;
    const t = e.changedTouches[0], rect = priceChart.getDom().getBoundingClientRect();
    if (Math.hypot(t.clientX-touchStart[0],t.clientY-touchStart[1]) > 8 || t.clientY-rect.top < 82 || t.clientY-rect.top > rect.height-92) return;
    const h = priceChart.convertFromPixel({xAxisIndex:0}, t.clientX-rect.left);
    const index = prices.findIndex(p => p.start <= h && h < p.end);
    if (index >= 0) priceChart.dispatchAction({type:'showTip',seriesIndex:0,dataIndex:index});
    else priceChart.dispatchAction({type:'hideTip'});
    touchStart = null;
  }, {passive:true,signal});
  root.querySelector(`[data-reset="${mode}"]`).addEventListener('click', () => priceChart.dispatchAction({ type: 'dataZoom', start: 0, end: 100 }), {signal});
  root.querySelector(`[data-zoom="${mode}"]`).addEventListener('click', () => { const z = priceChart.getOption().dataZoom[0]; const middle = (z.start + z.end) / 2; const range = (z.end - z.start) / 4; priceChart.dispatchAction({ type: 'dataZoom', start: Math.max(0, middle - range), end: Math.min(100, middle + range) }); }, {signal});
  }
  const powerChart = readings && sentHistory ? echarts.init(root.querySelector('#power-chart')) : null;
  if (powerChart) {
  powerChart.setOption({ animation: false, grid: { left: 45, right: 20, top: 30, bottom: 34 },
    tooltip: { trigger: 'axis', confine: true, formatter: items => { const p = items[0]; return `${escapeText(time(p.value[0]))}<br>${p.value[1] == null ? 'Unavailable' : `${p.value[1].toFixed(1)} kW`}`; } },
    xAxis: { ...axis, type: 'value', min: readings[0].time, max: readings.at(-1).time, ...(Number.isFinite(historyAxis?.interval) && historyAxis.interval > 0 ? {interval:historyAxis.interval} : {}), axisLabel: { ...axis.axisLabel, formatter: time } },
    yAxis: { ...axis, type: 'value', name: 'kW', min: 0, ...(Number.isFinite(historyAxis?.max) && historyAxis.max > 0 ? {max:historyAxis.max} : {}), nameTextStyle: { color: '#aebfd8', align: 'left' } },
    series: [{ type: 'line', step: 'end', connectNulls: false, symbol: 'circle', symbolSize: 5, lineStyle: { color: '#34e8b0', width: 2 }, itemStyle: { color: '#34e8b0' },
      areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: 'rgba(52,232,176,.4)' }, { offset: 1, color: 'rgba(52,232,176,.04)' }]) },
      markArea:{silent:true,label:{show:false},itemStyle:{color:'rgba(112,153,222,.15)'},data:[[{xAxis:sentHistory.start},{xAxis:sentHistory.end}]]},
      data: readings.map(r=>[r.time,r.kw]) }] });
  }
  const resize = new ResizeObserver(() => { Object.values(priceCharts).forEach(chart => chart.resize()); powerChart?.resize(); });
  for (const mode of modes) resize.observe(root.querySelector(`#price-${mode}`));
  if (powerChart) resize.observe(root.querySelector('#power-chart'));
  // A chart initialised or updated inside a hidden tab measured 0x0; resize() re-measures it (zoom lives in the chart's option and is kept).
  return { priceCharts, resize() { Object.values(priceCharts).forEach(chart => chart.resize()); powerChart?.resize(); }, update(next, nextFormat) {
    const navigated=next.viewKey!==viewKey;
    ({prices,windows,tracks=null,now,deadline,horizon,cap,unit='c/kWh',viewKey}=next);
    ({time,date:sampleDate,days:sampleDays,priceGaps,stepSegments,stepPoints,snapRange,initialRange,timeTicks,tickLabel}=nextFormat);
    time=nextFormat.chartTime || time;
    tooltipDate=nextFormat.tooltipDate || sampleDate;
    refreshers.forEach(refresh=>refresh(navigated));
  }, dispose() { controller.abort(); resize.disconnect(); Object.values(priceCharts).forEach(chart => chart.dispose()); powerChart?.dispose(); } };
}
