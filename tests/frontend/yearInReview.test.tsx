import React, { act } from "react";
import { afterEach, describe, expect, test, vi } from "vitest";
import { renderToString } from "react-dom/server";
import { createRoot } from "react-dom/client";
import { JSDOM } from "jsdom";
import { AppShell } from "../../apps/frontend/src/App";
import { defaultReviewYear, type YearInReviewWorkflow } from "../../apps/frontend/src/useYearInReviewWorkflow";
import { YearInReviewView } from "../../apps/frontend/src/views/YearInReviewView";
import { RatingsChapter } from "../../apps/frontend/src/views/yearInReview/RatingsChapter";
import { TasteChapter } from "../../apps/frontend/src/views/yearInReview/TasteChapter";
import { TimingChapter } from "../../apps/frontend/src/views/yearInReview/TimingChapter";
import { drawPoster } from "../../apps/frontend/src/views/yearInReview/poster";
import { fakeApiClient } from "./fakeApiClient";

// jsdom has no canvas, so the poster's drawing is stood in for; its layout is tested in yearInReviewPoster.test.ts.
vi.mock("../../apps/frontend/src/views/yearInReview/poster", async importOriginal => ({
  ...(await importOriginal<typeof import("../../apps/frontend/src/views/yearInReview/poster")>()),
  drawPoster: vi.fn(async () => new Uint8Array([137, 80, 78, 71]))
}));
import { emptySummary, fullSummary, reviewGame } from "./yearInReviewFixture";
import type { CompletedGameDetail } from "../../shared/types";

const readyState = { status: "ready" as const, releases: [], syncStatus: { status: "idle" as const, added: 0, repaired: 0, skipped: 0, failed: 0 } };
const years = [{ year: 2027, count: 0, inProgress: true }, { year: 2026, count: 2, inProgress: false }, { year: 2019, count: 1, inProgress: false }];

let cleanups: Array<() => Promise<void>> = [];
afterEach(async () => {
  for (const cleanup of cleanups) await cleanup();
  cleanups = [];
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

async function renderApp(element: React.ReactElement) {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const dom = new JSDOM("<!doctype html><div id=\"root\"></div>", { url: "http://127.0.0.1" });
  vi.stubGlobal("window", dom.window);
  vi.stubGlobal("document", dom.window.document);
  vi.stubGlobal("navigator", dom.window.navigator);
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  Object.assign(dom.window.HTMLElement.prototype, { attachEvent: () => undefined, detachEvent: () => undefined });
  const container = dom.window.document.getElementById("root")!;
  const root = createRoot(container);
  await act(async () => root.render(element));
  // The lazy view resolves on a later tick.
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); });
  cleanups.push(async () => {
    await act(async () => root.unmount());
    dom.window.close();
  });
  return { container, dom };
}

const button = (container: Element, text: string) => {
  const found = [...container.querySelectorAll("button")].find(item => item.textContent === text);
  if (!found) throw new Error(`Button not found: ${text}`);
  return found as HTMLButtonElement;
};

const startsWith = (container: Element, text: string) => {
  const found = [...container.querySelectorAll("button")].find(item => item.textContent?.startsWith(text));
  if (!found) throw new Error(`Button not found: ${text}`);
  return found as HTMLButtonElement;
};

const activeTab = (container: Element) => container.querySelector("[role='tab'][aria-selected='true']")?.textContent;

function workflow(summary = fullSummary()): YearInReviewWorkflow {
  return { years, year: summary.year, summary, status: "ready", actions: { selectYear: () => undefined, saveSettings: async () => null } };
}

