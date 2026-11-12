import { historyFixture } from './daily-sample.js';
import { renderHistory as sharedHistory } from '../shared-dashboard/history-view.js';
export const renderHistory = () => sharedHistory(historyFixture(), true);
