import * as echarts from 'echarts/core';
import { CustomChart, LineChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, MarkLineComponent, MarkAreaComponent, MarkPointComponent, DataZoomComponent, VisualMapComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import { prices, windows, time, sampleDate, sampleDays, priceGaps, now, deadline, horizon, stepSegments, stepPoints, cap, snapRange, initialRange, timeTicks } from './sample.js';
import { readings, sentHistory } from './daily-sample.js';

echarts.use([CustomChart, LineChart, GridComponent, TooltipComponent, MarkLineComponent, MarkAreaComponent, MarkPointComponent, VisualMapComponent, DataZoomComponent, CanvasRenderer]);
const axis = { axisLine: { lineStyle: { color: '#536b76' } }, axisLabel: { color: '#bed0d5', fontSize: 12 }, splitLine: { lineStyle: { color: '#34444d' } } };
export function mountCharts() {
  const priceCharts = {};
  for (const mode of ['bar', 'step']) {
  const priceChart = echarts.init(document.getElementById(`price-${mode}`));
  priceCharts[mode] = priceChart;
  const renderItem = (params, api) => {
    const s = api.coord([api.value(0), api.value(2)]), e = api.coord([api.value(1), api.value(2)]), zero = api.coord([api.value(0), 0]);
    const rect = echarts.graphic.clipRectByRect({ x: s[0], y: Math.min(s[1], zero[1]), width: Math.max(1, e[0] - s[0]), height: Math.max(2, Math.abs(zero[1] - s[1])) }, params.coordSys);
    if (!rect) return null;
    const color = api.value(2) <= 30 ? '#37c48f' : api.value(2) <= 45 ? '#e9b34e' : api.value(2) <= 60 ? '#ef8845' : '#ec6266';
    const fill = mode === 'bar' ? color : 'rgba(0,0,0,0)';
    const children = [{ type: 'rect', shape: rect, style: { fill } }];
    return { type: 'group', children };
  };
  const initial = initialRange(now);
  priceChart.setOption({ animation: false, grid: { left: 48, right: 20, top: 82, bottom: 92, show: true, backgroundColor: '#101f30', borderWidth: 0 },
    tooltip: { trigger: 'item', confine: true, hideDelay: 0, transitionDuration: 0, backgroundColor: '#233942', borderColor: '#5b7b7a', textStyle: { color: '#f0faf8' }, formatter: p => `${sampleDate(p.value[0])} 2026 ${time(p.value[0])}–${sampleDate(p.value[1])} 2026 ${time(p.value[1])}<br>${p.value[2].toFixed(2)} c/kWh · fictional sample${windows.filter(w => w.start < p.value[1] && w.end > p.value[0]).map(w => `<br>Proposal: ${sampleDate(w.start)} 2026 ${time(w.start)}–${time(w.end)}`).join('')}` },
    xAxis: { ...axis, type: 'value', min: horizon[0], max: horizon[1], axisLabel: { show: false }, axisTick: { show: false }, splitLine: { show: false } },
    yAxis: { ...axis, type: 'value', name: 'c/kWh', nameTextStyle: { color: '#bed0d5', align: 'left' }, interval: 10, min: value => Math.min(0, Math.floor(value.min / 10) * 10), max: value => Math.ceil(value.max / 10) * 10 },
    dataZoom: [{ type: 'inside', xAxisIndex: 0, startValue: initial[0], endValue: initial[1], filterMode: 'weakFilter', zoomOnMouseWheel: true, moveOnMouseMove: true, moveOnMouseWheel: false, preventDefaultMouseMove: false }, { type: 'slider', xAxisIndex: 0, startValue: initial[0], endValue: initial[1], filterMode: 'weakFilter', height: 28, bottom: 12, borderColor: '#4b6871', backgroundColor: '#142630', fillerColor: 'rgba(91,205,180,.22)', textStyle: { color: '#d0e1df' }, showDetail: false }],
    ...(mode === 'step' ? { visualMap: { show: false, type: 'piecewise', seriesIndex: 1, dimension: 1, pieces: [{lte:30,color:'#37c48f'},{gt:30,lte:45,color:'#e9b34e'},{gt:45,lte:60,color:'#ef8845'},{gt:60,color:'#ec6266'}] } } : {}),
    series: [{ type: 'custom', clip: true, name: 'Sample price', renderItem, encode: { x: [0, 1], y: 2 }, data: stepSegments(prices).map(([s, e]) => [s[0], e[0], s[1]]) },
    ...(mode === 'step' ? [{ type: 'line', name: 'Stepped price', data: stepPoints(prices), showSymbol: false, connectNulls: false, silent: true, z: 2, lineStyle: { width: 3 }, areaStyle: { opacity: .18 } }] : []),
    { type: 'line', symbol: 'none', data: [[-24, 0], [48, 0]], lineStyle: { opacity: 0 }, tooltip: { show: false },
      markArea: { silent: true, label: { show: false }, data: [[{xAxis:horizon[0], itemStyle:{color:'#000000'}},{xAxis:now}]] },
      markPoint: { symbol: 'pin', symbolSize: 54, label: { color: '#fff', fontSize: 11, fontWeight: 'bold', formatter: p => p.value.toFixed(2) }, data: [(() => { const p = prices.reduce((a,b)=>a.cents<b.cents?a:b); return { name: 'LOW', coord: [(p.start+p.end)/2,p.cents], value:p.cents, itemStyle:{color:'#16825d'} }; })(), (() => { const p = prices.reduce((a,b)=>a.cents>b.cents?a:b); return { name: 'HIGH', coord: [(p.start+p.end)/2,p.cents], value:p.cents, itemStyle:{color:'#b93f50'} }; })()] },
      markLine: { silent: true, symbol: 'none', label: { color: '#e5d2ac', fontSize: 11 }, lineStyle: { color: '#d4a969', type: 'dashed' }, data: [{ yAxis: cap, label: { formatter: `Cap ${cap} c/kWh`, position: 'insideEndTop' } }, { xAxis: now, label: { formatter: 'Now', position: 'insideStartTop', color:'#8fc5ff' }, lineStyle: { color: '#398dff', type:'solid', width:2 } }, { xAxis: deadline, label: { formatter: 'Ready by', position: 'insideStartTop' }, lineStyle: { color: '#e1c390' } }] } }] });
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
      el.textContent = h % 24 === 0 ? `${time(h)}\n${sampleDate(h)}` : time(h);
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
  // Handle two-finger scaling independently of narrow canvas targets. Keep the
  // initial viewport as the gesture baseline so quantization cannot accumulate drift.
  let pinch = null;
  const distance = touches => Math.hypot(touches[0].clientX-touches[1].clientX, touches[0].clientY-touches[1].clientY);
  const node = priceChart.getDom();
  node.addEventListener('touchstart', e => {
    if (e.touches.length !== 2) return;
    const z = priceChart.getOption().dataZoom[0], rect = node.getBoundingClientRect();
    const center = (e.touches[0].clientX+e.touches[1].clientX)/2-rect.left;
    pinch = { distance: distance(e.touches), start:z.startValue, end:z.endValue, anchor:priceChart.convertFromPixel({xAxisIndex:0},center) };
    e.preventDefault(); e.stopImmediatePropagation();
  }, {capture:true,passive:false});
  node.addEventListener('touchmove', e => {
    if (!pinch || e.touches.length !== 2) return;
    const scale = distance(e.touches)/pinch.distance;
    if (Number.isFinite(scale) && scale > 0) {
      const a = pinch.anchor + (pinch.start-pinch.anchor)/scale, b = pinch.anchor + (pinch.end-pinch.anchor)/scale;
      const [start,end] = snapRange(a,b);
      priceChart.dispatchAction({type:'dataZoom', startValue:start, endValue:end});
    }
    e.preventDefault(); e.stopImmediatePropagation();
  }, {capture:true,passive:false});
  node.addEventListener('touchend', e => { if (pinch && e.touches.length < 2) { pinch = null; e.preventDefault(); e.stopImmediatePropagation(); } }, {capture:true,passive:false});
  // A tap selects by exact x interval rather than requiring a narrow bar/line hit.
  let touchStart;
  priceChart.getDom().addEventListener('touchstart', e => { if (e.touches.length === 1) touchStart = [e.touches[0].clientX,e.touches[0].clientY]; else touchStart = null; }, {passive:true});
  priceChart.getDom().addEventListener('touchend', e => {
    if (!touchStart || e.changedTouches.length !== 1) return;
    const t = e.changedTouches[0], rect = priceChart.getDom().getBoundingClientRect();
    if (Math.hypot(t.clientX-touchStart[0],t.clientY-touchStart[1]) > 8 || t.clientY-rect.top < 82 || t.clientY-rect.top > rect.height-92) return;
    const h = priceChart.convertFromPixel({xAxisIndex:0}, t.clientX-rect.left);
    const index = prices.findIndex(p => p.start <= h && h < p.end);
    if (index >= 0) priceChart.dispatchAction({type:'showTip',seriesIndex:0,dataIndex:index});
    else priceChart.dispatchAction({type:'hideTip'});
    touchStart = null;
  }, {passive:true});
  document.querySelector(`[data-reset="${mode}"]`).addEventListener('click', () => priceChart.dispatchAction({ type: 'dataZoom', start: 0, end: 100 }));
  document.querySelector(`[data-zoom="${mode}"]`).addEventListener('click', () => { const z = priceChart.getOption().dataZoom[0]; const middle = (z.start + z.end) / 2; const range = (z.end - z.start) / 4; priceChart.dispatchAction({ type: 'dataZoom', start: Math.max(0, middle - range), end: Math.min(100, middle + range) }); });
  }
  window.samplePriceCharts = priceCharts;
  const powerChart = echarts.init(document.getElementById('power-chart'));
  powerChart.setOption({ animation: false, grid: { left: 45, right: 20, top: 30, bottom: 34 },
    tooltip: { trigger: 'axis', confine: true, formatter: items => { const p = items[0]; return `${time(p.value[0])}<br>${p.value[1] == null ? 'Unavailable' : `${p.value[1].toFixed(1)} kW`} · sample`; } },
    xAxis: { ...axis, type: 'value', min: 21.5, max: 23.5, interval: 0.5, axisLabel: { ...axis.axisLabel, formatter: time } },
    yAxis: { ...axis, type: 'value', name: 'kW', max: 8, min: 0, nameTextStyle: { color: '#bed0d5', align: 'left' } },
    series: [{ type: 'line', step: 'end', connectNulls: false, symbol: 'circle', symbolSize: 5, lineStyle: { color: '#188c79', width: 2 }, itemStyle: { color: '#188c79' },
      areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: 'rgba(31,165,137,.45)' }, { offset: 1, color: 'rgba(31,165,137,.04)' }]) },
      markArea:{silent:true,label:{show:false},itemStyle:{color:'rgba(112,153,222,.15)'},data:[[{xAxis:sentHistory.start},{xAxis:sentHistory.end}]]},
      data: readings.map(r=>[r.time,r.kw]) }] });
  const resize = new ResizeObserver(() => { Object.values(priceCharts).forEach(chart => chart.resize()); powerChart.resize(); });
  for (const mode of ['bar', 'step']) resize.observe(document.getElementById(`price-${mode}`)); resize.observe(document.getElementById('power-chart'));
}