describe("Year in Review view", () => {
  test("renders every card's content without an IntersectionObserver (first paint and tests)", () => {
    const html = renderToString(<YearInReviewView workflow={workflow()} />).replace(/<!-- -->/g, "");
    expect(html).toContain("Your <em>2026</em> in games");
    expect(html).toContain("The Voyage of 2026");
    expect(html).toContain("Games finished");
    expect(html).toContain(">2<");
    expect(html).toContain("+1 on 2025");
    expect(html).toContain("March");
    expect(html).toContain("First · 2 Mar 2026");
    expect(html).not.toContain("is-pending");
  });

  test("the month chart keeps every month as its own column, even the repeated initials", async () => {
    const errors = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const { container } = await renderApp(<YearInReviewView workflow={workflow()} />);
    expect([...container.querySelectorAll(".yir-columns__label")].map(label => label.textContent).join("")).toBe("JFMAMJJASOND");
    expect(errors.mock.calls.flat().join(" ")).not.toContain("same key");
    errors.mockRestore();
  });

  test("a year with no games shows the empty state and no chapters", () => {
    const html = renderToString(<YearInReviewView workflow={workflow(emptySummary(2019))} />).replace(/<!-- -->/g, "");
    expect(html).toContain("No finished games recorded for 2019");
    expect(html).not.toContain("role=\"tab\"");
  });

  test("the current year is marked as so far", () => {
    const html = renderToString(<YearInReviewView workflow={workflow({ ...fullSummary(2027), inProgress: true })} />);
    expect(html).toContain("so far");
  });

  test("opens the latest year with games, or the current year once it has some", () => {
    expect(defaultReviewYear(years)).toBe(2026);
    expect(defaultReviewYear([{ year: 2027, count: 3, inProgress: true }, ...years.slice(1)])).toBe(2027);
    expect(defaultReviewYear([{ year: 2027, count: 0, inProgress: true }])).toBe(2027);
  });
});

