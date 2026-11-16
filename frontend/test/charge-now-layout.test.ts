// @vitest-environment node
// Stage 18.2: Charge Now is one card (same field language as the plan controls) and mobile cards run edge to edge.
// Structural checks of the shared markup/CSS; pixel layout was checked separately in a browser (see handoff).
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const dark = readFileSync(new URL("../shared-dashboard/dark.css", import.meta.url), "utf8").replaceAll(String.fromCharCode(13), "");
const panel = readFileSync(new URL("../sidebar/panel.js", import.meta.url), "utf8");
const section = panel.slice(panel.indexOf('<section id="charge-controls"'), panel.indexOf("</section>", panel.indexOf('<section id="charge-controls"')));
const mobile = dark.slice(dark.lastIndexOf("@media(max-width:800px){\n.shell"));

describe("Charge Now layout", () => {
  it("keeps every id, groups fields in one card and nests no form", () => {
    for (const id of ["charge-now", "charge-options", "charge-duration", "custom-label", "charge-end", "charge-replace", "charge-state", "charge-notice"]) expect(section).toContain(`id="${id}"`);
    expect(section).toContain('aria-label="Charge Now"');
    expect(section).toContain('class="cn-fields"');
    expect(section).toContain('class="cn-actions"');
    expect(section).not.toContain("<form");
    expect(section.match(/id="charge-now"/g)).toHaveLength(1);
  });
  it("styles it as a wrapping card without fixed widths or a second boxed details", () => {
    expect(dark).toMatch(/#charge-controls,#log-viewer\{background:#1a202b/);
    expect(dark).toMatch(/#charge-options\{background:none;[^}]*border:0/);
    expect(dark).toContain(".cn-fields{display:flex;flex-wrap:wrap");
    expect(dark).toMatch(/\.cn-fields label\{[^}]*flex:1 1 180px/);
    expect(dark).toContain('.cn-fields [hidden]{display:none!important}');
    expect(dark).toMatch(/\.cn-actions button[^}]*min-height:44px/);
    expect(dark).not.toMatch(/#charge-controls\{[^}]*(?:[^-]width:\d+px)/);
    expect(dark).not.toMatch(/#charge-session>\*|#schedule-check>\*/);
  });
  it("host-bar styles no longer hard-code Charge Now layout", () => {
    expect(panel).not.toContain("#charge-options label{display:inline-block");
    expect(panel).not.toContain("#charge-controls{flex:1 1 100%;align-items:center}");
  });
});

describe("mobile edge-to-edge cards", () => {
  it("removes outer horizontal gutters at the existing 800px breakpoint, keeps vertical spacing", () => {
    expect(mobile).toContain(".shell{padding-left:0;padding-right:0}");
    expect(mobile).toMatch(/\.panel\{border-radius:0;border-left:0;border-right:0/);
    expect(mobile).toMatch(/#charge-controls,#log-viewer\{border-radius:0;border-left-width:0;border-right-width:0/);
    expect(mobile).toContain(".hostbar>#charge-controls{margin-left:-16px;margin-right:-16px");
    expect(mobile).not.toMatch(/\.shell\{[^}]*(?:padding-top|padding-bottom):0/);
    expect(mobile).not.toMatch(/100vw/.source.replace("100vw", "(?:width|min-width):100vw"));
  });
  it("lets long text and debug lines wrap instead of overflowing, and keeps desktop max width", () => {
    expect(mobile).toContain("overflow-wrap:anywhere");
    expect(dark).toContain("white-space:pre-wrap;overflow-wrap:anywhere");
    expect(readFileSync(new URL("../shared-dashboard/styles.css", import.meta.url), "utf8")).toContain(".shell{max-width:1440px;margin:auto;padding:32px 40px}");
  });
});
