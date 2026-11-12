import { mountDashboard } from '../shared-dashboard/dashboard.js';
import { createSampleAdapter } from './sample-adapter.js';

const adapter = createSampleAdapter();
const dashboard = mountDashboard(document.querySelector('#app'), adapter);
// Exposed only by the local preview for its browser regression checks.
window.samplePriceCharts = dashboard.charts;
window.sampleDashboard = dashboard;
window.sampleAdapter = adapter;
window.mountSharedDashboard = mountDashboard;
