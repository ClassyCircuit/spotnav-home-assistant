import test from 'node:test';
import assert from 'node:assert/strict';
import { readdir, readFile } from 'node:fs/promises';

test('preview mounts shared dashboard; shared modules do not import sample hosts', async () => {
  const preview = await readFile(new URL('../prototype/dashboard.js', import.meta.url), 'utf8');
  assert.match(preview, /from ['"]\.\.\/shared-dashboard\/dashboard\.js['"]/);
  assert.match(preview, /mountDashboard\(/);
  for (const name of await readdir(new URL('.', import.meta.url))) {
    if (!name.endsWith('.js')) continue;
    const source = await readFile(new URL(name, import.meta.url), 'utf8');
    assert.doesNotMatch(source, /(?:from\s*|import\s*\()\s*['"][^'"]*(?:prototype|sample)/, name);
    assert.doesNotMatch(source, /(?:location\.search|window\.hass)/, name);
  }
});
