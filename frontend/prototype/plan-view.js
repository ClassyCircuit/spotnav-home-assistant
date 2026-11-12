import { time, day } from './sample.js';
import { renderPlan as renderSharedPlan } from '../shared-dashboard/plan-view.js';
export { number } from '../shared-dashboard/plan-view.js';

export const renderPlan = (windows, assumptions, stale) =>
  renderSharedPlan(windows, assumptions, stale, { time, day, staleLabel: 'stale sample' });
