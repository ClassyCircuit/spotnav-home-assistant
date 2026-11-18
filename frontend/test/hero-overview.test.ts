// @vitest-environment jsdom
// @ts-nocheck
// Stage 20.2b: the Overview hero. Scene honesty (connected / unplugged / unknown / stale), SOC and metrics only from real
// data, existing guarded controls unchanged, artwork provenance and asset bundling.
import { describe, it, expect } from 'vitest';
import { readFileSync, existsSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { dashboardAdapter } from '../sidebar/adapter.js';
import { mountDashboard } from '../shared-dashboard/dashboard.js';
import { sceneOf, renderArt } from '../shared-dashboard/shell.js';

ElementInternals.prototype.setFormValue = function() {};
ElementInternals.prototype.setValidity = function() {};
ElementInternals.prototype.checkValidity = function() { return true; };
ElementInternals.prototype.reportValidity = function() { return true; };
Object.defineProperty(ElementInternals.prototype,'validity',{get:()=>({valid:true})});
Object.defineProperty(ElementInternals.prototype,'validationMessage',{get:()=>''});
window.scrollTo = () => {};
globalThis.ResizeObserver = class { observe() {} disconnect() {} };

const fixture = () => { const raw = JSON.parse(readFileSync('../tests/fixtures/dashboard/target_soc_two_vehicles.json','utf8')); raw.generated_at = new Date().toISOString(); return raw; };
const status = {api_version:1,schedule:{supported:false,verified:false,sent:null,sent_at:null,ack:null,effective:null}};

function mount(patch = {}) {
  const adapter = dashboardAdapter(fixture(), status, Date.now(), Date.now());
  adapter.draftKey = 'h:1';
  adapter.model = { ...adapter.model, ...patch };
  const root = document.createElement('main'); document.body.append(root);
  return { root, view: mountDashboard(root, adapter), adapter };
}
const art = root => root.querySelector('.sn-art');
const hero = root => root.querySelector('section.hero');
const car = (over = {}) => ({ status:'Connected · waiting to charge', detail:'d', power:'0.0 kW', soc:48, stale:false, ...over });

describe('hero scene honesty', () => {
  it('shows the cable artwork only for a fresh connected report', () => {
    expect(sceneOf({connection:'connected',stale:false}).art).toBe('connected');
    for (const s of [{connection:'connected',stale:true},{connection:'disconnected',stale:false},{connection:'disconnected',stale:true},{connection:'unknown',stale:false},{connection:'bogus'},undefined,null]) expect(sceneOf(s).art, JSON.stringify(s)).toBe('neutral');
  });
  it('names the state in text for every variant and never says connected when it is not known', () => {
    expect(sceneOf({connection:'connected'}).label).toBe('Car reported connected');
    expect(sceneOf({connection:'connected',stale:true}).label).toMatch(/Last reported connected · stale/);
    expect(sceneOf({connection:'disconnected'}).label).toBe('Not plugged in');
    expect(sceneOf({connection:'disconnected',stale:true}).label).toMatch(/stale/);
    expect(sceneOf({connection:'unknown'}).label).toBe('Plug state unknown');
    expect(sceneOf(undefined).label).toBe('Plug state unknown');
    for (const s of [{connection:'disconnected'},{connection:'unknown'},{connection:'connected',stale:true}]) expect(sceneOf(s).description).not.toMatch(/plugged into a Morek/);
  });
  it('renders decorative artwork as a labelled image that carries no state of its own', () => {
    const html = renderArt({connection:'connected'});
    expect(html).toContain('role="img"'); expect(html).toContain('data-art="connected"'); expect(html).toContain('decorative');
    expect(html).not.toMatch(/<img|animation|flow/i);
  });
  it('maps the host evidence into the hero chip and art', () => {
    const { root } = mount({ scene:{connection:'disconnected',stale:false} });
    expect(art(root).dataset.art).toBe('neutral'); expect(root.querySelector('.hero-chip').textContent).toBe('Not plugged in'); expect(hero(root).dataset.scene).toBe('disconnected');
    const c = mount({ scene:{connection:'connected',stale:false} }).root;
    expect(art(c).dataset.art).toBe('connected'); expect(c.querySelector('.hero-chip').dataset.connection).toBe('connected');
    const s = mount({ scene:{connection:'connected',stale:true} }).root;
    expect(art(s).dataset.art).toBe('neutral'); expect(art(s).dataset.artStale).toBe('true'); expect(s.querySelector('.hero-chip').textContent).toMatch(/stale/);
    const u = mount({ scene:undefined }).root;
    expect(art(u).dataset.art).toBe('neutral'); expect(u.querySelector('.hero-chip').textContent).toBe('Plug state unknown');
  });
  it('production adapter reports the plug state only from a fresh Morek status', () => {
    const raw = fixture(); const now = Date.now();
    const ready = {control:'available',vehicle:'connected',vehicle_observed_at:new Date(now).toISOString()};
    const mk = (r, at) => dashboardAdapter(raw, {api_version:1,schedule:{...status.schedule,supported:true,connector_id:1,readiness:r}}, at, now).model.scene;
    expect(mk(ready, now).connection).toBe('connected');
    expect(mk({...ready,vehicle_observed_at:new Date(now - 600000).toISOString()}, now).connection).toBe('unknown');
    expect(mk(ready, now - 3600000).connection).toBe('unknown');
    expect(mk({...ready,vehicle:'disconnected'}, now).connection).toBe('disconnected');
  });
});

describe('hero SOC and metrics', () => {
  it('shows a valid SOC with a target tick, labelled as reported', () => {
    const { root } = mount({ vehicle:car(), settings:{target:80,minimum:40,readyBy:'07:00'} });
    const soc = root.querySelector('.hero-soc');
    expect(soc.dataset.soc).toBe('reported'); expect(soc.querySelector('strong').textContent).toBe('48%'); expect(soc.textContent).toContain('Target 80%');
    expect(soc.querySelector('.hero-meter-fill').style.width).toBe('48%'); expect(soc.querySelector('.hero-meter-target').style.left).toBe('80%');
    expect(soc.querySelector('.hero-meter').getAttribute('aria-label')).toMatch(/Current SOC 48%; target 80%/);
  });
  it('labels stale and estimated SOC and never invents one when unknown', () => {
    const stale = mount({ vehicle:car({stale:true,power:'Unknown'}), settings:{target:80} }).root.querySelector('.hero-soc');
    expect(stale.dataset.soc).toBe('last-known'); expect(stale.textContent).toContain('Last known SOC · stale');
    const est = mount({ vehicle:car({socEstimated:true}), settings:{target:80} }).root.querySelector('.hero-soc');
    expect(est.dataset.soc).toBe('estimated'); expect(est.textContent).toContain('not a measurement');
    const none = mount({ vehicle:car({soc:null}), settings:{target:null} }).root.querySelector('.hero-soc');
    expect(none.dataset.soc).toBe('unknown'); expect(none.querySelector('strong').textContent).toBe('Unknown'); expect(none.querySelector('.hero-meter')).toBeNull();
    const noSoc = mount({ vehicle:car({soc:null}), settings:{target:80} }).root.querySelector('.hero-soc');
    expect(noSoc.querySelector('.hero-meter-fill')).toBeNull(); expect(noSoc.querySelector('.hero-meter-target')).not.toBeNull();
    const bad = mount({ vehicle:car({soc:140}), settings:{target:-3} }).root.querySelector('.hero-soc');
    expect(bad.dataset.soc).toBe('unknown'); expect(bad.querySelector('.hero-meter')).toBeNull();
  });
  it('shows measured power only as the host states it and keeps zero distinct from unknown', () => {
    const zero = mount({ vehicle:car({power:'0.0 kW'}) }).root;
    const unknown = mount({ vehicle:car({power:'Unknown'}) }).root;
    const value = r => [...r.querySelectorAll('.hero-body .metric')].find(m => m.textContent.includes('Measured now')).querySelector('strong').textContent;
    expect(value(zero)).toBe('0.0 kW'); expect(value(unknown)).toBe('Unknown');
    expect(zero.querySelector('.hero [data-flow], .hero [class*="flow"], .hero [class*="pulse"]')).toBeNull();
  });
  it('adds a To-target estimate only when SOC, target and capacity are all valid', () => {
    const has = r => r.textContent.includes('To target · est.');
    const ok = mount({ vehicle:car({soc:40}), settings:{target:80}, assumptions:{capacityKwh:80,efficiency:0.9} }).root;
    expect(has(ok)).toBe(true); expect(ok.textContent).toContain('32.0 kWh');
    expect(has(mount({ vehicle:car({soc:40}), settings:{target:80}, assumptions:{efficiency:0.9} }).root)).toBe(false);
    expect(has(mount({ vehicle:car({soc:null}), settings:{target:80}, assumptions:{capacityKwh:80} }).root)).toBe(false);
  });
  it('keeps the battery assumptions reachable but collapsed', () => {
    const { root } = mount({ vehicle:car({soc:40}), settings:{target:80}, assumptions:{capacityKwh:80,efficiency:0.9} });
    const d = root.querySelector('details.hero-battery'); expect(d).not.toBeNull(); expect(d.open).toBe(false); expect(d.querySelector('.battery-card')).not.toBeNull(); expect(d.textContent).toContain('Assumptions');
  });
});

describe('Overview presentation and controls', () => {
  it('uses one coherent chart title and keeps existing guarded controls in the hero', () => {
    const { root } = mount({ control:{autoState:'Auto on',pauseDisabled:false,resumeDisabled:true,chargeLabel:'Charge Now',chargeDisabled:false,replaceVisible:false,replaceDisabled:true,chargeState:'Ready',chargeNotice:''} });
    expect([...root.querySelectorAll('#sn-panel-overview h2')].find(h => /prices/i.test(h.textContent)).textContent).toMatch(/Electricity prices & (charging )?plan/);
    for (const id of ['#pause-auto','#resume-auto','#charge-now','#charge-duration','#charge-end','#charge-replace']) expect(root.querySelector('.hero ' + id), id).not.toBeNull();
    expect(root.querySelector('#pause-auto').disabled).toBe(false); expect(root.querySelector('#resume-auto').disabled).toBe(true);
    expect(root.querySelector('#open-plan').closest('.hero-top')).not.toBeNull();
  });
});

describe('artwork provenance and bundling', () => {
  const sha = p => createHash('sha256').update(readFileSync(p)).digest('hex');
  it('ships clean WebP files identical in the source and the distribution', () => {
    for (const name of ['bmw-morek-scene.webp','bmw-neutral.webp']) {
      const src = `shared-dashboard/art/${name}`, dist = `../custom_components/spotnav/www/sidebar/${name}`;
      expect(existsSync(src), src).toBe(true); expect(existsSync(dist), dist).toBe(true);
      expect(sha(src)).toBe(sha(dist));
      const head = readFileSync(src).subarray(0, 12); expect(head.subarray(0,4).toString()).toBe('RIFF'); expect(head.subarray(8,12).toString()).toBe('WEBP');
    }
  });
  it('records provenance and uses only the two clean images (never the baked-SOC ones)', () => {
    const doc = readFileSync('shared-dashboard/art/PROVENANCE.md','utf8').toLowerCase();
    for (const word of ['spotnav-pulse-v4-interactive.html','bmw-morek-scene.webp','bmw-neutral.webp','b5a0591e45fe4866','rights','crop','64%']) expect(doc).toContain(word);
    const css = readFileSync('shared-dashboard/shell.css','utf8');
    expect([...css.matchAll(/url\(([^)]+)\)/g)].map(m => m[1]).sort()).toEqual(['bmw-morek-scene.webp','bmw-neutral.webp']);
    expect(sha('shared-dashboard/art/bmw-morek-scene.webp').startsWith('b5a0591e45fe4866')).toBe(true);
  });
});