describe("Year in Review chapters", () => {
  const text = (element: React.ReactElement) => renderToString(element).replace(/<!-- -->/g, "").replace(/<[^>]+>/g, " ").replace(/&#x27;/g, "'").replace(/\s+/g, " ");

  test("Taste reads genres, platforms and what was new", () => {
    const html = text(<TasteChapter summary={fullSummary()} />);
    expect(html).toContain("100% RPG");
    expect(html).toContain("A strong Fantasy streak");
    expect(html).toContain("Supergiant Games");
    expect(html).toContain("Mostly solo");
    expect(html).toContain("Roguelike");
    expect(html).toContain("1 game isn't matched yet");
  });

  test("Ratings shows the player type, hot take, hidden gem and agreement", () => {
    const html = text(<RatingsChapter summary={fullSummary()} />);
    expect(html).toContain("The Explorer");
    expect(html).toContain("You played 8 different genres");
    expect(html).toContain("You gave it 7; critics gave 90");
    expect(html).toContain("only 12 ratings on IGDB");
    expect(html).toContain("50%");
  });

  test("Timing shows day-one, late, the release range and the streak", () => {
    const html = text(<TimingChapter summary={fullSummary()} />);
    expect(html).toContain("Day-one finishes");
    expect(html).toContain("4 years late");
    expect(html).toContain("2022 – 2026");
    expect(html).toContain("3 months");
    expect(html).toContain("May to July");
  });

  test("a chapter leaves out cards without data rather than showing them empty", () => {
    const html = text(<RatingsChapter summary={emptySummary(2026, { count: 3 })} />);
    expect(renderToString(<RatingsChapter summary={emptySummary(2026, { count: 3 })} />)).not.toContain("yir-card");
    expect(html).toContain("3 games without a rating are left out");
  });
});

describe("Year in Review in the app", () => {
  async function openYearInReview(summary = fullSummary(), bridge?: Record<string, unknown>, { motion = false, themeAutoplay = false } = {}) {
    const api = fakeApiClient({
      getPreferences: async () => ({ palette: null, themeAutoplay }),
      getYearInReviewYears: async () => ({ years }),
      getYearInReview: async year => (year === 2026 ? summary : emptySummary(year)),
      saveYearInReviewSettings: async () => summary,
      getCompletedGame: async id => completedDetail(id)
    });
    const rendered = await renderApp(<AppShell apiBaseUrl="http://unused" api={api} initialState={readyState} />);
    if (bridge) (rendered.dom.window as unknown as { releaseTracker: unknown }).releaseTracker = bridge;
    // Motion on: a frame loop, as in the app (the test DOM has none, so openings and wipes stay off by default).
    if (motion) Object.assign(rendered.dom.window, { requestAnimationFrame: (callback: () => void) => setTimeout(callback, 16), cancelAnimationFrame: (id: number) => clearTimeout(id) });
    await act(async () => button(rendered.container, "Year in Review").click());
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); });
    return { api, ...rendered };
  }

  test("the nav opens the latest year with games at its first chapter", async () => {
    const { api, container } = await openYearInReview();
    expect(api.getYearInReview).toHaveBeenCalledWith(2026);
    expect(container.querySelector("h1")?.textContent).toBe("Your 2026 in games");
    expect(activeTab(container)).toBe("Overview");
  });

  test("tabs and arrow keys change chapter", async () => {
    const { container, dom } = await openYearInReview();
    await act(async () => button(container, "Taste").click());
    expect(activeTab(container)).toBe("Taste");
    expect(container.querySelector("[role='tabpanel']")?.textContent).toContain("Supergiant Games");

    await act(async () => { dom.window.document.dispatchEvent(new dom.window.KeyboardEvent("keydown", { key: "ArrowLeft", bubbles: true })); });
    expect(activeTab(container)).toBe("Overview");
  });

  test("arrow keys typed into a form field don't change chapter", async () => {
    const { container, dom } = await openYearInReview();
    const select = container.querySelector("select[aria-label='Year']")!;
    await act(async () => { select.dispatchEvent(new dom.window.KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true })); });
    expect(activeTab(container)).toBe("Overview");
  });

  test("Space on a focused button presses the button instead of turning the page", async () => {
    const { container, dom } = await openYearInReview();
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 360)); });
    await pressKey(dom, " ", button(container, "Overview"));
    expect(activeTab(container)).toBe("Overview");

    await pressKey(dom, " ");
    expect(activeTab(container)).toBe("Taste");
  });

  test("wheeling past the end of a settled chapter carries on into the next one", async () => {
    const { container, dom } = await openYearInReview();
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 360)); });
    const panel = container.querySelector("[role='tabpanel']")!;
    // jsdom has no layout, so the chapter is short: at its top and bottom at once.
    await act(async () => { panel.dispatchEvent(new dom.window.WheelEvent("wheel", { deltaY: 200, bubbles: true })); });
    expect(activeTab(container)).toBe("Taste");

    // The tail of the same fling is ignored.
    await act(async () => { container.querySelector("[role='tabpanel']")!.dispatchEvent(new dom.window.WheelEvent("wheel", { deltaY: 200, bubbles: true })); });
    expect(activeTab(container)).toBe("Taste");
  });

  test("the year picker loads another year", async () => {
    const { api, container, dom } = await openYearInReview();
    const select = container.querySelector("select[aria-label='Year']") as HTMLSelectElement;
    await act(async () => {
      select.value = "2019";
      select.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
    });
    expect(api.getYearInReview).toHaveBeenLastCalledWith(2019);
    expect(container.textContent).toContain("No finished games recorded for 2019");
  });

  test("the key listener is gone once you leave Year in Review", async () => {
    const { container, dom } = await openYearInReview();
    await act(async () => button(container, "Upcoming").click());
    await act(async () => { dom.window.document.dispatchEvent(new dom.window.KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true })); });
    await act(async () => button(container, "Year in Review").click());
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); });
    expect(activeTab(container)).toBe("Overview");
  });

  const withMusic = () => {
    const summary = fullSummary();
    return { ...summary, goty: { ...summary.goty!, musicVideoId: "dQw4w9WgXcQ" } };
  };
  const pressKey = async (dom: JSDOM, key: string, target: EventTarget = dom.window.document) => {
    await act(async () => { target.dispatchEvent(new dom.window.KeyboardEvent("keydown", { key, bubbles: true, cancelable: true })); });
  };

  test("Save as image offers a horizontal or vertical poster of every game this year, desktop only", async () => {
    const browserOnly = await openYearInReview();
    expect([...browserOnly.container.querySelectorAll("button")].some(item => item.textContent === "Save as image")).toBe(false);
    await cleanups.pop()!();

    const saveImage = vi.fn(async () => ({ ok: true, path: "/pics/x.png" }));
    const { container, dom } = await openYearInReview(fullSummary(), { saveImage });
    await act(async () => button(container, "Save as image").click());
    const choices = [...container.querySelectorAll(".yir-save__choice")].map(choice => choice.textContent);
    expect(choices).toEqual(["Horizontal1920 × 1080 · for screens", "VerticalReadable on phones · for Reddit"]);
    expect(container.querySelector(".yir-save__intro")?.textContent).toBe("A poster of all 2 games you finished in 2026");

    // Escape closes the choice first, without leaving Year in Review.
    await pressKey(dom, "Escape");
    expect(container.querySelector(".yir-save__menu")).toBeNull();
    expect(container.querySelector(".yir")).not.toBeNull();

    await act(async () => button(container, "Save as image").click());
    await act(async () => { (container.querySelectorAll(".yir-save__choice")[1] as HTMLButtonElement).click(); await new Promise(resolve => setTimeout(resolve, 0)); });
    expect(drawPoster).toHaveBeenCalledWith(expect.objectContaining({ orientation: "vertical", summary: expect.objectContaining({ year: 2026 }) }));
    expect(saveImage).toHaveBeenCalledWith(new Uint8Array([137, 80, 78, 71]), "Year in Review 2026 - Vertical");
    expect(container.querySelector("[role='status']")?.textContent).toBe("Saved");
  });

  test("the finale shows the GOTY with its note, and with autoplay on its theme plays by itself in the background", async () => {
    const { container, dom } = await openYearInReview(withMusic(), undefined, { themeAutoplay: true });
    await pressKey(dom, "End");
    expect(activeTab(container)).toBe("Game of the Year");
    expect(container.querySelector(".yir-goty__title")?.textContent).toBe("Hades");
    expect(container.querySelector("button.yir-goty__cover[aria-label='Open Hades'] img")).not.toBeNull();
    expect(container.textContent).toContain("“Run 40 finally.”");
    // The rest of the year, under the GOTY: each with its title and (platform).
    expect([...container.querySelectorAll(".yir-covers .yir-tile__caption")].map(caption => caption.textContent)).toEqual(["Tunic (PS5)"]);
    // Playing already, with no video on show: the player is hidden and a pill says what is playing.
    const iframe = container.querySelector(".yir-player iframe.yir-player__frame");
    expect(iframe?.getAttribute("src")).toMatch(/^https:\/\/www\.youtube-nocookie\.com\/embed\/dQw4w9WgXcQ\?/);
    expect(container.querySelector(".yir-player__label")?.textContent).toBe("Theme music");

    await pressKey(dom, "Home");
    expect(activeTab(container)).toBe("Overview");
    expect(container.querySelector("iframe")).not.toBeNull();

    await act(async () => button(container, "Stop").click());
    expect(container.querySelector("iframe")).toBeNull();
    await pressKey(dom, "End");
    await act(async () => button(container, "▶ Play theme").click());
    expect(container.querySelector("iframe")).not.toBeNull();
    await act(async () => button(container, "■ Stop theme").click());
    expect(container.querySelector("iframe")).toBeNull();
  });

  test("theme music waits for Play unless autoplay is on", async () => {
    const { container, dom } = await openYearInReview(withMusic());
    expect(container.querySelector("iframe")).toBeNull();

    await pressKey(dom, "End");
    await act(async () => button(container, "▶ Play theme").click());
    expect(container.querySelector(".yir-player iframe")).not.toBeNull();
  });

  test("leaving Year in Review stops the music", async () => {
    const { container } = await openYearInReview(withMusic(), undefined, { themeAutoplay: true });
    expect(container.querySelector("iframe")).not.toBeNull();
    await act(async () => button(container, "✕ Leave").click());
    expect(container.querySelector("iframe")).toBeNull();
  });

  test("the music follows the year on screen, and a Stop lasts for that year", async () => {
    const { container, dom } = await openYearInReview(withMusic(), undefined, { themeAutoplay: true });
    expect(container.querySelector("iframe")).not.toBeNull();
    const select = container.querySelector("select[aria-label='Year']") as HTMLSelectElement;
    const pickYear = async (year: string) => act(async () => {
      select.value = year;
      select.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
      await new Promise(resolve => setTimeout(resolve, 0));
    });

    await pickYear("2019");
    expect(container.querySelector("iframe")).toBeNull();
    await pickYear("2026");
    expect(container.querySelector("iframe")).not.toBeNull();

    await act(async () => button(container, "Stop").click());
    await pickYear("2019");
    await pickYear("2026");
    expect(container.querySelector("iframe")).toBeNull();
  });

  test("a game opens its Completed Library page, and back returns to the same chapter", async () => {
    const { api, container } = await openYearInReview();
    await act(async () => button(container, "Timing & Habits").click());
    const tunic = container.querySelector("[role='tabpanel'] button[aria-label='Open Tunic']") as HTMLButtonElement;
    await act(async () => { tunic.click(); await new Promise(resolve => setTimeout(resolve, 0)); });

    expect(api.getCompletedGame).toHaveBeenCalledWith("tunic-ps5");
    expect(container.querySelector(".detail-view h2")?.textContent).toBe("Tunic");
    await act(async () => { button(container, "← back to Year in Review").click(); await new Promise(resolve => setTimeout(resolve, 0)); });
    expect(container.querySelector("h1")?.textContent).toBe("Your 2026 in games");
    expect(activeTab(container)).toBe("Timing & Habits");
  });

  test("the day-one card unrolls every day-one game under the cards, and a game's page comes back to it", async () => {
    const summary = fullSummary();
    const games = ["Hades", "Tunic", "Celeste", "Hollow Knight", "Balatro"].map((title, index) => reviewGame({ id: `g${index}`, title, finishLabel: `${index + 1} Mar 2026` }));
    const { api, container, dom } = await openYearInReview({ ...summary, timing: { ...summary.timing, dayOne: { games } } });
    await act(async () => button(container, "Timing & Habits").click());
    expect(container.querySelectorAll("[role='tabpanel'] .yir-card .yir-game")).toHaveLength(4 + 3);

    await act(async () => startsWith(container, "See all 5").click());
    const shelf = () => container.querySelector("[role='tabpanel'] section[aria-label='Day-one finishes']");
    expect(shelf()?.querySelectorAll(".yir-tile")).toHaveLength(5);
    expect(startsWith(container, "See all 5").getAttribute("aria-pressed")).toBe("true");

    await act(async () => { (shelf()!.querySelector("button[aria-label='Open Balatro']") as HTMLButtonElement).click(); await new Promise(resolve => setTimeout(resolve, 0)); });
    expect(api.getCompletedGame).toHaveBeenCalledWith("g4");
    await act(async () => { button(container, "← back to Year in Review").click(); await new Promise(resolve => setTimeout(resolve, 0)); });
    expect(shelf()?.querySelectorAll(".yir-tile")).toHaveLength(5);

    await pressKey(dom, "Escape");
    expect(shelf()).toBeNull();
    expect(activeTab(container)).toBe("Timing & Habits");
    expect(container.querySelector(".yir")).not.toBeNull();
  });

  test("opening a year plays its intro, which any key skips without turning the page", async () => {
    const { container, dom } = await openYearInReview(fullSummary(), undefined, { motion: true });
    const intro = () => container.querySelector(".yir-intro");
    expect([...intro()!.querySelectorAll(".yir-intro__year span")].map(digit => digit.textContent).join("")).toBe("2026");
    expect(intro()!.querySelector(".yir-intro__count")?.textContent).toBe("2 games finished. Let's look back.");
    expect(container.querySelector(".yir")?.classList.contains("yir--intro")).toBe(true);

    await pressKey(dom, "ArrowRight");
    expect(intro()).toBeNull();
    expect(activeTab(container)).toBe("Overview");
    expect(container.querySelector(".yir")?.classList.contains("yir--intro")).toBe(false);

    // A chapter change sweeps a band in the new chapter's colour across the screen.
    await pressKey(dom, "ArrowRight");
    expect(activeTab(container)).toBe("Taste");
    expect((container.querySelector(".yir-wipe") as HTMLElement | null)?.style.getPropertyValue("--wipe")).toBe("#3fa66f");
  });

  test("the intro lets shortcuts and Tab through, and still skips on a plain key", async () => {
    const { container, dom } = await openYearInReview(fullSummary(), undefined, { motion: true });
    const press = async (init: KeyboardEventInit) => {
      const event = new dom.window.KeyboardEvent("keydown", { bubbles: true, cancelable: true, ...init });
      await act(async () => { dom.window.document.dispatchEvent(event); });
      return event;
    };

    for (const shortcut of [{ key: "c", ctrlKey: true }, { key: "F4", altKey: true }, { key: "r", metaKey: true }, { key: "Tab" }]) {
      expect((await press(shortcut)).defaultPrevented).toBe(false);
      expect(container.querySelector(".yir-intro")).not.toBeNull();
    }

    expect((await press({ key: "a" })).defaultPrevented).toBe(true);
    expect(container.querySelector(".yir-intro")).toBeNull();
  });

  test("the intro doesn't play when coming back from a game's page", async () => {
    const { container } = await openYearInReview(fullSummary(), undefined, { motion: true });
    await act(async () => { (container.querySelector(".yir-intro") as HTMLElement).click(); });
    await act(async () => { (container.querySelector("[role='tabpanel'] button[aria-label='Open Hades']") as HTMLButtonElement).click(); await new Promise(resolve => setTimeout(resolve, 0)); });
    await act(async () => { button(container, "← back to Year in Review").click(); await new Promise(resolve => setTimeout(resolve, 0)); });
    expect(container.querySelector("h1")?.textContent).toBe("Your 2026 in games");
    expect(container.querySelector(".yir-intro")).toBeNull();
  });

  test("clicking a genre, platform, month or rating unrolls the games in it", async () => {
    const { container } = await openYearInReview();
    const revealed = () => [...container.querySelectorAll("[role='tabpanel'] .yir-reveal .yir-tile__caption")].map(caption => caption.textContent);

    await act(async () => (container.querySelector("button[aria-label='March: 1 game']") as HTMLButtonElement).click());
    expect(container.querySelector(".yir-reveal__title")?.textContent).toBe("Finished in March");
    expect(revealed()).toEqual(["Hades (PC)"]);
    await act(async () => (container.querySelector("button[aria-label='March: 1 game']") as HTMLButtonElement).click());
    expect(container.querySelector(".yir-reveal")).toBeNull();

    await act(async () => button(container, "Taste").click());
    await act(async () => (container.querySelector("button[aria-label='RPG, 100%: show its games']") as HTMLButtonElement).click());
    expect(revealed()).toEqual(["Hades (PC)", "Tunic (PS5)"]);
    await act(async () => (container.querySelector("button[aria-label='PS5, 50%: show its games']") as HTMLButtonElement).click());
    expect(container.querySelector(".yir-reveal__title")?.textContent).toBe("Played on PS5");
    expect(revealed()).toEqual(["Tunic (PS5)"]);

    await act(async () => button(container, "Ratings").click());
    expect(container.querySelector(".yir-reveal")).toBeNull();
    await act(async () => (container.querySelector("button[aria-label='9: 1 game']") as HTMLButtonElement).click());
    expect(revealed()).toEqual(["Hades (PC)"]);
  });

  test("Escape with nothing open, or Leave, goes back to Upcoming", async () => {
    const { container, dom } = await openYearInReview();
    await pressKey(dom, "Escape");
    expect(container.querySelector(".yir")).toBeNull();

    await act(async () => button(container, "Year in Review").click());
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); });
    await act(async () => button(container, "✕ Leave").click());
    expect(container.querySelector(".yir")).toBeNull();
  });

  test("Choose my GOTY saves the pick", async () => {
    const { api, container, dom } = await openYearInReview();
    await pressKey(dom, "End");
    await act(async () => button(container, "Choose my GOTY").click());
    const tunic = [...container.querySelectorAll(".yir-picker button")].find(item => item.textContent?.includes("Tunic")) as HTMLButtonElement;
    await act(async () => tunic.click());
    expect(api.saveYearInReviewSettings).toHaveBeenCalledWith(2026, { gotyCompletedId: "tunic-ps5" });
    expect(container.querySelector(".yir-picker")).toBeNull();
  });

  test("a save that lands after you changed year doesn't replace the year on screen", async () => {
    let finishSave: (summary: ReturnType<typeof fullSummary>) => void = () => undefined;
    const api = fakeApiClient({
      getYearInReviewYears: async () => ({ years }),
      getYearInReview: async year => (year === 2026 ? fullSummary() : emptySummary(year)),
      saveYearInReviewSettings: () => new Promise(resolve => { finishSave = resolve; })
    });
    const { container, dom } = await renderApp(<AppShell apiBaseUrl="http://unused" api={api} initialState={readyState} />);
    await act(async () => button(container, "Year in Review").click());
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); });
    await pressKey(dom, "End");
    await act(async () => button(container, "Choose my GOTY").click());
    const tunic = [...container.querySelectorAll(".yir-picker button")].find(item => item.textContent?.includes("Tunic")) as HTMLButtonElement;
    await act(async () => tunic.click());

    const select = container.querySelector("select[aria-label='Year']") as HTMLSelectElement;
    await act(async () => {
      select.value = "2019";
      select.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
    });
    await act(async () => finishSave(fullSummary()));
    expect(container.textContent).toContain("No finished games recorded for 2019");
  });

  test("theme music takes a YouTube link, and arrow keys in the box don't change chapter", async () => {
    const { api, container, dom } = await openYearInReview();
    await pressKey(dom, "End");
    await act(async () => button(container, "Set theme music").click());
    const input = container.querySelector("input[aria-label='YouTube link']") as HTMLInputElement;
    const save = button(container, "Save music");

    await typeInto(dom, input, "https://vimeo.com/1");
    expect(save.disabled).toBe(true);
    expect(container.textContent).toContain("That isn't a YouTube video link.");

    await pressKey(dom, "ArrowLeft", input);
    expect(activeTab(container)).toBe("Game of the Year");

    await typeInto(dom, input, "https://youtu.be/dQw4w9WgXcQ");
    expect(save.disabled).toBe(false);
    await act(async () => save.click());
    expect(api.saveYearInReviewSettings).toHaveBeenCalledWith(2026, { musicLink: "https://youtu.be/dQw4w9WgXcQ" });
  });
});

function completedDetail(id: string): CompletedGameDetail {
  const title = id === "tunic-ps5" ? "Tunic" : id === "hades-pc" ? "Hades" : id;
  return {
    id, title, normalizedTitle: title.toLowerCase(), userPlatform: "PC", completionPrecision: "exact", genres: [], igdbGenres: [], platforms: [],
    matchStatus: "matched", extra: {}, igdbPlatforms: [], igdbThemes: [], igdbGameModes: [], screenshots: []
  };
}

async function typeInto(dom: JSDOM, input: HTMLInputElement, value: string) {
  await act(async () => {
    input.focus();
    Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype, "value")!.set!.call(input, value);
    input.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
    input.dispatchEvent(new dom.window.KeyboardEvent("keyup", { bubbles: true }));
  });
}
