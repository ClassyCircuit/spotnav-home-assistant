// @vitest-environment node
// Stage 18.1: every owned form/expandable/debug surface gets a dark baseline from the shared dark.css,
// and the sidebar bundle makes the Web Awesome dark palette reach the shadow root. Structural, not a colour snapshot.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const dark = readFileSync(new URL("../shared-dashboard/dark.css", import.meta.url), "utf8");
const shell = readFileSync(new URL("../shared-dashboard/shell.css", import.meta.url), "utf8");
const panel = readFileSync(new URL("../../custom_components/spotnav/www/sidebar/panel.css", import.meta.url), "utf8");
const rule = (css: string, selector: string) => css.split("\n").find((l) => l.startsWith(selector)) ?? "";
const lum = (hex: string) => {
  const [r = 0, g = 0, b = 0] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const contrast = (a: string, b: string) => { const hi = Math.max(lum(a), lum(b)), lo = Math.min(lum(a), lum(b)); return (hi + 0.05) / (lo + 0.05); };

describe("dark theme ownership", () => {
  it("styles native controls in all states without light surfaces", () => {
    expect(dark).toMatch(/:where\(button,select,textarea,input:not/);
    for (const state of [":disabled", "[readonly]", "::placeholder", ":focus-visible"]) expect(dark).toContain(state);
    expect(dark).toContain(":where(option,optgroup)");
    expect(dark).toContain("color-scheme:dark");
  });
  it("covers Web Awesome details/input parts, dialog, Charge Now details and the log viewer", () => {
    for (const s of ["wa-details::part(content)", "wa-input::part(base)", "wa-input[disabled]::part(input)", "dialog{", ".log-lines"]) expect(dark).toContain(s);
    for (const s of ["#charge-options", "#log-viewer"]) expect(shell).toContain(s);
    expect(rule(dark, ".log-lines")).toContain("white-space:pre-wrap");
  });
  it("keeps warning/error colours distinct from the neutral dark surface", () => {
    expect(rule(shell, ".alert{")).toContain("var(--sn-error-soft)");
    expect(shell).toContain("--sn-error-soft:#431a22");
    expect(dark).toContain("[data-level=warn]{border-color:#b9892f}");
    expect(contrast("#ffcf97", "#1a202b")).toBeGreaterThan(7);
  });
  it("has readable text on input/disabled/code surfaces", () => {
    expect(contrast("#f0f3f8", "#161e29")).toBeGreaterThan(7);
    expect(contrast("#c5d0df", "#293342")).toBeGreaterThan(4.5);
    expect(contrast("#9fb0c4", "#161e29")).toBeGreaterThan(4.5);
    expect(contrast("#e2e8f0", "#0d131b")).toBeGreaterThan(7);
  });
  it("sidebar bundle scopes the Web Awesome dark palette to the host and keeps tokens on :host", () => {
    expect(panel).toContain(":host(.wa-dark)");
    expect(panel).not.toMatch(/(^|[,{}\s])\.wa-dark[\s,{]/);
    expect(panel).toContain("#charge-options");
    expect(panel).toMatch(/:host\s*\{[^}]*--sn-input:\s*#0b1626/);
  });
});
