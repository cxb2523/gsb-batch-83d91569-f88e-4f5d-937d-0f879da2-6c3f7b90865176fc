import { afterEach, describe, expect, test, vi } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { openDatabase, type TrackerDatabase } from "../../apps/backend/src/database/db";
import { runMigrations } from "../../apps/backend/src/database/migrations";
import { createReleaseStore } from "../../apps/backend/src/database/releaseStore";
import type { IgdbGateway } from "../../apps/backend/src/igdb/gateway";
import { createBackendApp } from "../../apps/backend/src/server";
import { shouldAutoSync } from "../../apps/backend/src/sync/syncStatus";
import { createSyncSettingsStore } from "../../apps/backend/src/sync/syncSettingsStore";
import { computeSortDateAndEligibility } from "../../apps/backend/src/sync/releasePolicy";

let dirs: string[] = [];
let dbs: TrackerDatabase[] = [];

afterEach(() => {
  for (const db of dbs) db.close();
  dbs = [];
  for (const dir of dirs) rmSync(dir, { recursive: true, force: true });
  dirs = [];
  delete process.env.GRT_DATA_DIR;
});

// A gateway that knows three companies by exact name and answers company searches.
function fakeGateway(hasCredentials = true): IgdbGateway {
  const companies: Record<string, { id: number; name: string; published: number[] }> = {
    Capcom: { id: 37, name: "Capcom", published: [1, 2] },
    Sega: { id: 112, name: "Sega", published: [1] },
    Nintendo: { id: 70, name: "Nintendo", published: [1, 2, 3] }
  };
  return {
    hasCredentials: () => hasCredentials,
    query: vi.fn(async (endpoint: string, body: string) => {
      if (endpoint !== "companies") return [];
      const exact = body.match(/where name = "(.+?)"/)?.[1];
      if (exact) return companies[exact] ? [companies[exact]] : [];
      return Object.values(companies).filter(company => body.toLowerCase().includes(`*"${company.name.slice(0, 3).toLowerCase()}`));
    })
  } as unknown as IgdbGateway;
}

function setup(igdb = fakeGateway()) {
  const dir = mkdtempSync(join(tmpdir(), "grt-sync-settings-"));
  dirs.push(dir);
  process.env.GRT_DATA_DIR = dir;
  const db = openDatabase(join(dir, "tracker.db"));
  dbs.push(db);
  runMigrations(db);
  return { app: createBackendApp({ db, autoSync: false, igdb }), db };
}

