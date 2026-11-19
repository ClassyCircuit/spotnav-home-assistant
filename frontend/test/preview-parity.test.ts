// @vitest-environment jsdom
import { describe, it, expect } from 'vitest';
import { createSampleAdapter } from '../prototype/sample-adapter.js';
import { renderPlanEditor } from '../shared-dashboard/plan-editor-view.js';

describe('fictional preview parity', () => {
  it('exposes the read-only production editor and honest proposal context', () => {
    const { model: m, actions } = createSampleAdapter();
    expect(m.settingsEditor).toBe(true);
    expect(m.canSave).toBe(false);
    expect(actions.save).toBeUndefined();
    expect(m.windowsContext.codes).toEqual([]);
    const view = renderPlanEditor({m, settings:m.settings, e:String, value:String, priceText:String, capUnit:'c/kWh'});
    expect(view.summary).toContain('Proposed defaults');
    expect(view.summary).toContain('Limited to your permissions');
    expect(view.groups).toContain('data-setting="capBasis" disabled');
  });
});
