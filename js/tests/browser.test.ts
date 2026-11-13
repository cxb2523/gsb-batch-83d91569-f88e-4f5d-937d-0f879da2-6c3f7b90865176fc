import { describe, it, expect, vi } from "vitest";
import { BrowserManager } from "../src/browser.js";
import { RefRegistry } from "../src/refs.js";

describe("BrowserManager", () => {
  it("starts as not running", () => {
    const manager = new BrowserManager();
    expect(manager.isRunning).toBe(false);
  });

  it("recoverDeadBrowser coalesces concurrent callers into one relaunch", async () => {
    const manager = new BrowserManager();
    let closes = 0, launches = 0;
    vi.spyOn(manager, "close").mockImplementation(async () => {
      closes++; await new Promise((r) => setTimeout(r, 10));
    });
    vi.spyOn(manager, "launch").mockImplementation(async () => {
      launches++; await new Promise((r) => setTimeout(r, 10));
    });

    // Five tabs recovering from a dead browser at once must share ONE
    // close+relaunch, not stomp each other's freshly launched browser.
    await Promise.all([0, 1, 2, 3, 4].map(() => manager.recoverDeadBrowser(true, "t")));
    expect(closes).toBe(1);
    expect(launches).toBe(1);

    // A later, separate recovery runs fresh (the in-flight promise was cleared).
    await manager.recoverDeadBrowser(true, "t");
    expect(closes).toBe(2);
    expect(launches).toBe(2);
  });

  it("concurrent releases: only the true last tab out closes the browser", async () => {
    const manager = new BrowserManager();
    let closes = 0;
    vi.spyOn(manager, "close").mockImplementation(async () => { closes++; });
    // Fake pages that take a moment to close, forcing the releases to
    // interleave at the await — the exact shape of the production race.
    const mkTab = () => ({
      page: { isClosed: () => false, close: () => new Promise((r) => setTimeout(r, 20)) },
    });
    (manager as any).tabs.set("a", mkTab());
    (manager as any).tabs.set("b", mkTab());
    (manager as any).tabs.set("c", mkTab());

    await Promise.all([
      manager.releaseTab("a"),
      manager.releaseTab("b"),
      manager.releaseTab("c"),
    ]);
    // Unserialized, every release sees an emptied map and all three "close
    // the browser"; serialized, only the genuine last one does.
    expect(closes).toBe(1);
    expect((manager as any).tabs.size).toBe(0);
  });

  it("getPage rejects when not launched", async () => {
    const manager = new BrowserManager();
    await expect(manager.getPage()).rejects.toThrow("not launched");
  });

  it("getContext throws when not launched", () => {
    const manager = new BrowserManager();
    expect(() => manager.getContext()).toThrow("not launched");
  });

  it("close on non-running is safe", async () => {
    const manager = new BrowserManager();
    await manager.close(); // should not throw
    expect(manager.isRunning).toBe(false);
  });

  it("has empty refs on creation", () => {
    const manager = new BrowserManager();
    expect(manager.tabState("default").refs.size).toBe(0);
  });

  it("keeps per-tab refs independent", () => {
    const manager = new BrowserManager();
    expect(manager.tabState("a").refs).not.toBe(manager.tabState("b").refs);
    expect(manager.tabState("a").refs).toBe(manager.tabState("a").refs);
  });
});

describe("TabState history", () => {
  it("pushHistory tracks urls", () => {
    const st = new BrowserManager().tabState("default");
    st.pushHistory("https://a.com");
    st.pushHistory("https://b.com");
    st.pushHistory("https://c.com");
    expect(st.history).toEqual(["https://a.com", "https://b.com", "https://c.com"]);
    expect(st.historyIndex).toBe(2);
  });

  it("pushHistory truncates forward history", () => {
    const st = new BrowserManager().tabState("default");
    st.pushHistory("https://a.com");
    st.pushHistory("https://b.com");
    st.pushHistory("https://c.com");
    st.historyIndex = 0; // simulate having gone back to a.com
    st.pushHistory("https://d.com");
    expect(st.history).toEqual(["https://a.com", "https://d.com"]);
    expect(st.historyIndex).toBe(1);
  });

  it("history is independent per tab", () => {
    const manager = new BrowserManager();
    manager.tabState("a").pushHistory("https://a.com");
    expect(manager.tabState("b").history).toEqual([]);
  });
});