describe("sync settings API", () => {
  test("a new library tracks no publishers, every platform, releases from January 1 this year, doesn't auto-sync, and alerts", async () => {
    const { app, db } = setup();

    expect((await app.inject({ method: "GET", url: "/api/sync/settings" })).json()).toEqual({
      publishers: [],
      platforms: ["pc", "xbox", "playstation", "switch"],
      trackFrom: `${new Date().getUTCFullYear()}-01-01`,
      autoSync: false,
      alerts: true
    });
    expect(shouldAutoSync(db)).toBe(false);
  });

  test("saves platforms, the track-from date and auto-sync, and refuses bad values", async () => {
    const { app, db } = setup();

    const saved = await app.inject({ method: "PUT", url: "/api/sync/settings", payload: { platforms: ["pc", "switch"], trackFrom: "2025-06-01", autoSync: true } });

    expect(saved.json()).toMatchObject({ platforms: ["pc", "switch"], trackFrom: "2025-06-01", autoSync: true });
    expect(shouldAutoSync(db)).toBe(true);
    for (const payload of [{ platforms: [] }, { platforms: ["dreamcast"] }, { trackFrom: "2025-13-01" }, { trackFrom: "soon" }, { autoSync: "yes" }]) {
      expect((await app.inject({ method: "PUT", url: "/api/sync/settings", payload })).statusCode, JSON.stringify(payload)).toBe(400);
    }
  });

  test("auto-sync waits 12 hours after the last successful sync, whatever the computer's time zone", () => {
    const zone = process.env.TZ;
    process.env.TZ = "Asia/Kolkata";
    try {
      const { db } = setup();
      createSyncSettingsStore(db).update({ autoSync: true });
      // Stored the way SQLite's current_timestamp stores it: UTC, no zone.
      const finishedHoursAgo = (hours: number) => {
        db.prepare("delete from sync_runs").run();
        const at = new Date(Date.now() - hours * 3_600_000).toISOString().replace("T", " ").slice(0, 19);
        db.prepare("insert into sync_runs (status, finished_at) values ('success', ?)").run(at);
      };

      finishedHoursAgo(11);
      expect(shouldAutoSync(db)).toBe(false);
      finishedHoursAgo(13);
      expect(shouldAutoSync(db)).toBe(true);
    } finally {
      process.env.TZ = zone;
    }
  });

  test("publishers are searched on IGDB, tracked and untracked", async () => {
    const { app } = setup();

    const found = await app.inject({ method: "GET", url: "/api/sync/publishers/search?q=cap" });
    expect(found.json().items).toEqual([{ id: 37, name: "Capcom" }]);

    const tracked = await app.inject({ method: "POST", url: "/api/sync/publishers", payload: { id: 37, name: "Capcom" } });
    expect(tracked.json().publishers).toEqual([{ id: 37, name: "Capcom" }]);

    const untracked = await app.inject({ method: "DELETE", url: "/api/sync/publishers/37" });
    expect(untracked.json().publishers).toEqual([]);
    expect((await app.inject({ method: "DELETE", url: "/api/sync/publishers/37" })).statusCode).toBe(404);
    expect((await app.inject({ method: "POST", url: "/api/sync/publishers", payload: { id: "37" } })).statusCode).toBe(400);
  });

  test("suggested publishers are added by exact IGDB name, and the ones IGDB doesn't know are reported", async () => {
    const { app } = setup();

    const added = (await app.inject({ method: "POST", url: "/api/sync/publishers/suggested" })).json();

    expect(added.publishers.map((publisher: { name: string }) => publisher.name)).toEqual(["Capcom", "Nintendo", "Sega"]);
    expect(added.notFound).toContain("Square Enix");
  });

  test("publisher search and suggestions need IGDB keys", async () => {
    const { app } = setup(fakeGateway(false));

    expect((await app.inject({ method: "GET", url: "/api/sync/publishers/search?q=cap" })).statusCode).toBe(409);
    expect((await app.inject({ method: "POST", url: "/api/sync/publishers/suggested" })).statusCode).toBe(409);
  });

  test("a sync with no tracked publishers says what to do", async () => {
    const { app } = setup();

    const status = (await app.inject({ method: "POST", url: "/api/sync/igdb" })).json();

    expect(status).toMatchObject({ status: "failed", message: "No publishers are tracked yet. Add some in Settings → Sync, then sync again." });
  });

  test("Upcoming lists releases from the track-from date on", async () => {
    const { app, db } = setup();
    const store = createReleaseStore(db);
    for (const [id, releaseDate] of [["older", "2025-03-01"], ["newer", "2026-03-01"]]) {
      const date = { dateText: releaseDate, releaseDate, datePrecision: "Exact" as const, releaseWindow: null };
      store.save({ id, title: id, normalizedTitle: id, category: "Main", sourceConfidence: 90, publishers: [], developers: [], platforms: [], genres: [], artworks: [], ...date, ...computeSortDateAndEligibility(date) });
    }

    await app.inject({ method: "PUT", url: "/api/sync/settings", payload: { trackFrom: "2026-01-01" } });
    expect((await app.inject({ method: "GET", url: "/api/releases" })).json().items.map((item: { id: string }) => item.id)).toEqual(["newer"]);

    await app.inject({ method: "PUT", url: "/api/sync/settings", payload: { trackFrom: "2025-01-01" } });
    expect((await app.inject({ method: "GET", url: "/api/releases" })).json().items.map((item: { id: string }) => item.id)).toEqual(["older", "newer"]);
  });
});
