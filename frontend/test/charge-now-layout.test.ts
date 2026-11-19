// @vitest-environment node
// Stage 18.2 -> 20.2a: Charge Now is one card inside the shared shell (rendered by shell.js from host models), and the
// layout is decided by the measured `data-sn-layout`, never by viewport media queries. Structural checks only; pixel
// layout needs a browser (unrun).
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { renderControls } from "../shared-dashboard/shell.js";

const css = (name: string) => readFileSync(new URL(`../shared-dashboard/${name}`, import.meta.url), "utf8").replaceAll(String.fromCharCode(13), "");
const shell = css("shell.css");
const panel = readFileSync(new URL("../sidebar/panel.js", import.meta.url), "utf8");
const html = renderControls({}, {});
const section = html.slice(html.indexOf('<section id="charge-controls"'), html.indexOf("</section>"));

describe("Charge Now layout", () => {
  it("keeps every id, groups fields in one card and nests no form", () => {
    for (const id of ["charge-now", "charge-options", "charge-duration", "custom-label", "charge-end", "charge-replace", "charge-state", "charge-notice"]) expect(section).toContain(`id="${id}"`);
    expect(section).toContain('aria-label="Charge Now"');
    expect(section).toContain('class="cn-fields"');
    expect(section).toContain('class="cn-actions"');
    expect(section).not.toContain("<form");
    expect(section.match(/id="charge-now"/g)).toHaveLength(1);
  });
  it("renders controls disabled by default and enabled only from the host model", () => {
    expect(html).toMatch(/id="pause-auto"[^>]* disabled/);
    expect(html).toMatch(/id="resume-auto"[^>]* disabled/);
    expect(html).toMatch(/id="charge-now"[^>]* disabled/);
    const on = renderControls({ pauseDisabled: false, resumeDisabled: false, chargeDisabled: false, chargeLabel: "Return to Auto" });
    expect(on).not.toMatch(/id="(?:pause-auto|resume-auto|charge-now)"[^>]* disabled/);
    expect(on).toContain(">Return to Auto</button>");
  });
  it("styles it as a wrapping card without fixed widths", () => {
    expect(shell).toContain(".cn-fields{display:flex;flex-wrap:wrap");
    expect(shell).toMatch(/\.cn-fields label\{[^}]*flex:1 1 180px/);
    expect(shell).toContain(".cn-fields [hidden]{display:none!important}");
    expect(shell).toMatch(/\.sn-btn\{[^}]*min-height:44px/);
    expect(shell).not.toMatch(/\.sn-charge\{[^}]*[^-]width:\d+px/);
  });
  it("the host no longer renders its own bar or hard-codes control markup", () => {
    expect(panel).not.toContain('class="hostbar"');
    expect(panel).not.toContain('<section id="charge-controls"');
    expect(panel).not.toContain("querySelector('#charge-now')");
  });
});

describe("responsive layout contract", () => {
  it("never defines named grid areas or viewport width media queries for layout", () => {
    for (const name of ["styles.css", "dark.css", "shell.css"]) {
      const code = css(name).replace(/\/\*[\s\S]*?\*\//g, "");
      expect(code, name).not.toMatch(/grid-template-areas/);
      expect(code, name).not.toMatch(/@media\s*\(\s*(?:min|max)-width/);
    }
  });
  it("auto-places one column on narrow panels, with a bottom bar and safe-area padding", () => {
    expect(shell).toMatch(/\.tab-panel>\.dashboard\{display:grid;[^}]*grid-template-columns:minmax\(0,1fr\)/);
    expect(shell).toMatch(/\[data-sn-layout="compact"\] \.sn-nav\{position:fixed;[^}]*bottom:0/);
    expect(shell).toContain("env(safe-area-inset-bottom");
    expect(shell).toMatch(/\.panel\{[^}]*min-width:0;overflow-wrap:anywhere/);
  });
  it("keeps the desktop shell width bounded", () => {
    expect(shell).toMatch(/\.shell\{max-width:1480px;margin:0 auto/);
  });
  it("uses safe-area edges for compact cards and the full chart width", () => {
    expect(shell).toMatch(/\[data-sn-layout="compact"\] \.shell\{--sn-gutter:0px;[^}]*safe-area-inset-left[^}]*safe-area-inset-right/);
    expect(shell).toMatch(/\[data-sn-layout="compact"\] \.prices\{padding-left:0;padding-right:0;border:0;border-radius:0/);
    expect(shell).toMatch(/\[data-sn-layout="compact"\] \.price-chart\{border:0;border-radius:0/);
    expect(shell).toMatch(/\[data-sn-layout="compact"\] \.prices \.track-lanes\{padding-left:0;padding-right:0/);
    expect(shell).toMatch(/\.chart\{width:100%/);
    expect(shell).toMatch(/\.sn-tab\{[^}]*min-height:44px;min-width:44px/);
  });
});
