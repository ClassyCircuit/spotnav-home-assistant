import { sampleInsights } from './sample-adapter.js';
import { renderInsights as sharedInsights } from '../shared-dashboard/insight-view.js';
export const renderInsights = missing => sharedInsights(sampleInsights(missing));
