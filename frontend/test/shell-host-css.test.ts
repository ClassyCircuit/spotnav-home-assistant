// @vitest-environment node
// Stage 20.1: the --sn-* tokens must be declared where the panel is styled. The live panel stylesheet lives inside the
// panel's shadow root, where `:root` selects nothing, so it must declare them on `:host`; the preview uses `:root`.
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const src = readFileSync(new URL('../shared-dashboard/shell.css', import.meta.url), 'utf8');
const shipped = readFileSync(new URL('../../custom_components/spotnav/www/sidebar/panel.css', import.meta.url), 'utf8');
const tokenBlock = (css: string) => css.slice(css.indexOf('--sn-bg:'));

describe('shell tokens and host coverage', () => {
  it('source declares tokens for both the preview root and the shadow host', () => {
    expect(src).toMatch(/:root\s*,\s*:host\s*\{--sn-bg:/);
  });
  it('shipped live stylesheet scopes the tokens to :host and never to :root/html/body', () => {
    const start = shipped.indexOf('/* shared-dashboard/shell.css */');
    expect(start).toBeGreaterThan(-1);
    const shell = shipped.slice(start);
    expect(shell).toMatch(/^:host\s*\{\s*--sn-bg:#08111f;/m);
    expect(shell).not.toMatch(/:host,\s*:host/);
    expect(shell).toContain('--sn-nav-h:');
    expect(shell).not.toMatch(/:root|(^|[\s,}])html\b|(^|[\s,}])body\s*\{/m);
    expect(shell).toMatch(/^:host\s*\{[^}]*background:\s*var\(--sn-bg\)/m);
  });
  it('every var(--sn-*) the shell uses is defined in the shipped :host block', () => {
    const shell = shipped.slice(shipped.indexOf('/* shared-dashboard/shell.css */'));
    const defined = new Set([...tokenBlock(shell.slice(0, shell.indexOf('}'))).matchAll(/(--sn-[\w-]+):/g)].map(m => m[1]));
    const used = new Set([...shell.matchAll(/var\((--sn-[\w-]+)/g)].map(m => m[1]));
    for (const token of used) expect(defined.has(token), token).toBe(true);
  });
});
