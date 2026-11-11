import * as echarts from 'echarts/core';
import { CustomChart, LineChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, MarkLineComponent, MarkAreaComponent, DataZoomComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import { prices, windows, time, day, now, deadline, horizon, stepSegments, stepPoints, cap } from './sample.js';

echarts.use([CustomChart, LineChart, GridComponent, TooltipComponent, MarkLineComponent, MarkAreaComponent, DataZoomComponent, CanvasRenderer]);
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
  priceChart.setOption({ animation: false, grid: { left: 48, right: 20, top: 48, bottom: 82 },
    tooltip: { trigger: 'item', confine: true, hideDelay: 0, transitionDuration: 0, backgroundColor: '#233942', borderColor: '#5b7b7a', textStyle: { color: '#f0faf8' }, formatter: p => `${day(p.value[0])} ${time(p.value[0])}–${day(p.value[1])} ${time(p.value[1])}<br>${p.value[2].toFixed(2)} c/kWh · fictional sample` },
    xAxis: { ...axis, type: 'value', min: horizon[0], max: horizon[1], interval: 12, axisLabel: { ...axis.axisLabel, hideOverlap: true, formatter: h => h % 24 === 0 ? `${day(h)}\n00:00` : time(h) } },
    yAxis: { ...axis, type: 'value', name: 'c/kWh', nameTextStyle: { color: '#bed0d5', align: 'left' }, min: value => Math.min(0, Math.floor(value.min / 10) * 10), max: value => Math.ceil(value.max / 10) * 10 },
    dataZoom: [{ type: 'inside', xAxisIndex: 0, filterMode: 'weakFilter', zoomOnMouseWheel: true, moveOnMouseMove: true, moveOnMouseWheel: false, preventDefaultMouseMove: false }, { type: 'slider', xAxisIndex: 0, filterMode: 'weakFilter', height: 28, bottom: 12, borderColor: '#4b6871', backgroundColor: '#142630', fillerColor: 'rgba(91,205,180,.22)', textStyle: { color: '#d0e1df' }, showDetail: false }],
    series: [{ type: 'custom', clip: true, name: 'Sample price', renderItem, encode: { x: [0, 1], y: 2 }, data: stepSegments(prices).map(([s, e]) => [s[0], e[0], s[1]]) },
    ...(mode === 'step' ? [{ type: 'line', name: 'Stepped price', data: stepPoints(prices), showSymbol: false, connectNulls: false, silent: true, z: 1, lineStyle: { width: 2.5, color: '#f0ba60' }, areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{offset: 0, color: 'rgba(239,136,69,.34)'}, {offset: 1, color: 'rgba(239,136,69,.015)'}]) } }] : []),
    { type: 'line', symbol: 'none', data: [[-24, 0], [48, 0]], lineStyle: { opacity: 0 }, tooltip: { show: false },
      markArea: { silent: true, label: { show: false }, data: [...windows.map(w => [{ xAxis: w.start, itemStyle: { color: 'rgba(118,180,255,.22)' } }, { xAxis: w.end }])] },
      markLine: { silent: true, symbol: 'none', label: { color: '#e5d2ac', fontSize: 11 }, lineStyle: { color: '#d4a969', type: 'dashed' }, data: [{ yAxis: cap, label: { formatter: `Cap ${cap} c/kWh`, position: 'insideEndTop' } }, { xAxis: now, label: { formatter: 'Now', position: 'insideStartTop' }, lineStyle: { color: '#92baf9' } }, { xAxis: deadline, label: { formatter: 'Ready by', position: 'insideStartTop' }, lineStyle: { color: '#e1c390' } }] } }] });
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
      data: [[21.5, 0], [21.75, 0], [22, 6], [22.25, 6], [22.5, null], [22.75, 6], [23, 0], [23.25, 0], [23.5, 0]] }] });
  const resize = new ResizeObserver(() => { Object.values(priceCharts).forEach(chart => chart.resize()); powerChart.resize(); });
  for (const mode of ['bar', 'step']) resize.observe(document.getElementById(`price-${mode}`)); resize.observe(document.getElementById('power-chart'));
}
