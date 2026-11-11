// Loading a language: English is in the bundle, every other language is one file fetched from Home
// Assistant, once per page. The shipped card itself always uses English.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LANGUAGE_FILES } from "../src/generated/languages";
import {
  LANGUAGES,
  LANGUAGE_URL_PATH,
  forgetLanguages,
  isLanguageLoaded,
  isLanguagePending,
  loadLanguage,
  translate,
} from "../src/i18n";
import { TRANSLATIONS } from "../src/i18n/all";
import { dashboard, FakeHass, mountCard } from "./helpers";

const WWW_I18N = resolve(__dirname, "../../custom_components/spotnav/www/i18n");
const CONFIG = { type: "custom:spotnav-card", charger: "entry_a" };

const text = (element: Element): string => element.shadowRoot?.textContent ?? "";

async function settle(): Promise<void> {
  await vi.advanceTimersByTimeAsync(0);
}

/** A `fetch` the test answers by hand, one request at a time. */
function handFetch() {
  const calls: string[] = [];
  const waiting: Array<(response: Response) => void> = [];
  const fetcher = vi.fn((input: RequestInfo | URL) => {
    calls.push(String(input));
    return new Promise<Response>((resolveResponse) => waiting.push(resolveResponse));
  });
  return {
    calls,
    fetcher,
    answer(body: unknown, status = 200): void {
      const next = waiting.shift();
      if (next === undefined) {
        throw new Error("no request waiting");
      }
      next(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
    },
  };
}

function urlOf(language: string): string {
  return `${LANGUAGE_URL_PATH}${LANGUAGE_FILES[language]}`;
}

beforeEach(() => {
  vi.useFakeTimers();
  document.body.innerHTML = "";
  forgetLanguages();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("the language files", () => {
  it("name every language but English, and the committed file holds that language's words", () => {
    expect(Object.keys(LANGUAGE_FILES).sort()).toEqual(LANGUAGES.filter((l) => l !== "en").sort());
    for (const [language, name] of Object.entries(LANGUAGE_FILES)) {
      expect(name).toMatch(new RegExp(`^${language}\\.[0-9a-f]{8}\\.json$`));
      const served = JSON.parse(readFileSync(resolve(WWW_I18N, name), "utf8"));
      expect(served, language).toEqual(TRANSLATIONS[language as keyof typeof TRANSLATIONS]);
    }
  });
});

describe("loadLanguage", () => {
  it("needs no request for English, nor for a language it has no file for", async () => {
    const fetcher = vi.fn();
    expect(await loadLanguage("en", fetcher)).toBe(true);
    expect(isLanguagePending("en")).toBe(false);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("fetches a language once, however many ask, and then translates in it", async () => {
    const hand = handFetch();
    expect(isLanguagePending("sv")).toBe(true);
    expect(translate("sv", "state.loading")).toBe(TRANSLATIONS.en["state.loading"]);
    const first = loadLanguage("sv", hand.fetcher);
    const second = loadLanguage("sv", hand.fetcher);
    expect(hand.calls).toEqual([urlOf("sv")]);
    hand.answer(TRANSLATIONS.sv);
    expect(await first).toBe(true);
    expect(await second).toBe(true);
    expect(isLanguageLoaded("sv")).toBe(true);
    expect(translate("sv", "state.loading")).toBe(TRANSLATIONS.sv["state.loading"]);
  });

  it("gives up for the page on a failure, in English, and tries again on the next page load", async () => {
    const hand = handFetch();
    const first = loadLanguage("de", hand.fetcher);
    hand.answer({}, 404);
    expect(await first).toBe(false);
    expect(isLanguagePending("de")).toBe(false);
    expect(translate("de", "state.loading")).toBe(TRANSLATIONS.en["state.loading"]);
    // Not again on this page: a `hass` update arrives many times a minute.
    expect(await loadLanguage("de", hand.fetcher)).toBe(false);
    expect(hand.calls).toHaveLength(1);

    forgetLanguages(); // A reload.
    const again = loadLanguage("de", hand.fetcher);
    expect(hand.calls).toHaveLength(2);
    hand.answer(TRANSLATIONS.de);
    expect(await again).toBe(true);
  });

  it("refuses a file that is not a language", async () => {
    const hand = handFetch();
    const loading = loadLanguage("fi", hand.fetcher);
    hand.answer(["not", "words"]);
    expect(await loading).toBe(false);
    const rejecting = loadLanguage("nl", vi.fn(() => Promise.reject(new TypeError("offline"))));
    expect(await rejecting).toBe(false);
  });
});

describe("the card's language", () => {
  function swedishHass(fake: FakeHass, language = "sv-SE") {
    const snapshot = fake.snapshot("one", language);
    snapshot.user = { is_admin: true };
    return snapshot;
  }

  it.each(["en", "sv-SE", "fr-FR"])("uses English and does not fetch a translation for %s", async (language) => {
    const hand = handFetch();
    vi.stubGlobal("fetch", hand.fetcher);
    const hass = new FakeHass();
    const element = mountCard(CONFIG, swedishHass(hass, language));
    await settle();
    expect(text(element)).toContain(TRANSLATIONS.en["state.loading"]);
    hass.resolveNext(dashboard());
    await settle();
    expect(text(element)).toContain("Planned from");
    expect(text(element)).toContain("Daily overview");
    expect(hand.calls).toEqual([]);
  });

  it("shows English at once, with no request, for a language it does not have", async () => {
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    const hass = new FakeHass();
    const element = mountCard(CONFIG, hass.snapshot("one", "it-IT"));
    await settle();
    expect(text(element)).toContain(TRANSLATIONS.en["state.loading"]);
    hass.resolveNext(dashboard());
    await settle();
    expect(text(element)).toContain("Planned from");
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("keeps the existing English view when the HA language changes", async () => {
    const hand = handFetch();
    vi.stubGlobal("fetch", hand.fetcher);
    const hass = new FakeHass();
    const element = mountCard(CONFIG, hass.snapshot("one", "en"));
    await settle();
    hass.resolveNext(dashboard());
    await settle();
    expect(text(element)).toContain("Planned from");
    expect(hand.calls).toEqual([]);

    const before = hass.messages.length;
    element.hass = hass.snapshot("two", "fr-FR");
    element.hass = hass.snapshot("three", "fr-FR");
    await settle();
    expect(hand.calls).toEqual([]);
    expect(text(element)).toContain("Planned from");

    expect(hass.messages).toHaveLength(before);
  });
});
