import { renderBattery as sharedBattery } from '../shared-dashboard/vehicle-view.js';
export { batteryEstimates } from '../shared-dashboard/vehicle-view.js';
export const renderBattery = input => sharedBattery({ minimum: 40, deadline: '07:00', sample: true, ...input });
