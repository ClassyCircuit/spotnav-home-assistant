// @ts-nocheck
// Stage 20.3: shared control markup for pending / uncertain / confirmation states. Pure rendering; the host owns every gate.
import { describe, expect, it } from 'vitest';
import { renderControls, renderRecoveryBanner } from '../shared-dashboard/shell.js';

describe('action feedback markup', () => {
  it('marks pending buttons busy and gives the uncertain outcome an alert role and kind', () => {
    const pending = renderControls({ chargeBusy: true, chargeKind: 'pending', chargeNotice: 'Request in progress', autoBusy: true });
    expect(pending).toContain('id="charge-now" class="sn-btn sn-btn-primary" aria-busy="true"');
    expect(pending).toMatch(/id="pause-auto"[^>]*aria-busy="true"/);
    expect(pending).toMatch(/id="charge-notice"[^>]*role="status" data-kind="pending"/);
    const unknown = renderControls({ chargeKind: 'uncertain', chargeNotice: 'Unknown outcome' });
    expect(unknown).toMatch(/id="charge-notice"[^>]*role="alert" data-kind="uncertain"/);
    expect(renderControls({})).not.toContain('aria-busy');
    expect(renderControls({ chargeKind: '<script>' })).toContain('data-kind=""');
  });
  it('renders an escaped, labelled in-page confirmation only when the host supplies one', () => {
    expect(renderControls({})).not.toContain('charge-confirm');
    const html = renderControls({ confirm: { token: 3, action: 'charge_now', origin: 'charge-now', title: 'Start <b>', text: 'Fixed end & price', confirmLabel: 'Go' } });
    expect(html).toMatch(/role="alertdialog" aria-modal="false" aria-labelledby="charge-confirm-title" aria-describedby="charge-confirm-text"/);
    expect(html).not.toContain('<b>'); expect(html).toContain('Fixed end &amp; price');
    expect(html).toContain('id="charge-confirm-cancel"'); expect(html).toContain('id="charge-confirm-ok"');
  });
  it('links a recovery banner to the controls with no data-changing attribute', () => {
    const html = renderRecoveryBanner({ level: 'warning', code: 'x', text: 'Unknown outcome' });
    expect(html).toContain('id="recovery-goto-controls"'); expect(html).toContain('data-goto-controls');
    expect(renderRecoveryBanner(null)).not.toContain('goto');
  });
});
