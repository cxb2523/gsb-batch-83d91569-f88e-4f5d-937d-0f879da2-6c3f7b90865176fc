import React from "react";
import { afterEach, describe, expect, test, vi } from "vitest";
import { renderToString } from "react-dom/server";
import { createRoot } from "react-dom/client";
import { act } from "react";
import { JSDOM } from "jsdom";
import { AppShell } from "../../apps/frontend/src/App";
import { fakeApiClient } from "./fakeApiClient";

describe("frontend shell", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  test("renders artwork gallery grouped by date heading and opens detail content", () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-09-15T12:00:00"));
    const html = renderToString(
      <AppShell
        apiBaseUrl="http://127.0.0.1:1234"
        initialState={{
          status: "ready",
          releases: [
            {
              id: "p4",
              title: "Persona 4 Revival",
              dateText: "Feb 18, 2027",
              releaseDate: "2027-02-18",
              datePrecision: "Exact",
              effectiveSortDate: "2027-02-18",
              category: "Remake",
              publishers: ["Atlus"],
              developers: ["Atlus Studio"],
              platforms: ["PC", "Xbox Series X|S"],
              sourceConfidence: 90,
              artworks: [{ imageId: "art-a" }]
            }
          ],
          syncStatus: { status: "success", added: 1, repaired: 0, skipped: 0, failed: 0 }
        }}
      />
    );

    expect(html).toContain("Game Release Tracker");
    expect(html).toContain("February 2027");
    expect(html).toContain("Persona 4 Revival");
    expect(html).toContain("https://images.igdb.com/igdb/image/upload/t_screenshot_med/art-a.jpg");
    expect(html).toContain("release-row__cover");
    expect(html).toContain("upcoming-feature");
    expect(html).toContain("Atlus. Remake. PC, Xbox Series X|S");
    expect(html).toContain("Sync now");
    expect(html).toContain("Add game");
    expect(html).toContain("More filters");
  });

  test("Upcoming uses a medium blurred fill and keeps sharp artwork at full size", () => {
    const html = renderToString(<AppShell apiBaseUrl="http://127.0.0.1:1234" initialState={{
      status: "ready", releases: [{ ...releaseListItem("art", "Art Game"), artworks: [{ imageId: "wide-art", source: "artwork" }] }],
      syncStatus: { status: "idle", added: 0, repaired: 0, skipped: 0, failed: 0 }
    }} />);
    expect(html).toContain('class="backdrop__fill" src="https://images.igdb.com/igdb/image/upload/t_screenshot_med/wide-art.jpg"');
    expect(html).toContain('class="backdrop__img backdrop__img--current" src="https://images.igdb.com/igdb/image/upload/t_1080p/wide-art.jpg"');
  });

  test("Upcoming uses a medium image when a cover becomes its blurred backdrop", () => {
    const html = renderToString(<AppShell apiBaseUrl="http://127.0.0.1:1234" initialState={{
      status: "ready", releases: [{ ...releaseListItem("cover", "Cover Game"), artworks: [{ imageId: "cover-art", source: "cover" }] }],
      syncStatus: { status: "idle", added: 0, repaired: 0, skipped: 0, failed: 0 }
    }} />);
    expect(html).toContain('class="backdrop backdrop--blur"');
    expect(html).toContain('class="backdrop__img backdrop__img--current" src="https://images.igdb.com/igdb/image/upload/t_screenshot_med/cover-art.jpg"');
    expect(html).toContain('class="upcoming-feature__cover"><img src="https://images.igdb.com/igdb/image/upload/t_cover_big/cover-art.jpg"');
  });

  test("does not render ineligible releases supplied by stale state", () => {
    const html = renderToString(
      <AppShell
        apiBaseUrl="http://127.0.0.1:1234"
        initialState={{
          status: "ready",
          releases: [
            {
              id: "old",
              title: "Old Game",
              dateText: "2025",
              releaseDate: "2025-01-01",
              datePrecision: "Year",
              effectiveSortDate: "2025-01-01",
              category: "Main",
              publishers: ["Atlus"],
              developers: [],
              platforms: ["PC"],
              sourceConfidence: 90,
              eligible: false,
              artworks: []
            }
          ],
          syncStatus: { status: "success", added: 0, repaired: 0, skipped: 0, failed: 0 }
        }}
      />
    );

    expect(html).not.toContain("Old Game");
  });

  test("debounced query helper only fires once for rapid changes", async () => {
    vi.useFakeTimers();
    const { createDebounced } = await import("../../apps/frontend/src/api/debounce");
    const calls: string[] = [];
    const debounced = createDebounced((value: string) => calls.push(value), 250);

    debounced("p");
    debounced("pe");
    debounced("persona");
    vi.advanceTimersByTime(249);
    expect(calls).toEqual([]);
    vi.advanceTimersByTime(1);
    expect(calls).toEqual(["persona"]);
    vi.useRealTimers();
  });

  test("API client sends a valid JSON body for Sync Now", async () => {
    const calls: RequestInit[] = [];
    vi.stubGlobal("fetch", vi.fn(async (_url: string, init?: RequestInit) => {
      calls.push(init ?? {});
      return new Response(JSON.stringify({ status: "success", added: 0, repaired: 0, skipped: 0, failed: 0 }), { status: 200 });
    }));
    const { createApiClient } = await import("../../apps/frontend/src/api/client");

    await createApiClient("http://127.0.0.1:1234").syncNow();

    expect(calls[0].method).toBe("POST");
    expect(calls[0].body).toBe("{}");
    expect(calls[0].headers).toEqual({ "Content-Type": "application/json" });
    vi.unstubAllGlobals();
  });

  test("API client sends the app token on every request, with or without a body", async () => {
    const calls: RequestInit[] = [];
    vi.stubGlobal("fetch", vi.fn(async (_url: string, init?: RequestInit) => {
      calls.push(init ?? {});
      return new Response(JSON.stringify({ ok: true, status: "success", added: 0, repaired: 0, skipped: 0, failed: 0 }), { status: 200 });
    }));
    const { createApiClient } = await import("../../apps/frontend/src/api/client");
    const api = createApiClient("http://127.0.0.1:1234", "launch-token");

    await api.syncNow();
    await api.deleteRelease("manual-1", false);

    expect(calls[0].headers).toEqual({ "Content-Type": "application/json", "x-grt-token": "launch-token" });
    expect(calls[1].headers).toEqual({ "x-grt-token": "launch-token" });
    vi.unstubAllGlobals();
  });

  test("API client does not send JSON content-type for bodyless delete requests", async () => {
    const calls: RequestInit[] = [];
    vi.stubGlobal("fetch", vi.fn(async (_url: string, init?: RequestInit) => {
      calls.push(init ?? {});
      return new Response(JSON.stringify({ ok: true }), { status: 200 });
    }));
    const { createApiClient } = await import("../../apps/frontend/src/api/client");

    await createApiClient("http://127.0.0.1:1234").deleteRelease("manual-1", false);

    expect(calls[0].method).toBe("DELETE");
    expect(calls[0].body).toBeUndefined();
    expect(calls[0].headers).toBeUndefined();
    vi.unstubAllGlobals();
  });

  test("API client surfaces backend error bodies", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ error: "Title is required" }), {
      status: 400,
      statusText: "Bad Request"
    })));
    const { createApiClient } = await import("../../apps/frontend/src/api/client");

    await expect(createApiClient("http://127.0.0.1:1234").createManualRelease({})).rejects.toThrow("400 Bad Request: Title is required");
    vi.unstubAllGlobals();
  });

  test("API client deletes completed games without a JSON body", async () => {
    const calls: Array<{ url: string; init: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init: init ?? {} });
      return new Response(JSON.stringify({ ok: true }), { status: 200 });
    }));
    const { createApiClient } = await import("../../apps/frontend/src/api/client");

    await createApiClient("http://127.0.0.1:1234").deleteCompletedGame("completed-bloodborne-pc");

    expect(calls[0].url).toBe("http://127.0.0.1:1234/api/completed-games/completed-bloodborne-pc");
    expect(calls[0].init.method).toBe("DELETE");
    expect(calls[0].init.body).toBeUndefined();
    expect(calls[0].init.headers).toBeUndefined();
    vi.unstubAllGlobals();
  });

  test("settings view shows credential status without exposing saved secrets", () => {
    const html = renderToString(
      <AppShell
        apiBaseUrl="http://127.0.0.1:1234"
        initialState={{
          status: "ready",
          releases: [],
          syncStatus: { status: "failed", added: 0, repaired: 0, skipped: 0, failed: 1, message: "IGDB companies failed: 401" },
          settingsStatus: {
            credentialStatus: { status: "expired-or-rejected", message: "IGDB companies failed: 401" },
            credentials: {
              IGDB_CLIENT_ID: { saved: true },
              IGDB_CLIENT_SECRET: { saved: true },
              IGDB_ACCESS_TOKEN: { saved: true },
              STEAMGRIDDB_API_KEY: { saved: true }
            },
            autoSyncDue: true
          },
          initialView: "settings"
        }}
      />
    );

    expect(html).toContain("expired-or-rejected");
    expect(html).toContain("IGDB companies failed: 401");
    expect(html).toContain("Client ID saved");
    expect(html).toContain("SteamGridDB key saved");
    expect(html).not.toContain("7zjrfr");
    expect(html).not.toContain("sgdb-secret");
  });

  test("settings view asks for a key again when its saved copy can no longer be read", () => {
    const html = renderToString(
      <AppShell
        apiBaseUrl="http://127.0.0.1:1234"
        initialState={{
          status: "ready",
          releases: [],
          syncStatus: { status: "idle", added: 0, repaired: 0, skipped: 0, failed: 0 },
          settingsStatus: {
            credentialStatus: { status: "missing" },
            credentials: {
              IGDB_CLIENT_ID: { saved: true },
              IGDB_CLIENT_SECRET: { saved: false, unreadable: true },
              IGDB_ACCESS_TOKEN: { saved: false },
              STEAMGRIDDB_API_KEY: { saved: false }
            },
            autoSyncDue: false
          },
          initialView: "settings"
        }}
      />
    );

    expect(html).toContain("Client secret can no longer be read - enter it again");
    expect(html).toContain("Access token not saved");
  });

  test("add game view renders manual fields", () => {
    const html = renderToString(
      <AppShell
        apiBaseUrl="http://127.0.0.1:1234"
        initialState={{
          status: "ready",
          releases: [],
          syncStatus: { status: "idle", added: 0, repaired: 0, skipped: 0, failed: 0 },
          initialView: "add"
        }}
      />
    );

    expect(html).toContain("Add manual game");
    expect(html).toContain("Title");
    expect(html).toContain("Publishers");
    expect(html).toContain("Search IGDB");
    expect(html).toContain("Save game");
  });

  test("manual IGDB candidate mapping keeps media fields for save", async () => {
    const { manualGameFromCandidate } = await import("../../apps/frontend/src/useReleaseManualGameWorkflow");

    expect(manualGameFromCandidate({
      igdbId: 19560,
      title: "Bloodborne",
      publishers: ["Sony Interactive Entertainment"],
      developers: ["FromSoftware"],
      platforms: ["PC"],
      category: "Main",
      dateText: "Dec 31, 2026",
      datePrecision: "Exact",
      releaseDate: "2026-12-31",
      releaseWindow: null,
      sourceUrl: "https://www.igdb.com/games/bloodborne",
      coverImageId: "cover-bloodborne",
      artworks: [{ imageId: "art-bloodborne", source: "artwork" }, { imageId: "cover-bloodborne", source: "cover" }],
      screenshots: [{ imageId: "shot-bloodborne", source: "artwork" }],
      trailers: [{ videoId: "gameplay123", name: "Gameplay Trailer", provider: "youtube" }]
    })).toMatchObject({
      igdbId: 19560,
      title: "Bloodborne",
      artworks: [{ imageId: "art-bloodborne", source: "artwork" }, { imageId: "cover-bloodborne", source: "cover" }],
      screenshots: [{ imageId: "shot-bloodborne", source: "artwork" }],
      trailers: [{ videoId: "gameplay123", name: "Gameplay Trailer", provider: "youtube" }]
    });
  });

  test("completed library renders grouped and undated game cards", () => {
    const html = renderToString(
      <AppShell
        apiBaseUrl="http://127.0.0.1:1234"
        initialState={{
          status: "ready",
          releases: [],
          syncStatus: { status: "idle", added: 0, repaired: 0, skipped: 0, failed: 0 },
          initialView: "completed-library",
          completedLibraryStatus: "ready",
          completedGames: [
            completedItem("skyfall", "Skyfall Tactics", "2026-01", "exact"),
            { ...completedItem("undated", "Undated Game", null, "none"), completionDate: null, completionYear: null }
          ]
        }}
      />
    );

    expect(html).toContain("Completed Library");
    expect(html).toContain("January 2026");
    expect(html).toContain("Undated Completed Games");
    expect(html).toContain("Skyfall Tactics");
    expect(html).toContain("finished 7 Jan");
    expect(html).toContain("https://images.igdb.com/igdb/image/upload/t_cover_big/cover-skyfall.jpg");
    expect(html).toContain("https://images.igdb.com/igdb/image/upload/t_cover_big_2x/cover-skyfall.jpg 528w");
    expect(html).toContain('sizes="132px"');
    expect(html).toContain("completed-grid");
  });

  test("genre filters narrow upcoming releases and completed games", async () => {
    const { container, cleanup } = await renderInteractive(
      <AppShell
        apiBaseUrl="http://127.0.0.1:1234"
        initialState={{
          status: "ready",
          releases: [
            { ...releaseListItem("p4", "Persona 4 Revival"), genres: ["Role-playing (RPG)"] },
            { ...releaseListItem("doom", "Doom Next"), genres: ["Shooter"] }
          ],
          syncStatus: { status: "idle", added: 0, repaired: 0, skipped: 0, failed: 0 },
          completedLibraryStatus: "ready",
          completedGames: [
            completedItem("skyfall", "Skyfall Tactics", "2026-01", "exact"),
            { ...completedItem("racer", "Neon Racer", "2026-02", "exact"), genres: [], igdbGenres: ["Racing"] }
          ]
        }}
      />
    );
    const chooseGenre = async (value: string) => {
      const select = [...container.querySelectorAll("select")].find(item => item.querySelector("option")?.textContent === "All genres") as HTMLSelectElement;
      await act(async () => {
        const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(select), "value")?.set;
        setter?.call(select, value);
        select.dispatchEvent(new select.ownerDocument.defaultView!.Event("change", { bubbles: true }));
      });
    };

    expect(container.querySelectorAll(".release-row")).toHaveLength(2);
    await chooseGenre("Shooter");
    expect([...container.querySelectorAll(".release-row strong")].map(item => item.textContent)).toEqual(["Doom Next"]);

    await act(async () => {
      getButton(container, "Completed Library").click();
    });
    expect(container.querySelectorAll(".completed-card")).toHaveLength(2);
    await chooseGenre("Racing");
    expect([...container.querySelectorAll(".completed-card__title")].map(item => item.textContent)).toEqual(["Neon Racer"]);
    await cleanup();
  });

  test("an injected ApiClient drives the app, and artwork edits adopt the returned release without refetching", async () => {
    const detail = { ...releaseDetail("p4", "Persona 4 Revival"), artworks: [{ imageId: "hero", source: "artwork" as const }, { imageId: "next", source: "artwork" as const }] };
    const api = fakeApiClient({
      reorderArtworks: async (_id, ids) => ({ ok: true, item: { ...detail, artworks: ids.map(imageId => ({ imageId, source: "artwork" as const })) } })
    });
    const { container, cleanup } = await renderInteractive(
      <AppShell apiBaseUrl="http://unused" api={api} initialState={{ status: "ready", releases: [releaseListItem("p4", "Persona 4 Revival")], syncStatus: { status: "idle", added: 0, repaired: 0, skipped: 0, failed: 0 }, initialView: "detail", initialDetail: detail }} />
    );

    await act(async () => getButton(container, "Move next to hero").click());

    expect(api.reorderArtworks).toHaveBeenCalledWith("p4", ["next", "hero"]);
    expect(api.getRelease).not.toHaveBeenCalled();
    expect(api.listReleases).toHaveBeenCalledTimes(1);
    await cleanup();
  });

  test("list reloads fetch only the list; sync status loads once at startup", async () => {
    const api = fakeApiClient({ syncNow: async () => ({ status: "success", added: 1, repaired: 0, skipped: 0, failed: 0 }) });
    const { container, cleanup } = await renderInteractive(<AppShell apiBaseUrl="http://unused" api={api} />);

    await act(async () => getButton(container, "Sync now").click());

    expect(api.syncNow).toHaveBeenCalledTimes(1);
    expect(api.listReleases).toHaveBeenCalledTimes(2);
    expect(api.getSyncStatus).toHaveBeenCalledTimes(1);
    expect(api.getSettings).not.toHaveBeenCalled();
    expect(api.listCompletedGames).not.toHaveBeenCalled();
    await cleanup();
  });

  test("a partial sync the user started reloads the list with the games it saved", async () => {
    let saved = false;
    const api = fakeApiClient({
      listReleases: async () => (saved
        ? { items: [releaseListItem("p4", "Persona 4 Revival")], truncated: false, total: 1 }
        : { items: [], truncated: false, total: 0 }),
      syncNow: async () => {
        saved = true;
        return { status: "partial", added: 1, repaired: 0, skipped: 0, failed: 1 };
      }
    });
    const { container, cleanup } = await renderInteractive(<AppShell apiBaseUrl="http://unused" api={api} />);

    await act(async () => getButton(container, "Sync now").click());

    expect(container.textContent).toContain("Persona 4 Revival");
    await cleanup();
  });

  test("Completed Library and Settings load on their first open only", async () => {
    const api = fakeApiClient();
    const { container, cleanup } = await renderInteractive(<AppShell apiBaseUrl="http://unused" api={api} />);
    expect(api.listCompletedGames).not.toHaveBeenCalled();
    expect(api.getSettings).not.toHaveBeenCalled();

    await act(async () => getButton(container, "Completed Library").click());
    expect(api.listCompletedGames).toHaveBeenCalledTimes(1);
    expect(api.getSettings).not.toHaveBeenCalled();
    await act(async () => getButton(container, "Upcoming").click());
    await act(async () => getButton(container, "Completed Library").click());
    expect(api.listCompletedGames).toHaveBeenCalledTimes(1);

    await act(async () => getButton(container, "Settings").click());
    expect(api.getSettings).toHaveBeenCalledTimes(1);
    await act(async () => getButton(container, "Upcoming").click());
    await act(async () => getButton(container, "Settings").click());
    expect(api.getSettings).toHaveBeenCalledTimes(1);
    await cleanup();
  });

  test("a startup auto-sync is followed until it finishes, then the list reloads", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    let checks = 0;
    const api = fakeApiClient({
      getSyncStatus: async () => ({ status: ++checks === 1 ? "running" as const : "success" as const, added: 2, repaired: 0, skipped: 0, failed: 0 })
    });
    const { cleanup } = await renderInteractive(<AppShell apiBaseUrl="http://unused" api={api} />);
    expect(api.listReleases).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });

    expect(api.getSyncStatus).toHaveBeenCalledTimes(2);
    expect(api.listReleases).toHaveBeenCalledTimes(2);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000);
    });
    expect(api.getSyncStatus).toHaveBeenCalledTimes(2);
    vi.useRealTimers();
    await cleanup();
  });

  test("settings has no Excel import any more", () => {
    const html = renderToString(
      <AppShell
        apiBaseUrl="http://127.0.0.1:1234"
        initialState={{
          status: "ready",
          releases: [],
          syncStatus: { status: "idle", added: 0, repaired: 0, skipped: 0, failed: 0 },
          initialView: "settings"
        }}
      />
    );

    expect(html).not.toContain("Excel");
    expect(html).not.toContain("Sync Library");
  });

  test("side navigation opens distinct tabs instead of redirecting everything to upcoming", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-09-15T12:00:00"));
    const { container, cleanup } = await renderInteractive(
      <AppShell
        apiBaseUrl="http://127.0.0.1:1234"
        initialState={{
          status: "ready",
          releases: [releaseListItem("p4", "Persona 4 Revival")],
          syncStatus: { status: "idle", added: 0, repaired: 0, skipped: 0, failed: 0 }
        }}
      />
    );

    await act(async () => {
      getButton(container, "Calendar").click();
    });
    expect(container.querySelector(".tab-panel")?.textContent).toContain("September 2026");
    expect(container.querySelector(".side-nav button.active")?.textContent).toBe("Calendar");

    const navLabels = [...container.querySelectorAll(".side-nav button")].map(button => button.textContent);
    expect(navLabels).toEqual(["Upcoming", "Calendar", "Completed Library", "Randomizer", "Year in Review", "Settings"]);

    await act(async () => {
      getButton(container, "Upcoming").click();
    });
    await act(async () => {
      getButton(container, "Add game").click();
    });
    expect(container.textContent).toContain("Add manual game");
    await cleanup();
  });

  test("completed detail shows IGDB summary and screenshots", () => {
    const html = renderToString(
      <AppShell
        apiBaseUrl="http://127.0.0.1:1234"
        initialState={{
          status: "ready",
          releases: [],
          syncStatus: { status: "idle", added: 0, repaired: 0, skipped: 0, failed: 0 },
          initialView: "completed-detail",
          completedLibraryStatus: "ready",
          completedGames: [],
          initialCompletedDetail: {
            ...completedItem("detail", "Wired Heart", "2026-01", "exact"),
            extra: { Mood: "Excellent" },
            igdbReleaseDate: "2024-04-01",
            igdbDeveloper: "Lumen Co",
            igdbPublisher: "Lumen Co",
            igdbGenres: ["Adventure"],
            igdbPlatforms: ["PC"],
            summary: "A neon mystery adventure from IGDB.",
            notes: "Finished the true ending.",
            screenshots: [{ imageId: "shot-a", source: "artwork" }]
          }
        }}
      />
    );

    expect(html).toContain("A neon mystery adventure from IGDB.");
    expect(html).toContain("Finished the true ending.");
    expect(html).toContain("07 01 2026");
    expect(html).not.toContain("My note");
    expect(html).toContain("https://images.igdb.com/igdb/image/upload/t_screenshot_med/shot-a.jpg");
    expect(html).toContain("Extra fields");
    expect(html).toContain("Fix match");
  });

  test("completed manual form asks for day month year completion dates", async () => {
    const { container, cleanup } = await renderInteractive(
      <AppShell
        apiBaseUrl="http://127.0.0.1:1234"
        initialState={{
          status: "ready",
          releases: [],
          syncStatus: { status: "idle", added: 0, repaired: 0, skipped: 0, failed: 0 },
          initialView: "completed-library",
          completedLibraryStatus: "ready",
          completedGames: []
        }}
      />
    );

    await act(async () => {
      getButton(container, "Add completed game").click();
    });

    expect(container.textContent).toContain("Add completed game");
    expect(container.querySelector("input[placeholder='DD MM YYYY']")).not.toBeNull();
    await cleanup();
  });

  test("completed manual form searches IGDB and saves the selected match with personal fields", async () => {
    const bloodborne = {
      ...completedItem("completed-bloodborne-pc", "Bloodborne", "2026-07", "exact"),
      userPlatform: "PC",
      completionDate: "2026-07-17",
      ratingRaw: "9/10",
      notes: "Great combat.",
      extra: {},
      igdbGenres: [],
      igdbPlatforms: [],
      screenshots: []
    };
    const api = fakeApiClient({
      searchManualCompletedCandidates: async () => ({ items: [{ igdbId: 19560, title: "Bloodborne", platforms: ["PlayStation 4"], releaseDate: "2015-03-24", confidence: 95, coverImageId: "cover-bb" }] as never }),
      createManualCompletedGame: async () => ({ ok: true, item: bloodborne })
    });
    const { container, cleanup } = await renderInteractive(
      <AppShell
        apiBaseUrl="http://127.0.0.1:1234"
        api={api}
        initialState={{
          status: "ready",
          releases: [],
          syncStatus: { status: "idle", added: 0, repaired: 0, skipped: 0, failed: 0 },
          initialView: "completed-library",
          completedLibraryStatus: "ready",
          completedGames: []
        }}
      />
    );

    await act(async () => { getButton(container, "Add completed game").click(); });
    await act(async () => {
      setInputValue(container.querySelector("input[aria-label='Completed game title']")!, "Bloodborne");
      setInputValue(container.querySelector("input[aria-label='Completed game platform']")!, "PC");
      setInputValue(container.querySelector("input[aria-label='Completed game rating']")!, "9/10");
      setInputValue(container.querySelector("input[aria-label='Completed game completion date']")!, "17 07 2026");
      setInputValue(container.querySelector("textarea[aria-label='Completed game notes']")!, "Great combat.");
    });
    await act(async () => { getButton(container, "Search IGDB").click(); });
    expect(container.querySelector(".manual-candidate")?.textContent).toContain("Bloodborne");
    await act(async () => { (container.querySelector(".manual-candidate") as HTMLButtonElement).click(); });
    await act(async () => { getButton(container, "Save completed game").click(); });

    expect(api.searchManualCompletedCandidates).toHaveBeenCalledWith({ title: "Bloodborne", userPlatform: "PC", completionYear: 2026 });
    expect(api.createManualCompletedGame).toHaveBeenCalledWith(expect.objectContaining({ igdbId: 19560, title: "Bloodborne", userPlatform: "PC", ratingRaw: "9/10", completionDate: "17 07 2026", notes: "Great combat." }));
    await cleanup();
  });

  test("completed manual form saves all entered fields and reloads into the month group", async () => {
    const elliot = {
      ...completedItem("completed-adventure-of-elliot-pc", "Adventure of Elliot", "2026-07", "exact"),
      completionDate: "2026-07-17",
      userPlatform: "PC",
      ratingRaw: "8/10"
    };
    const api = fakeApiClient({
      createManualCompletedGame: async () => ({ ok: true, item: { ...elliot, notes: "Loved the demo.", extra: {}, igdbGenres: [], igdbPlatforms: [], screenshots: [] } }),
      listCompletedGames: async () => ({ items: [elliot], total: 1 })
    });
    const { container, cleanup } = await renderInteractive(
      <AppShell
        apiBaseUrl="http://127.0.0.1:1234"
        api={api}
        initialState={{
          status: "ready",
          releases: [],
          syncStatus: { status: "idle", added: 0, repaired: 0, skipped: 0, failed: 0 },
          initialView: "completed-library",
          completedLibraryStatus: "ready",
          completedGames: []
        }}
      />
    );

    await act(async () => {
      getButton(container, "Add completed game").click();
    });
    await act(async () => {
      setInputValue(container.querySelector("input[aria-label='Completed game title']")!, "Adventure of Elliot");
      setInputValue(container.querySelector("input[aria-label='Completed game platform']")!, "PC");
      setInputValue(container.querySelector("input[aria-label='Completed game rating']")!, "8/10");
      setInputValue(container.querySelector("input[aria-label='Completed game completion date']")!, "17 07 2026");
      setInputValue(container.querySelector("textarea[aria-label='Completed game notes']")!, "Loved the demo.");
    });

    await act(async () => {
      getButton(container, "Save completed game").click();
    });

    expect(api.createManualCompletedGame).toHaveBeenCalledWith(expect.objectContaining({
      title: "Adventure of Elliot",
      userPlatform: "PC",
      ratingRaw: "8/10",
      completionDate: "17 07 2026",
      notes: "Loved the demo."
    }));

    await act(async () => {
      getButton(container, "← back to library").click();
    });

    expect(container.textContent).toContain("July 2026");
    expect(container.textContent).toContain("Adventure of Elliot");
    expect(container.textContent).toContain("finished 17 Jul");
    await cleanup();
  });

  test("completed detail can load and save a manual IGDB match", async () => {
    const api = fakeApiClient({
      getCompletedMatchCandidates: async () => ({ items: [{ igdbId: 19560, title: "Bloodborne", platforms: ["PlayStation 4"], releaseDate: "2015-03-24", confidence: 95, coverImageId: "cover-bb" }] as never }),
      saveCompletedMatch: async () => ({
        ok: true,
        item: {
          ...completedItem("bloodborne", "Bloodborne", "2026-12", "exact"),
          igdbId: 19560,
          matchStatus: "matched",
          coverImageId: "cover-bb",
          extra: {},
          igdbGenres: ["Action"],
          igdbPlatforms: ["PlayStation 4"],
          screenshots: [],
          summary: "Hunt your nightmares."
        }
      })
    });
    const { container, cleanup } = await renderInteractive(
      <AppShell
        apiBaseUrl="http://127.0.0.1:1234"
        api={api}
        initialState={{
          status: "ready",
          releases: [],
          syncStatus: { status: "idle", added: 0, repaired: 0, skipped: 0, failed: 0 },
          initialView: "completed-detail",
          completedLibraryStatus: "ready",
          completedGames: [],
          initialCompletedDetail: {
            ...completedItem("bloodborne", "Bloodborne", "2026-12", "exact"),
            matchStatus: "needsReview",
            extra: {},
            igdbGenres: [],
            igdbPlatforms: [],
            screenshots: []
          }
        }}
      />
    );
    await act(async () => {
      getButton(container, "Fix match").click();
    });
    expect(container.textContent).toContain("Bloodborne");
    expect(container.textContent).toContain("95%");

    await act(async () => {
      await Promise.resolve();
    });

    expect(api.getCompletedMatchCandidates).toHaveBeenCalledWith("bloodborne");
    expect(api.saveCompletedMatch).toHaveBeenCalledWith("bloodborne", 19560);
    expect(container.textContent).toContain("Applied");
    expect(container.textContent).toContain("IGDB #19560");
    expect(container.textContent).toContain("Hunt your nightmares.");
    await cleanup();
  });

  test("completed media carousel starts on first screenshot and advances", async () => {
    const { container, cleanup } = await renderInteractive(
      <AppShell
        apiBaseUrl="http://127.0.0.1:1234"
        initialState={{
          status: "ready",
          releases: [],
          syncStatus: { status: "idle", added: 0, repaired: 0, skipped: 0, failed: 0 },
          initialView: "completed-detail",
          completedLibraryStatus: "ready",
          completedGames: [],
          initialCompletedDetail: {
            ...completedItem("shots", "Screenshot Game", "2026-01", "exact"),
            extra: {},
            igdbGenres: [],
            igdbPlatforms: [],
            screenshots: [
              { imageId: "shot-a", source: "artwork" },
              { imageId: "shot-b", source: "artwork" }
            ]
          }
        }}
      />
    );

    expect(container.querySelector(".completed-media-hero img")?.getAttribute("src")).toContain("t_1080p/shot-a");
    expect(container.querySelector(".completed-media-thumbs img")?.getAttribute("src")).toContain("t_screenshot_med/shot-a");
    await act(async () => {
      container.querySelector(".completed-media-gallery")?.dispatchEvent(new window.KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
    });
    expect(container.querySelector(".completed-media-hero img")?.getAttribute("src")).toContain("shot-b");
    await act(async () => {
      getButton(container, "Screenshot 1").click();
    });
    expect(container.querySelector(".completed-media-hero img")?.getAttribute("src")).toContain("shot-a");
    await act(async () => {
      container.querySelector(".completed-media-gallery")?.dispatchEvent(new window.KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
    });
    expect(container.querySelector(".completed-media-hero img")?.getAttribute("src")).toContain("shot-b");
    await cleanup();
  });

  test("upcoming detail media gallery shows IGDB screenshots and advances on arrow keys", async () => {
    const { container, cleanup } = await renderInteractive(
      <AppShell
        apiBaseUrl="http://127.0.0.1:1234"
        initialState={{
          status: "ready",
          releases: [],
          syncStatus: { status: "idle", added: 0, repaired: 0, skipped: 0, failed: 0 },
          initialView: "detail",
          initialDetail: {
            ...releaseDetail("igdb-393932", "Echoes of Aincrad"),
            screenshots: [
              { imageId: "sc-1", source: "artwork" },
              { imageId: "sc-2", source: "artwork" }
            ]
          }
        }}
      />
    );

    expect(container.querySelector(".completed-media-hero img")?.getAttribute("src")).toContain("t_1080p/sc-1");
    expect(container.querySelector(".completed-media-thumbs img")?.getAttribute("src")).toContain("t_screenshot_med/sc-1");
    await act(async () => {
      container.querySelector(".completed-media-gallery")?.dispatchEvent(new window.KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
    });
    expect(container.querySelector(".completed-media-hero img")?.getAttribute("src")).toContain("t_1080p/sc-2");
    await act(async () => {
      getButton(container, "Screenshot 1").click();
    });
    expect(container.querySelector(".completed-media-hero img")?.getAttribute("src")).toContain("t_1080p/sc-1");
    await cleanup();
  });

  test("upcoming detail media gallery renders a trailer first and mounts the player only after play", async () => {
    const { container, cleanup } = await renderInteractive(
      <AppShell
        apiBaseUrl="http://127.0.0.1:1234"
        initialState={{
          status: "ready",
          releases: [],
          syncStatus: { status: "idle", added: 0, repaired: 0, skipped: 0, failed: 0 },
          initialView: "detail",
          initialDetail: {
            ...releaseDetail("igdb-393932", "Echoes of Aincrad"),
            trailers: [{ videoId: "gameplay123", name: "Gameplay Trailer", provider: "youtube" }],
            screenshots: [
              { imageId: "sc-1", source: "artwork" },
              { imageId: "sc-2", source: "artwork" }
            ]
          }
        }}
      />
    );

    expect(container.querySelector(".upcoming-media-gallery iframe")).toBeNull();
    expect(container.querySelector(".upcoming-media-hero img")?.getAttribute("src")).toContain("i.ytimg.com/vi/gameplay123");
    expect(container.querySelector(".trailer-play-button")?.textContent).toContain("Play trailer");
    expect(container.textContent).toContain("Gameplay Trailer");

    await act(async () => {
      getButton(container, "Play trailer").click();
    });
    const iframe = container.querySelector(".upcoming-media-gallery iframe") as HTMLIFrameElement | null;
    expect(iframe?.getAttribute("src")).toContain("https://www.youtube-nocookie.com/embed/gameplay123");
    expect(iframe?.getAttribute("src")).toContain("playsinline=1");
    expect(container.querySelector(".upcoming-media-overlay")).toBeNull();

    await act(async () => {
      container.querySelector(".upcoming-media-gallery")?.dispatchEvent(new window.KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
    });
    expect(container.querySelector(".upcoming-media-gallery iframe")).toBeNull();
    expect(container.querySelector(".upcoming-media-hero img")?.getAttribute("src")).toContain("t_1080p/sc-1");

    await cleanup();
  });

  test("upcoming detail trailer thumbnail only selects and poster play starts inline playback", async () => {
    const { container, cleanup } = await renderInteractive(
      <AppShell
        apiBaseUrl="http://127.0.0.1:1234"
        initialState={{
          status: "ready",
          releases: [],
          syncStatus: { status: "idle", added: 0, repaired: 0, skipped: 0, failed: 0 },
          initialView: "detail",
          initialDetail: {
            ...releaseDetail("igdb-393932", "Echoes of Aincrad"),
            trailers: [{ videoId: "gameplay123", name: "Gameplay Trailer", provider: "youtube" }],
            screenshots: [{ imageId: "sc-1", source: "artwork" }]
          }
        }}
      />
    );

    const trailerThumb = Array.from(container.querySelectorAll(".upcoming-media-thumbs button"))
      .find(button => button.textContent?.includes("Trailer: Gameplay Trailer")) as HTMLButtonElement | undefined;

    await act(async () => {
      trailerThumb?.click();
    });

    expect(container.querySelector(".upcoming-media-gallery iframe")).toBeNull();
    expect(container.querySelector(".upcoming-media-hero img")?.getAttribute("src")).toContain("i.ytimg.com/vi/gameplay123");
    expect(container.querySelector(".trailer-play-button")?.textContent).toContain("Play trailer");
    expect(container.querySelector(".trailer-thumb-label")?.textContent).toBe("Trailer");

    await act(async () => {
      getButton(container, "Play trailer").click();
    });

    const iframe = container.querySelector(".upcoming-media-gallery iframe") as HTMLIFrameElement | null;
    expect(iframe?.getAttribute("src")).toContain("https://www.youtube-nocookie.com/embed/gameplay123");
    expect(container.querySelector(".upcoming-media-overlay")).toBeNull();

    await cleanup();
  });

  test("upcoming detail media gallery opens and closes a fullscreen overlay", async () => {
    const { container, cleanup } = await renderInteractive(
      <AppShell
        apiBaseUrl="http://127.0.0.1:1234"
        initialState={{
          status: "ready",
          releases: [],
          syncStatus: { status: "idle", added: 0, repaired: 0, skipped: 0, failed: 0 },
          initialView: "detail",
          initialDetail: {
            ...releaseDetail("igdb-393932", "Echoes of Aincrad"),
            trailers: [{ videoId: "gameplay123", name: "Gameplay Trailer", provider: "youtube" }],
            screenshots: [{ imageId: "sc-1", source: "artwork" }]
          }
        }}
      />
    );

    await act(async () => {
      getButton(container, "Open fullscreen").click();
    });
    expect(container.querySelector(".upcoming-media-overlay")).not.toBeNull();

    await act(async () => {
      getButton(container, "Play trailer").click();
    });
    expect(container.querySelector(".upcoming-media-overlay iframe")?.getAttribute("src")).toContain("gameplay123");

    await act(async () => {
      container.querySelector(".upcoming-media-overlay")?.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    });
    expect(container.querySelector(".upcoming-media-overlay")).toBeNull();
    expect(container.querySelector(".upcoming-media-gallery iframe")).toBeNull();

    await cleanup();
  });

  test("upcoming detail shows a placeholder when no IGDB screenshots are saved", async () => {
    const { container, cleanup } = await renderInteractive(
      <AppShell
        apiBaseUrl="http://127.0.0.1:1234"
        initialState={{
          status: "ready",
          releases: [],
          syncStatus: { status: "idle", added: 0, repaired: 0, skipped: 0, failed: 0 },
          initialView: "detail",
          initialDetail: releaseDetail("manual-1", "Manual Game")
        }}
      />
    );

    expect(container.textContent).toContain("No IGDB screenshots saved yet.");
    expect(container.querySelector(".completed-media-hero img")).toBeNull();
    await cleanup();
  });

  test("completed detail can delete the current completed game", async () => {
    const api = fakeApiClient();
    const confirm = vi.fn(() => true);
    vi.stubGlobal("confirm", confirm);
    const { container, cleanup } = await renderInteractive(
      <AppShell
        apiBaseUrl="http://127.0.0.1:1234"
        api={api}
        initialState={{
          status: "ready",
          releases: [],
          syncStatus: { status: "idle", added: 0, repaired: 0, skipped: 0, failed: 0 },
          initialView: "completed-detail",
          completedLibraryStatus: "ready",
          completedGames: [],
          initialCompletedDetail: {
            ...completedItem("completed-bloodborne-pc", "Bloodborne", "2026-05", "exact"),
            extra: {},
            igdbGenres: [],
            igdbPlatforms: [],
            screenshots: []
          }
        }}
      />
    );

    await act(async () => {
      getButton(container, "Delete").click();
    });

    expect(confirm).toHaveBeenCalledWith('Delete "Bloodborne" from completed library?');
    expect(api.deleteCompletedGame).toHaveBeenCalledWith("completed-bloodborne-pc");
    expect(container.textContent).toContain("Completed Library");
    await cleanup();
    vi.unstubAllGlobals();
  });

  test("completed library can select visible games with Ctrl+A and bulk delete them", async () => {
    const api = fakeApiClient();
    const confirm = vi.fn(() => true);
    vi.stubGlobal("confirm", confirm);
    const { container, cleanup } = await renderInteractive(
      <AppShell
        apiBaseUrl="http://127.0.0.1:1234"
        api={api}
        initialState={{
          status: "ready",
          releases: [],
          syncStatus: { status: "idle", added: 0, repaired: 0, skipped: 0, failed: 0 },
          initialView: "completed-library",
          completedLibraryStatus: "ready",
          completedGames: [
            completedItem("completed-bloodborne-pc", "Bloodborne", "2026-05", "exact"),
            completedItem("completed-doom-pc", "Doom", "2026-01", "exact")
          ]
        }}
      />
    );

    await act(async () => {
      document.dispatchEvent(new window.KeyboardEvent("keydown", { key: "a", ctrlKey: true, bubbles: true }));
    });
    expect(container.textContent).toContain("2 selected");

    await act(async () => {
      getButton(container, "Delete selected").click();
    });

    expect(confirm).toHaveBeenCalledWith("Delete 2 selected completed games?");
    expect(api.deleteCompletedGame.mock.calls).toEqual([["completed-bloodborne-pc"], ["completed-doom-pc"]]);
    await cleanup();
    vi.unstubAllGlobals();
  });

  test("detail view exposes delete and artwork management controls", () => {
    const html = renderToString(
      <AppShell
        apiBaseUrl="http://127.0.0.1:1234"
        initialState={{
          status: "ready",
          releases: [],
          syncStatus: { status: "idle", added: 0, repaired: 0, skipped: 0, failed: 0 },
          initialView: "detail",
          initialDetail: {
            id: "manual-1",
            title: "Manual Game",
            dateText: "Feb 20, 2027",
            releaseDate: "2027-02-20",
            datePrecision: "Exact",
            effectiveSortDate: "2027-02-20",
            category: "Main",
            publishers: ["NIS America"],
            developers: [],
            platforms: ["Windows PC"],
            sourceConfidence: 70,
            artworks: [{ imageId: "local.png", source: "local", url: "/api/artworks/local/local.png" }],
            sources: [],
            igdbUrl: null
          }
        }}
      />
    );

    expect(html).toContain("Delete");
    expect(html).toContain("Delete + block");
    expect(html).toContain("Add artwork");
    expect(html).toContain("Remove artwork");
    expect(html).toContain("No IGDB screenshots saved yet.");
  });

  test("detail delete asks for confirmation before calling the delete API", async () => {
    const api = fakeApiClient();
    const { container, cleanup } = await renderInteractive(
      <AppShell
        apiBaseUrl="http://127.0.0.1:1234"
        api={api}
        initialState={{
          status: "ready",
          releases: [],
          syncStatus: { status: "idle", added: 0, repaired: 0, skipped: 0, failed: 0 },
          initialView: "detail",
          initialDetail: releaseDetail("manual-1", "Manual Game")
        }}
      />
    );
    vi.stubGlobal("confirm", vi.fn(() => false));

    await act(async () => {
      getButton(container, "Delete").click();
    });

    expect(confirm).toHaveBeenCalledWith('Delete "Manual Game"?');
    expect(api.deleteRelease).not.toHaveBeenCalled();
    expect(api.logEvent.mock.calls.map(([event]) => event)).toEqual(["ui.click", "ui.confirm.cancelled"]);

    vi.mocked(confirm).mockReturnValue(true);
    await act(async () => {
      getButton(container, "Delete").click();
    });

    expect(api.deleteRelease).toHaveBeenCalledWith("manual-1", false);
    await cleanup();
    vi.unstubAllGlobals();
  });

  test("wallpaper chooser uses the Electron picker without rendering a file input", async () => {
    const selectedUrl = "/api/wallpaper/current";
    const { container, cleanup } = await renderInteractive(
      <AppShell
        apiBaseUrl="http://127.0.0.1:1234"
        initialState={{
          status: "ready",
          releases: [],
          syncStatus: { status: "idle", added: 0, repaired: 0, skipped: 0, failed: 0 }
        }}
      />,
      window => {
        window.releaseTracker = {
          chooseWallpaper: vi.fn(async () => selectedUrl)
        };
      }
    );

    await act(async () => { getButton(container, "Settings").click(); });
    expect(container.querySelector(".wallpaper-upload input")).toBeNull();

    await act(async () => {
      getButton(container, "Choose wallpaper").click();
    });

    expect(window.releaseTracker?.chooseWallpaper).toHaveBeenCalledTimes(1);
    expect(container.querySelector(".backdrop__img")?.getAttribute("src")).toContain("http://127.0.0.1:1234/api/wallpaper/current");
    await cleanup();
  });

  test("loads a saved backend wallpaper on startup", async () => {
    const api = fakeApiClient({ getWallpaper: async () => ({ hasWallpaper: true, url: "/api/wallpaper/current" }) });
    const { container, cleanup } = await renderInteractive(<AppShell apiBaseUrl="http://127.0.0.1:1234" api={api} />);

    await act(async () => {
      await Promise.resolve();
    });

    expect(container.querySelector(".backdrop__img")?.getAttribute("src")).toContain("http://127.0.0.1:1234/api/wallpaper/current");
    await cleanup();
    vi.unstubAllGlobals();
  });

  test("detail delete and block confirms and sends block=true", async () => {
    const api = fakeApiClient();
    const { container, cleanup } = await renderInteractive(
      <AppShell
        apiBaseUrl="http://127.0.0.1:1234"
        api={api}
        initialState={{
          status: "ready",
          releases: [],
          syncStatus: { status: "idle", added: 0, repaired: 0, skipped: 0, failed: 0 },
          initialView: "detail",
          initialDetail: releaseDetail("igdb-1", "Blocked Game")
        }}
      />
    );
    vi.stubGlobal("confirm", vi.fn(() => true));

    await act(async () => {
      getButton(container, "Delete + block").click();
    });

    expect(confirm).toHaveBeenCalledWith('Delete "Blocked Game" and block it from future syncs?');
    expect(api.deleteRelease).toHaveBeenCalledWith("igdb-1", true);
    await cleanup();
    vi.unstubAllGlobals();
  });

  test("gallery can select all visible releases and bulk delete them after confirmation", async () => {
    const api = fakeApiClient();
    const { container, cleanup } = await renderInteractive(
      <AppShell
        apiBaseUrl="http://127.0.0.1:1234"
        api={api}
        initialState={{
          status: "ready",
          releases: [
            releaseListItem("p4", "Persona 4 Revival"),
            releaseListItem("metaphor", "Metaphor Expansion")
          ],
          syncStatus: { status: "idle", added: 0, repaired: 0, skipped: 0, failed: 0 }
        }}
      />
    );
    vi.stubGlobal("confirm", vi.fn(() => true));

    await act(async () => {
      (container.querySelector("input[aria-label='Select Persona 4 Revival']") as HTMLInputElement).click();
    });
    await act(async () => {
      getButton(container, "Select all").click();
    });
    await act(async () => {
      getButton(container, "Delete selected").click();
    });

    expect(confirm).toHaveBeenCalledWith("Delete 2 selected releases?");
    expect(api.logEvent).toHaveBeenCalledWith("ui.bulk-delete.succeeded", expect.objectContaining({ ids: ["p4", "metaphor"] }));
    expect(api.deleteRelease.mock.calls).toEqual([["p4", false], ["metaphor", false]]);
    await cleanup();
    vi.unstubAllGlobals();
  });

  test("returning from upcoming detail restores the opened game position", async () => {
    const scrollIntoView = vi.fn();
    const scrollTo = vi.fn();
    const api = fakeApiClient({ getRelease: async id => releaseDetail(id, "Echoes of Aincrad") });
    const { container, cleanup } = await renderInteractive(
      <AppShell
        apiBaseUrl="http://127.0.0.1:1234"
        api={api}
        initialState={{
          status: "ready",
          releases: [
            releaseListItem("first", "First Game"),
            releaseListItem("echoes", "Echoes of Aincrad"),
            releaseListItem("third", "Third Game")
          ],
          syncStatus: { status: "idle", added: 0, repaired: 0, skipped: 0, failed: 0 }
        }}
      />,
      window => {
        Object.defineProperty(window, "scrollY", { configurable: true, value: 640 });
        window.scrollTo = scrollTo;
        window.HTMLElement.prototype.scrollIntoView = scrollIntoView;
        window.requestAnimationFrame = callback => {
          callback(0);
          return 1;
        };
      }
    );

    await act(async () => {
      const button = [...container.querySelectorAll("button")].find(item => item.textContent?.includes("Echoes of Aincrad"));
      if (!button) throw new Error("Echoes card not found");
      (button as HTMLButtonElement).dispatchEvent(new window.MouseEvent("dblclick", { bubbles: true }));
      await Promise.resolve();
    });
    expect(container.textContent).toContain("Echoes of Aincrad");

    await act(async () => {
      const button = [...container.querySelectorAll("button")].find(item => item.textContent?.includes("Back"));
      if (!button) throw new Error("Back button not found");
      (button as HTMLButtonElement).click();
    });

    expect(scrollIntoView).toHaveBeenCalledWith({ block: "center", inline: "nearest" });
    expect(scrollTo).not.toHaveBeenCalled();
    await cleanup();
    vi.unstubAllGlobals();
  });

  test("returning from completed detail restores the opened completed game position", async () => {
    const scrollIntoView = vi.fn();
    const scrollTo = vi.fn();
    const api = fakeApiClient({ getCompletedGame: async id => completedDetail(id, "Doom", "2026-01", "exact") });
    const { container, cleanup } = await renderInteractive(
      <AppShell
        apiBaseUrl="http://127.0.0.1:1234"
        api={api}
        initialState={{
          status: "ready",
          releases: [],
          syncStatus: { status: "idle", added: 0, repaired: 0, skipped: 0, failed: 0 },
          initialView: "completed-library",
          completedLibraryStatus: "ready",
          completedGames: [
            completedItem("completed-bloodborne-pc", "Bloodborne", "2026-05", "exact"),
            completedItem("completed-doom-pc", "Doom", "2026-01", "exact")
          ]
        }}
      />,
      window => {
        Object.defineProperty(window, "scrollY", { configurable: true, value: 860 });
        window.scrollTo = scrollTo;
        window.HTMLElement.prototype.scrollIntoView = scrollIntoView;
        window.requestAnimationFrame = callback => {
          callback(0);
          return 1;
        };
      }
    );

    await act(async () => {
      const button = [...container.querySelectorAll("button")].find(item => item.textContent?.includes("Doom"));
      if (!button) throw new Error("Completed game card not found");
      (button as HTMLButtonElement).click();
      await Promise.resolve();
    });
    expect(container.textContent).toContain("Your platform");

    await act(async () => {
      const button = [...container.querySelectorAll("button")].find(item => item.textContent?.includes("back to library"));
      if (!button) throw new Error("Back button not found");
      (button as HTMLButtonElement).click();
    });

    expect(container.textContent).toContain("Completed Library");
    expect(scrollIntoView).toHaveBeenCalledWith({ block: "center", inline: "nearest" });
    expect(scrollTo).not.toHaveBeenCalled();
    await cleanup();
    vi.unstubAllGlobals();
  });

  test("renders SteamGridDB artwork URLs without IGDB rewriting", () => {
    const steamGridUrl = "https://cdn2.steamgriddb.com/grid/example-grid.jpg";
    const html = renderToString(
      <AppShell
        apiBaseUrl="http://127.0.0.1:1234"
        initialState={{
          status: "ready",
          releases: [
            {
              id: "sgdb-1",
              title: "SteamGrid Game",
              dateText: "2027",
              releaseDate: "2027-01-01",
              datePrecision: "Year",
              effectiveSortDate: "2027-01-01",
              category: "Main",
              publishers: ["Atlus"],
              developers: [],
              platforms: ["PC"],
              sourceConfidence: 80,
              artworks: [{ imageId: "steam-grid", source: "steamgriddb", url: steamGridUrl }]
            }
          ],
          syncStatus: { status: "idle", added: 0, repaired: 0, skipped: 0, failed: 0 }
        }}
      />
    );

    expect(html).toContain(steamGridUrl);
    expect(html).not.toContain("images.igdb.com/igdb/image/upload/t_screenshot_med/steam-grid.jpg");
  });

  test("gallery capsules prefer portrait-friendly artwork sources over wide IGDB artwork", () => {
    const steamGridUrl = "https://cdn2.steamgriddb.com/grid/portrait-grid.jpg";
    const html = renderToString(
      <AppShell
        apiBaseUrl="http://127.0.0.1:1234"
        initialState={{
          status: "ready",
          releases: [
            {
              id: "capsule-1",
              title: "Capsule Game",
              dateText: "2027",
              releaseDate: "2027-01-01",
              datePrecision: "Year",
              effectiveSortDate: "2027-01-01",
              category: "Main",
              publishers: ["Atlus"],
              developers: [],
              platforms: ["PC"],
              sourceConfidence: 80,
              artworks: [
                { imageId: "wide-art", source: "artwork" },
                { imageId: "cover-art", source: "cover" },
                { imageId: "steam-grid", source: "steamgriddb", url: steamGridUrl }
              ]
            },
            {
              id: "capsule-2",
              title: "Cover Game",
              dateText: "2027",
              releaseDate: "2027-01-01",
              datePrecision: "Year",
              effectiveSortDate: "2027-01-01",
              category: "Main",
              publishers: ["Atlus"],
              developers: [],
              platforms: ["PC"],
              sourceConfidence: 80,
              artworks: [
                { imageId: "wide-only-first", source: "artwork" },
                { imageId: "cover-only-second", source: "cover" }
              ]
            }
          ],
          syncStatus: { status: "idle", added: 0, repaired: 0, skipped: 0, failed: 0 }
        }}
      />
    );

    expect(html).toContain("https://images.igdb.com/igdb/image/upload/t_cover_big/cover-art.jpg");
    expect(html).toContain("https://images.igdb.com/igdb/image/upload/t_cover_small/cover-only-second.jpg");
  });

  test("gallery capsules respect a non-generic first artwork choice", () => {
    const firstSteamGridUrl = "https://cdn2.steamgriddb.com/grid/first-grid.jpg";
    const laterLocalUrl = "/api/artworks/local/later-local.png";
    const html = renderToString(
      <AppShell
        apiBaseUrl="http://127.0.0.1:1234"
        initialState={{
          status: "ready",
          releases: [
            {
              id: "ordered-1",
              title: "Ordered Game",
              dateText: "2027",
              releaseDate: "2027-01-01",
              datePrecision: "Year",
              effectiveSortDate: "2027-01-01",
              category: "Main",
              publishers: ["Atlus"],
              developers: [],
              platforms: ["PC"],
              sourceConfidence: 80,
              artworks: [
                { imageId: "first-grid", source: "steamgriddb", url: firstSteamGridUrl },
                { imageId: "later-local.png", source: "local", url: laterLocalUrl }
              ]
            }
          ],
          syncStatus: { status: "idle", added: 0, repaired: 0, skipped: 0, failed: 0 }
        }}
      />
    );

    expect(html).toContain(firstSteamGridUrl);
    expect(html).not.toContain("http://127.0.0.1:1234/api/artworks/local/later-local.png");
  });


});

async function renderInteractive(element: React.ReactElement, configureWindow?: (window: Window & typeof globalThis) => void) {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  const dom = new JSDOM("<!doctype html><html><body><div id=\"root\"></div></body></html>", { url: "http://127.0.0.1" });
  const previousWindow = globalThis.window;
  const previousDocument = globalThis.document;
  const previousNavigator = globalThis.navigator;
  configureWindow?.(dom.window as Window & typeof globalThis);
  vi.stubGlobal("window", dom.window);
  vi.stubGlobal("document", dom.window.document);
  vi.stubGlobal("navigator", dom.window.navigator);
  const container = dom.window.document.getElementById("root")!;
  const root = createRoot(container);
  await act(async () => {
    root.render(element);
  });
  return {
    container,
    async cleanup() {
      await act(async () => {
        root.unmount();
      });
      dom.window.close();
      vi.stubGlobal("window", previousWindow);
      vi.stubGlobal("document", previousDocument);
      vi.stubGlobal("navigator", previousNavigator);
    }
  };
}

function getButton(container: Element, text: string) {
  const button = [...container.querySelectorAll("button")].find(item => item.textContent === text);
  if (!button) throw new Error(`Button not found: ${text}`);
  return button as HTMLButtonElement;
}

function setInputValue(element: Element, value: string) {
  const field = element as HTMLInputElement | HTMLTextAreaElement;
  const view = field.ownerDocument.defaultView!;
  const prototype = field instanceof view.HTMLTextAreaElement
    ? view.HTMLTextAreaElement.prototype
    : view.HTMLInputElement.prototype;
  const valueSetter = Object.getOwnPropertyDescriptor(prototype, "value")?.set;
  valueSetter?.call(field, value);
  field.dispatchEvent(new view.InputEvent("input", { bubbles: true, inputType: "insertText", data: value }));
  field.dispatchEvent(new view.Event("change", { bubbles: true }));
}

function releaseListItem(id: string, title: string) {
  return {
    id,
    title,
    dateText: "2027",
    releaseDate: "2027-01-01",
    datePrecision: "Year" as const,
    effectiveSortDate: "2027-01-01",
    category: "Main" as const,
    publishers: ["Atlus"],
    developers: [],
    platforms: ["PC"],
    genres: [],
    sourceConfidence: 80,
    artworks: []
  };
}

function releaseDetail(id: string, title: string) {
  return {
    ...releaseListItem(id, title),
    sources: [],
    igdbUrl: null,
    screenshots: [],
    trailers: []
  };
}

function completedItem(id: string, title: string, completionMonth: string | null, completionPrecision: "exact" | "month" | "year" | "none") {
  return {
    id,
    title,
    normalizedTitle: title.toLowerCase(),
    userPlatform: "PC",
    ratingRaw: "9/10",
    ratingScore: 9,
    completionDate: completionMonth ? `${completionMonth}-07` : null,
    completionMonth,
    completionYear: completionMonth ? Number(completionMonth.slice(0, 4)) : null,
    completionPrecision,
    developer: "Lumen Co",
    publisher: "Lumen Co",
    genres: ["Strategy"],
    igdbGenres: [] as string[],
    platforms: ["PC"],
    coverImageId: `cover-${id}`,
    igdbId: 9000,
    matchStatus: "matched" as const
  };
}

function completedDetail(id: string, title: string, completionMonth: string | null, completionPrecision: "exact" | "month" | "year" | "none") {
  return {
    ...completedItem(id, title, completionMonth, completionPrecision),
    notes: null,
    extra: {},
    igdbReleaseDate: null,
    igdbDeveloper: null,
    igdbPublisher: null,
    igdbGenres: [],
    igdbPlatforms: [],
    summary: null,
    screenshots: [],
    lastSyncedAt: null
  };
}
