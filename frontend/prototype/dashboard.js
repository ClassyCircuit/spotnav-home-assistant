import { mountDashboard } from '../shared-dashboard/dashboard.js';
import { createSampleAdapter } from './sample-adapter.js';

let dashboard;
const adapter = createSampleAdapter(next => dashboard?.update(next));
dashboard = mountDashboard(document.querySelector('#app'), adapter);
// Exposed only by the local preview for its browser regression checks.
window.samplePriceCharts = dashboard.charts;
window.sampleDashboard = dashboard;
window.sampleAdapter = adapter;
window.mountSharedDashboard = mountDashboard;