describe("BrowserManager persistent mode", () => {
  it("accepts persistent path in constructor", () => {
    const manager = new BrowserManager("/tmp/test-profile");
    expect(manager.isRunning).toBe(false);
  });

  it("defaults persistent to null", () => {
    const manager = new BrowserManager();
    expect(manager.isRunning).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Tab lifecycle: close isolation, reopen, and switch history semantics.
// In-memory fake pages stand in for Playwright, so no browser or network.
// ---------------------------------------------------------------------------

const URL_A1 = "data:text/html,<h1>A1</h1>";
const URL_A2 = "data:text/html,<h1>A2</h1>";
const URL_A3 = "data:text/html,<h1>A3</h1>";
const URL_B1 = "data:text/html,<h1>B1</h1>";
const URL_B2 = "data:text/html,<h1>B2</h1>";

class FakePage {
  private currentUrl = "about:blank";
  private closed = false;
  constructor(private ctx: FakeContext) {}
  url() { return this.currentUrl; }
  isClosed() { return this.closed; }
  async goto(url: string) { this.currentUrl = url; }
  async close() {
    this.closed = true;
    this.ctx.remove(this);
  }
  async bringToFront() {}
}

class FakeContext {
  private all: FakePage[] = [];
  async newPage(): Promise<FakePage> {
    const page = new FakePage(this);
    this.all.push(page);
    return page;
  }
  pages(): FakePage[] { return [...this.all]; }
  remove(page: FakePage) { this.all = this.all.filter((p) => p !== page); }
}

function managerWithContext(): BrowserManager {
  const manager = new BrowserManager();
  (manager as any).context = new FakeContext();
  return manager;
}

// Mimic the open command: (re)create the tab's page and record history.
async function openTab(manager: BrowserManager, tab: string, url: string): Promise<FakePage> {
  const page = (await manager.getPage(tab, true)) as FakePage;
  await page.goto(url);
  manager.tabState(tab).pushHistory(page.url());
  return page;
}

describe("tab close isolation", () => {
  it("closing one tab preserves the other tab's page, refs and history", async () => {
    const manager = managerWithContext();
    const pageA = await openTab(manager, "a", URL_A1);
    await openTab(manager, "a", URL_A2);
    const pageB = await openTab(manager, "b", URL_B1);
    await openTab(manager, "b", URL_B2);

    await manager.releaseTab("a");

    expect(pageA.isClosed()).toBe(true);
    const stB = manager.tabState("b");
    expect(stB.page).toBe(pageB);
    expect(pageB.isClosed()).toBe(false);
    expect(stB.history).toEqual([URL_B1, URL_B2]);
    expect(stB.historyIndex).toBe(1);
    expect(await manager.goBack("b")).toBe(URL_B1);
    expect(pageB.url()).toBe(URL_B1);
  });

  it("close on a tab that never opened a page is a successful no-op", async () => {
    const manager = managerWithContext();
    const pageB = await openTab(manager, "b", URL_B1);

    await manager.releaseTab("ghost");
    await manager.releaseTab("ghost"); // idempotent
    expect((manager as any).context).not.toBeNull();
    expect(manager.tabState("b").page).toBe(pageB);
    expect(manager.tabState("b").history).toEqual([URL_B1]);
  });

  it("closing the last live tab shuts the browser down", async () => {
    const manager = managerWithContext();
    const page = await openTab(manager, "solo", URL_A1);

    await manager.releaseTab("solo");

    expect(page.isClosed()).toBe(true);
    expect(manager.isRunning).toBe(false);
    expect((manager as any).tabs.size).toBe(0);
  });
});

describe("reopening a closed tab name", () => {
  it("starts with blank history: back/forward return null", async () => {
    const manager = managerWithContext();
    await openTab(manager, "spectator", URL_B1); // keeps the browser alive
    const oldPage = await openTab(manager, "worker", URL_A1);
    await openTab(manager, "worker", URL_A2);
    expect(await manager.goBack("worker")).toBe(URL_A1);

    await manager.releaseTab("worker");
    expect(oldPage.isClosed()).toBe(true);
    expect((manager as any).tabs.has("worker")).toBe(false);

    const newPage = await openTab(manager, "worker", URL_B1);
    expect(newPage).not.toBe(oldPage);

    const st = manager.tabState("worker");
    expect(st.history).toEqual([URL_B1]);
    expect(st.historyIndex).toBe(0);
    expect(await manager.goBack("worker")).toBeNull();
    expect(await manager.goForward("worker")).toBeNull();
  });

  it("gets a fresh ref registry", async () => {
    const manager = managerWithContext();
    await openTab(manager, "spectator", URL_B1);
    await openTab(manager, "t", URL_A1);
    manager.tabState("t").refs.buildFromSnapshot('- button "Go"');
    expect(manager.tabState("t").refs.size).toBe(1);

    await manager.releaseTab("t");
    await openTab(manager, "t", URL_B1);

    expect(manager.tabState("t").refs.size).toBe(0);
  });

  it("never resurrects URLs from the previous lifecycle", async () => {
    const manager = managerWithContext();
    await openTab(manager, "spectator", URL_B1);
    await openTab(manager, "w", URL_A1);
    await openTab(manager, "w", URL_A2);
    await openTab(manager, "w", URL_A3);
    await manager.releaseTab("w");

    await openTab(manager, "w", URL_B1);
    await openTab(manager, "w", URL_B2);
    const history = manager.tabState("w").history;
    expect(history).toEqual([URL_B1, URL_B2]);
    expect(history.some((u) => u.startsWith("data:text/html,<h1>A"))).toBe(false);
  });
});

describe("switch tab history isolation", () => {
  it("resets the adopting tab to a single entry and drops stale refs", async () => {
    const manager = managerWithContext();
    const pageB = await openTab(manager, "beta", URL_B1);
    await openTab(manager, "beta", URL_B2);
    const pageA = await openTab(manager, "alpha", URL_A1);
    await openTab(manager, "alpha", URL_A2);
    manager.tabState("alpha").refs.buildFromSnapshot('- button "Old"');

    const index = manager.getContext().pages().indexOf(pageB);
    await manager.switchToTab("alpha", index);

    const stA = manager.tabState("alpha");
    expect(stA.page).toBe(pageB);
    expect(stA.history).toEqual([URL_B2]);
    expect(stA.historyIndex).toBe(0);
    expect(stA.refs.size).toBe(0);
    expect(await manager.goBack("alpha")).toBeNull();
    expect(await manager.goForward("alpha")).toBeNull();
    // The old page stays open; only the pointer moved.
    expect(pageA.isClosed()).toBe(false);
  });

  it("does not pollute the other tab's page or history", async () => {
    const manager = managerWithContext();
    const pageB = await openTab(manager, "beta", URL_B1);
    await openTab(manager, "beta", URL_B2);
    await openTab(manager, "alpha", URL_A1);
    await openTab(manager, "alpha", URL_A2);

    const index = manager.getContext().pages().indexOf(pageB);
    await manager.switchToTab("alpha", index);

    const stB = manager.tabState("beta");
    expect(stB.page).toBe(pageB);
    expect(stB.history).toEqual([URL_B1, URL_B2]);
    expect(stB.historyIndex).toBe(1);
    // beta still walks its own history after alpha switched onto its page.
    expect(await manager.goBack("beta")).toBe(URL_B1);
    expect(pageB.url()).toBe(URL_B1);
    expect(manager.tabState("alpha").history).toEqual([URL_B2]);
  });

  it("navigation after switch cannot contaminate the other tab", async () => {
    const manager = managerWithContext();
    const pageB = await openTab(manager, "beta", URL_B1);
    await openTab(manager, "beta", URL_B2);
    await openTab(manager, "alpha", URL_A1);

    const index = manager.getContext().pages().indexOf(pageB);
    await manager.switchToTab("alpha", index);
    await openTab(manager, "alpha", URL_A3);

    expect(manager.tabState("alpha").history).toEqual([URL_B2, URL_A3]);
    expect(manager.tabState("beta").history).toEqual([URL_B1, URL_B2]);
    expect(manager.tabState("beta").historyIndex).toBe(1);
  });

  it("back/forward fail until a new navigation creates a step", async () => {
    const manager = managerWithContext();
    const pageB = await openTab(manager, "beta", URL_B1);
    await openTab(manager, "alpha", URL_A1);

    const index = manager.getContext().pages().indexOf(pageB);
    await manager.switchToTab("alpha", index);
    expect(await manager.goBack("alpha")).toBeNull();
    expect(await manager.goForward("alpha")).toBeNull();

    await openTab(manager, "alpha", URL_A2);
    expect(await manager.goBack("alpha")).toBe(URL_B1);
    expect(await manager.goForward("alpha")).toBe(URL_A2);
  });
});
