import { afterEach, describe, expect, test, vi } from "vitest";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { openDatabase } from "../../apps/backend/src/database/db";
import { runMigrations } from "../../apps/backend/src/database/migrations";
import { createReleaseStore } from "../../apps/backend/src/database/releaseStore";
import { createBackendApp } from "../../apps/backend/src/server";
import { createSyncSettingsStore } from "../../apps/backend/src/sync/syncSettingsStore";

let dirs: string[] = [];
let dbs: Array<{ close(): void }> = [];

function setup() {
  const dir = mkdtempSync(join(tmpdir(), "grt-api-"));
  dirs.push(dir);
  process.env.GRT_DATA_DIR = dir;
  const db = openDatabase(join(dir, "tracker.db"));
  dbs.push(db);
  runMigrations(db);
  // Sync fixtures are credited to IGDB company 1.
  createSyncSettingsStore(db).addPublishers([{ id: 1, name: "Atlus" }]);
  const app = createBackendApp({ db, autoSync: false });
  return { app, db };
}

function setupWithEvents() {
  const dir = mkdtempSync(join(tmpdir(), "grt-api-"));
  dirs.push(dir);
  process.env.GRT_DATA_DIR = dir;
  const db = openDatabase(join(dir, "tracker.db"));
  dbs.push(db);
  runMigrations(db);
  // Sync fixtures are credited to IGDB company 1.
  createSyncSettingsStore(db).addPublishers([{ id: 1, name: "Atlus" }]);
  const events: Array<{ event: string; details?: Record<string, unknown> }> = [];
  const app = createBackendApp({
    db,
    autoSync: false,
    logger: { log: (event: string, details?: Record<string, unknown>) => events.push({ event, details }) }
  } as Parameters<typeof createBackendApp>[0]);
  return { app, db, events };
}

afterEach(() => {
  vi.unstubAllGlobals();
  for (const db of dbs) db.close();
  dbs = [];
  for (const dir of dirs) rmSync(dir, { recursive: true, force: true });
  dirs = [];
  delete process.env.GRT_DATA_DIR;
  delete process.env.GRT_ASSET_ROOT;
});

describe("release API", () => {
  test("filters, sorts, caps results, and reports truncation", async () => {
    const { app, db } = setup();
    const insert = db.prepare("insert into releases (id, title, normalized_title, date_text, release_date, date_precision, category, source_confidence, eligible, effective_sort_date) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)");
    insert.run("old", "Old Game", "old game", "Dec 31, 2025", "2025-12-31", "Exact", "Main", 90, 0, "2025-12-31");
    insert.run("wl", "Wo Long 2: Wings of Ember", "wo long 2 wings of ember", "Early 2027", null, "Window", "Main", 60, 1, "2027-01-01");
    createReleaseStore(db).save({
      id: "p4", title: "Persona 4 Revival", normalizedTitle: "persona 4 revival",
      dateText: "Feb 18, 2027", releaseDate: "2027-02-18", datePrecision: "Exact",
      releaseWindow: null, sourceConfidence: 90, category: "Remake",
      publishers: ["Atlus"], developers: [], platforms: [], genres: [],
      artworks: [{ imageId: "art-a", source: "artwork" }]
    });

    const response = await app.inject({ method: "GET", url: "/api/releases?search=persona&publisher=Atlus" });
    expect(response.statusCode).toBe(200);
    const body = response.json();
    expect(body.truncated).toBe(false);
    expect(body.items.map((item: { title: string }) => item.title)).toEqual(["Persona 4 Revival"]);
    expect(body.items[0].artworks).toEqual([{ imageId: "art-a", source: "artwork" }]);
  });

  test("persists hidden watched released state through PATCH", async () => {
    const { app, db } = setup();
    db.prepare("insert into releases (id, title, normalized_title, date_text, date_precision, category, eligible, effective_sort_date) values (?, ?, ?, ?, ?, ?, 1, ?)").run("ex", "Exodus", "exodus", "2027", "Year", "Main", "2027-01-01");

    const response = await app.inject({
      method: "PATCH",
      url: "/api/releases/ex",
      payload: { hidden: true, watched: true, released: false }
    });

    expect(response.statusCode).toBe(200);
    expect(db.prepare("select hidden, watched, released from user_release_state where release_id = ?").get("ex")).toEqual({ hidden: 1, watched: 1, released: 0 });
  });

  test("partial release state PATCH preserves unspecified flags", async () => {
    const { app, db } = setup();
    db.prepare("insert into releases (id, title, normalized_title, date_text, date_precision, category, eligible, effective_sort_date) values (?, ?, ?, ?, ?, ?, 1, ?)").run("ex", "Exodus", "exodus", "2027", "Year", "Main", "2027-01-01");
    db.prepare("insert into user_release_state (release_id, hidden, watched, released) values (?, 0, 1, 1)").run("ex");

    const response = await app.inject({
      method: "PATCH",
      url: "/api/releases/ex",
      payload: { hidden: true }
    });

    expect(response.statusCode).toBe(200);
    expect(db.prepare("select hidden, watched, released from user_release_state where release_id = ?").get("ex")).toEqual({ hidden: 1, watched: 1, released: 1 });
  });

  test("detail PATCH persists publishers developers and platforms through read model", async () => {
    const { app, db } = setup();
    db.prepare("insert into releases (id, title, normalized_title, date_text, release_date, date_precision, category, eligible, effective_sort_date) values (?, ?, ?, ?, ?, ?, ?, 1, ?)").run("ex", "Exodus", "exodus", "2027", null, "Year", "Main", "2027-01-01");
    db.prepare("insert into release_publishers (release_id, publisher) values (?, ?)").run("ex", "Old Publisher");
    db.prepare("insert into release_developers (release_id, developer) values (?, ?)").run("ex", "Old Developer");
    db.prepare("insert into release_platforms (release_id, platform) values (?, ?)").run("ex", "Old Platform");

    const response = await app.inject({
      method: "PATCH",
      url: "/api/releases/ex",
      payload: {
        publishers: ["New Publisher"],
        developers: ["New Developer"],
        platforms: ["PC", "Xbox Series X|S"]
      }
    });

    expect(response.statusCode).toBe(200);
    const detail = (await app.inject({ method: "GET", url: "/api/releases/ex" })).json();
    expect(detail).toMatchObject({
      publishers: ["New Publisher"],
      developers: ["New Developer"],
      platforms: ["PC", "Xbox Series X|S"]
    });
  });

  test("sync endpoint returns status instead of throwing when credentials are missing", async () => {
    const { app } = setup();
    const first = await app.inject({ method: "POST", url: "/api/sync/igdb" });
    const second = await app.inject({ method: "POST", url: "/api/sync/igdb" });

    expect(first.statusCode).toBe(200);
    expect(second.statusCode).toBe(200);
    expect(second.json().status).toBe("failed");
    expect(second.json().message.length).toBeGreaterThan(0);
  });

  test("a sync interrupted by closing the app is reported as failed on the next start", async () => {
    const { db } = setup();
    db.prepare("insert into sync_runs (status, message) values ('running', 'Sync started')").run();

    const status = (await createBackendApp({ db, autoSync: false }).inject({ method: "GET", url: "/api/sync/status" })).json();

    expect(status).toMatchObject({ status: "failed", message: "interrupted" });
  });

  test("detail endpoint returns full eligible release and 404s ineligible rows", async () => {
    const { app, db } = setup();
    db.prepare("insert into releases (id, title, normalized_title, date_text, release_date, date_precision, category, source_confidence, eligible, effective_sort_date, igdb_url) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)").run("p4", "Persona 4 Revival", "persona 4 revival", "Feb 18, 2027", "2027-02-18", "Exact", "Remake", 90, 1, "2027-02-18", "https://www.igdb.com/games/persona-4-revival");
    db.prepare("insert into release_publishers (release_id, publisher) values (?, ?)").run("p4", "Atlus");
    db.prepare("insert into release_developers (release_id, developer) values (?, ?)").run("p4", "Atlus Studio");
    db.prepare("insert into release_artworks (release_id, image_id, sort_order) values (?, ?, ?)").run("p4", "art-a", 0);
    db.prepare("insert into release_screenshots (release_id, image_id, sort_order) values (?, ?, ?)").run("p4", "sc-a", 0);
    db.prepare("insert into release_trailers (release_id, video_id, name, provider, sort_order) values (?, ?, ?, ?, ?)").run("p4", "gameplay123", "Gameplay Trailer", "youtube", 0);
    db.prepare("insert into releases (id, title, normalized_title, date_text, release_date, date_precision, category, eligible, effective_sort_date) values (?, ?, ?, ?, ?, ?, ?, 0, ?)").run("old", "Old Game", "old game", "2025", "2025-01-01", "Year", "Main", "2025-01-01");

    const detail = await app.inject({ method: "GET", url: "/api/releases/p4" });
    expect(detail.statusCode).toBe(200);
    expect(detail.json()).toMatchObject({
      title: "Persona 4 Revival",
      publishers: ["Atlus"],
      developers: ["Atlus Studio"],
      effectiveSortDate: "2027-02-18",
      artworks: [{ imageId: "art-a" }],
      screenshots: [{ imageId: "sc-a", source: "artwork" }],
      trailers: [{ videoId: "gameplay123", name: "Gameplay Trailer", provider: "youtube" }]
    });

    expect((await app.inject({ method: "GET", url: "/api/releases/old" })).statusCode).toBe(404);
  });

  test("settings credentials are reflected in credential status", async () => {
    const previous = {
      IGDB_CLIENT_ID: process.env.IGDB_CLIENT_ID,
      IGDB_CLIENT_SECRET: process.env.IGDB_CLIENT_SECRET,
      IGDB_ACCESS_TOKEN: process.env.IGDB_ACCESS_TOKEN
    };
    delete process.env.IGDB_CLIENT_ID;
    delete process.env.IGDB_CLIENT_SECRET;
    delete process.env.IGDB_ACCESS_TOKEN;
    const { app } = setup();
    try {
      expect((await app.inject({ method: "GET", url: "/api/settings" })).json().credentialStatus.status).toBe("missing");

      await app.inject({
        method: "PATCH",
        url: "/api/settings",
        payload: { IGDB_CLIENT_ID: "client", IGDB_ACCESS_TOKEN: "token", STEAMGRIDDB_API_KEY: "sgdb-secret" }
      });

      const saved = (await app.inject({ method: "GET", url: "/api/settings" })).json();
      expect(saved.credentialStatus.status).toBe("ready");
      expect(saved.credentials).toEqual({
        IGDB_CLIENT_ID: { saved: true },
        IGDB_CLIENT_SECRET: { saved: false },
        IGDB_ACCESS_TOKEN: { saved: true },
        STEAMGRIDDB_API_KEY: { saved: true }
      });
      expect(JSON.stringify(saved)).not.toContain("token");
      expect(JSON.stringify(saved)).not.toContain("sgdb-secret");

      await app.inject({ method: "DELETE", url: "/api/settings/credentials" });
      expect((await app.inject({ method: "GET", url: "/api/settings" })).json().credentialStatus.status).toBe("missing");
      expect((await app.inject({ method: "GET", url: "/api/settings" })).json().credentials.STEAMGRIDDB_API_KEY.saved).toBe(false);
    } finally {
      if (previous.IGDB_CLIENT_ID === undefined) delete process.env.IGDB_CLIENT_ID;
      else process.env.IGDB_CLIENT_ID = previous.IGDB_CLIENT_ID;
      if (previous.IGDB_CLIENT_SECRET === undefined) delete process.env.IGDB_CLIENT_SECRET;
      else process.env.IGDB_CLIENT_SECRET = previous.IGDB_CLIENT_SECRET;
      if (previous.IGDB_ACCESS_TOKEN === undefined) delete process.env.IGDB_ACCESS_TOKEN;
      else process.env.IGDB_ACCESS_TOKEN = previous.IGDB_ACCESS_TOKEN;
    }
  });

  test("creates manual releases with computed eligibility", async () => {
    const { app } = setup();

    const created = await app.inject({
      method: "POST",
      url: "/api/releases/manual",
      payload: {
        title: "Manual NIS RPG",
        publishers: "NIS America",
        developers: "Studio Example",
        platforms: "Windows PC, Xbox Series X|S",
        category: "Main",
        dateText: "Feb 20, 2027",
        datePrecision: "Exact",
        releaseDate: "2027-02-20",
        sourceUrl: "https://example.test/manual"
      }
    });

    expect(created.statusCode).toBe(200);
    expect(created.json().item).toMatchObject({
      title: "Manual NIS RPG",
      publishers: ["NIS America"],
      effectiveSortDate: "2027-02-20",
      eligible: true
    });
    expect((await app.inject({ method: "GET", url: "/api/releases?publisher=NIS%20America" })).json().items).toHaveLength(1);
  });

  test("manual IGDB search returns form-ready candidates", async () => {
    const { app } = setup();
    await app.inject({
      method: "PATCH",
      url: "/api/settings",
      payload: { IGDB_CLIENT_ID: "client", IGDB_ACCESS_TOKEN: "token" }
    });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify([
      {
        id: 19560,
        name: "Bloodborne",
        url: "https://www.igdb.com/games/bloodborne",
        game_type: 0,
        first_release_date: 1767225600,
        cover: { image_id: "cover-bloodborne" },
        artworks: [{ image_id: "art-bloodborne" }],
        screenshots: [{ image_id: "shot-bloodborne" }],
        videos: [{ video_id: "gameplay123", name: "Gameplay Trailer" }],
        platforms: [{ abbreviation: "PC" }],
        involved_companies: [
          { developer: true, company: { name: "FromSoftware" } },
          { publisher: true, company: { name: "Sony Interactive Entertainment" } }
        ]
      }
    ]), { status: 200 })));

    const response = await app.inject({ method: "GET", url: "/api/releases/manual/search?q=Bloodborne" });

    expect(response.statusCode).toBe(200);
    expect(response.json().items[0]).toMatchObject({
      igdbId: 19560,
      title: "Bloodborne",
      developers: ["FromSoftware"],
      publishers: ["Sony Interactive Entertainment"],
      platforms: ["PC"],
      sourceUrl: "https://www.igdb.com/games/bloodborne",
      coverImageId: "cover-bloodborne",
      artworks: [{ imageId: "art-bloodborne", source: "artwork" }, { imageId: "cover-bloodborne", source: "cover" }],
      screenshots: [{ imageId: "shot-bloodborne", source: "artwork" }],
      trailers: [{ videoId: "gameplay123", name: "Gameplay Trailer", provider: "youtube" }]
    });
  });

  test("manual release created from IGDB candidate persists artwork screenshots and trailers", async () => {
    const { app } = setup();

    const created = await app.inject({
      method: "POST",
      url: "/api/releases/manual",
      payload: {
        igdbId: 19560,
        title: "Bloodborne",
        publishers: "Sony Interactive Entertainment",
        developers: "FromSoftware",
        platforms: "PC",
        category: "Main",
        dateText: "Dec 31, 2026",
        datePrecision: "Exact",
        releaseDate: "2026-12-31",
        sourceUrl: "https://www.igdb.com/games/bloodborne",
        artworks: [{ imageId: "art-bloodborne", source: "artwork" }, { imageId: "cover-bloodborne", source: "cover" }],
        screenshots: [{ imageId: "shot-bloodborne", source: "artwork" }],
        trailers: [{ videoId: "gameplay123", name: "Gameplay Trailer", provider: "youtube" }]
      }
    });

    expect(created.statusCode).toBe(200);
    const detail = created.json().item;
    expect(detail).toMatchObject({
      title: "Bloodborne",
      artworks: [{ imageId: "art-bloodborne", source: "artwork" }, { imageId: "cover-bloodborne", source: "cover" }],
      screenshots: [{ imageId: "shot-bloodborne", source: "artwork" }],
      trailers: [{ videoId: "gameplay123", name: "Gameplay Trailer", provider: "youtube" }]
    });
  });

  test("stores ineligible manual TBA releases but excludes them from list reads", async () => {
    const { app, db } = setup();

    const created = await app.inject({
      method: "POST",
      url: "/api/releases/manual",
      payload: {
        title: "Manual TBA",
        publishers: "NIS America",
        category: "Main",
        dateText: "TBA",
        datePrecision: "TBA"
      }
    });

    expect(created.statusCode).toBe(200);
    expect(db.prepare("select eligible from releases where title = ?").get("Manual TBA")).toEqual({ eligible: 0 });
    expect((await app.inject({ method: "GET", url: "/api/releases?search=Manual" })).json().items).toEqual([]);
  });

  test("re-adding a tracked IGDB game that is hidden from Upcoming reports a conflict instead of a null item", async () => {
    const { app, db } = setup();
    const payload = { igdbId: 4242, title: "Hidden TBA", category: "Main", dateText: "TBA", datePrecision: "TBA" };

    expect((await app.inject({ method: "POST", url: "/api/releases/manual", payload })).statusCode).toBe(200);
    const again = await app.inject({ method: "POST", url: "/api/releases/manual", payload });

    expect(again.statusCode).toBe(409);
    expect(again.json().error).toMatch(/already tracked but hidden/);
    expect(db.prepare("select count(*) count from releases where igdb_id = ?").get(4242)).toEqual({ count: 1 });
  });

  test("delete removes a release and delete block prevents future sync inserts", async () => {
    const { app, db } = setup();
    db.prepare("insert into releases (id, igdb_id, title, normalized_title, date_text, release_date, date_precision, category, eligible, effective_sort_date) values (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)").run("igdb-1", 1, "Blocked Game", "blocked game", "Feb 20, 2027", "2027-02-20", "Exact", "Main", "2027-02-20");
    db.prepare("insert into release_artworks (release_id, image_id, sort_order) values (?, ?, 0)").run("igdb-1", "art-a");
    db.prepare("insert into user_release_state (release_id, hidden) values (?, 1)").run("igdb-1");

    const removed = await app.inject({ method: "DELETE", url: "/api/releases/igdb-1?block=true" });

    expect(removed.statusCode).toBe(200);
    expect(db.prepare("select 1 from releases where id = ?").get("igdb-1")).toBeUndefined();
    expect(db.prepare("select 1 from release_artworks where release_id = ?").get("igdb-1")).toBeUndefined();
    expect((await app.inject({ method: "GET", url: "/api/blocked-releases" })).json().items[0]).toMatchObject({
      igdbId: 1,
      normalizedTitle: "blocked game"
    });
  });

  test("delete route writes diagnostics for request, block, and delete outcome, without per-request noise", async () => {
    const { app, db, events } = setupWithEvents();
    db.prepare("insert into releases (id, igdb_id, title, normalized_title, date_text, release_date, date_precision, category, eligible, effective_sort_date) values (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)").run("igdb-1", 1, "Blocked Game", "blocked game", "Feb 20, 2027", "2027-02-20", "Exact", "Main", "2027-02-20");

    const removed = await app.inject({ method: "DELETE", url: "/api/releases/igdb-1?block=true" });

    expect(removed.statusCode).toBe(200);
    expect(events.map(event => event.event)).toEqual([
      "release.delete.requested",
      "release.delete.blocked",
      "release.delete.deleted"
    ]);
    expect(events.find(event => event.event === "release.delete.requested")?.details).toMatchObject({ id: "igdb-1", block: true });
  });

  test("failed requests are logged by route pattern, so search text never reaches the log", async () => {
    const { app, events } = setupWithEvents();

    const missing = await app.inject({ method: "GET", url: "/api/releases/does-not-exist?q=secret+search" });

    expect(missing.statusCode).toBe(404);
    expect(events).toContainEqual({ event: "http.response", details: { method: "GET", route: "/api/releases/:id", statusCode: 404, ms: expect.any(Number) } });
    expect(JSON.stringify(events)).not.toContain("secret");
  });

  test("frontend diagnostics endpoint writes supplied UI events", async () => {
    const { app, events } = setupWithEvents();

    const response = await app.inject({
      method: "POST",
      url: "/api/diagnostics/log",
      payload: { event: "ui.click", details: { action: "delete", releaseId: "p4" } }
    });

    expect(response.statusCode).toBe(200);
    expect(events.find(event => event.event === "ui.click")?.details).toMatchObject({ action: "delete", releaseId: "p4" });
  });

  test("local artwork uploads work up to the advertised 10 MB and larger ones get a clear error", async () => {
    const { app, db } = setup();
    db.prepare("insert into releases (id, title, normalized_title, date_text, release_date, date_precision, category, eligible, effective_sort_date) values (?, ?, ?, ?, ?, ?, ?, 1, ?)").run("manual-1", "Manual Game", "manual game", "Feb 20, 2027", "2027-02-20", "Exact", "Main", "2027-02-20");
    const upload = (bytes: number) => app.inject({
      method: "POST",
      url: "/api/releases/manual-1/artworks/local",
      payload: { fileName: "hero.png", mimeType: "image/png", dataBase64: Buffer.alloc(bytes, 7).toString("base64") }
    });

    const fiveMegabytes = await upload(5 * 1024 * 1024);
    const tooLarge = await upload(10 * 1024 * 1024 + 1);

    expect(fiveMegabytes.statusCode).toBe(200);
    expect(tooLarge.statusCode).toBe(400);
    expect(tooLarge.json().error).toMatch(/larger than 10 MB/);
  });

  test("local artwork upload, reorder, and removal update release detail", async () => {
    const { app, db } = setup();
    db.prepare("insert into releases (id, title, normalized_title, date_text, release_date, date_precision, category, eligible, effective_sort_date) values (?, ?, ?, ?, ?, ?, ?, 1, ?)").run("manual-1", "Manual Game", "manual game", "Feb 20, 2027", "2027-02-20", "Exact", "Main", "2027-02-20");
    db.prepare("insert into release_artworks (release_id, image_id, source, sort_order) values (?, ?, ?, ?)").run("manual-1", "igdb-art", "artwork", 0);

    const uploaded = await app.inject({
      method: "POST",
      url: "/api/releases/manual-1/artworks/local",
      payload: {
        fileName: "hero.png",
        mimeType: "image/png",
        dataBase64: Buffer.from("fake-png").toString("base64")
      }
    });

    expect(uploaded.statusCode).toBe(200);
    const local = uploaded.json().artwork;
    expect(local).toMatchObject({ source: "local" });
    expect(local.url).toContain("/api/artworks/local/");

    await app.inject({ method: "PATCH", url: "/api/releases/manual-1/artworks/order", payload: { artworkIds: [local.imageId, "igdb-art"] } });
    expect((await app.inject({ method: "GET", url: "/api/releases/manual-1" })).json().artworks[0]).toMatchObject({ imageId: local.imageId, source: "local" });

    await app.inject({ method: "DELETE", url: `/api/releases/manual-1/artworks/${encodeURIComponent(local.imageId)}` });
    expect((await app.inject({ method: "GET", url: "/api/releases/manual-1" })).json().artworks.map((art: { imageId: string }) => art.imageId)).toEqual(["igdb-art"]);
  });

  test("wallpaper routes report, stream, and clear the saved wallpaper", async () => {
    const { app } = setup();
    const { saveWallpaperFromFile } = await import("../../apps/runtime/src/wallpaperStorage");
    const picked = join(mkdtempSync(join(tmpdir(), "grt-picked-")), "wallpaper.png");
    writeFileSync(picked, "wallpaper-bytes");
    saveWallpaperFromFile(process.env.GRT_DATA_DIR!, picked);

    const status = await app.inject({ method: "GET", url: "/api/wallpaper" });
    expect(status.statusCode).toBe(200);
    expect(status.json()).toEqual({ hasWallpaper: true, url: "/api/wallpaper/current" });

    const streamed = await app.inject({ method: "GET", url: "/api/wallpaper/current" });
    expect(streamed.statusCode).toBe(200);
    expect(streamed.headers["content-type"]).toContain("image/png");
    expect(streamed.headers["cache-control"]).toBe("no-store");
    expect(streamed.body).toBe("wallpaper-bytes");

    const cleared = await app.inject({ method: "DELETE", url: "/api/wallpaper" });
    expect(cleared.statusCode).toBe(200);
    expect(cleared.json()).toEqual({ ok: true });
    expect((await app.inject({ method: "GET", url: "/api/wallpaper" })).json()).toEqual({ hasWallpaper: false, url: null });
    expect((await app.inject({ method: "GET", url: "/api/wallpaper/current" })).statusCode).toBe(404);
  });

  test("sync auto-enriches missing artwork from SteamGridDB and reports repaired rows", async () => {
    const { db } = setup();
    const { startSync } = await import("../../apps/backend/src/sync/syncRun");
    const candidate = {
      id: 101,
      name: "Persona 4 Revival",
      game_type: 0,
      first_release_date: 1802908800,
      platforms: [{ id: 6, abbreviation: "PC", slug: "win" }],
      involved_companies: [{ publisher: true, company: { id: 1, name: "Atlus" } }]
    };

    const status = await startSync(db, [candidate], undefined, {
      steamGridClient: {
        findArtwork: async () => [{ imageId: "sgdb-101", source: "steamgriddb" as const, url: "https://cdn2.steamgriddb.com/grid/sgdb-101.jpg" }]
      }
    });

    expect(status).toMatchObject({ status: "success", added: 1, repaired: 1, skipped: 0, failed: 0 });
    expect((await createBackendApp({ db, autoSync: false }).inject({ method: "GET", url: "/api/releases/igdb-101" })).json().artworks).toEqual([
      { imageId: "sgdb-101", source: "steamgriddb", url: "https://cdn2.steamgriddb.com/grid/sgdb-101.jpg" }
    ]);
  });

  test("sync auto-enriches IGDB artwork-only releases with portrait grid artwork", async () => {
    const { db } = setup();
    const { startSync } = await import("../../apps/backend/src/sync/syncRun");
    const calls: string[] = [];

    const status = await startSync(db, [{
      id: 105,
      name: "Wide Artwork Game",
      game_type: 0,
      first_release_date: 1802908800,
      platforms: [{ id: 6, abbreviation: "PC", slug: "win" }],
      involved_companies: [{ publisher: true, company: { id: 1, name: "Atlus" } }],
      artworks: [{ image_id: "igdb-wide-art" }]
    }], undefined, {
      steamGridClient: {
        findArtwork: async title => {
          calls.push(title);
          return [{ imageId: "sgdb-105", source: "steamgriddb" as const, url: "https://cdn2.steamgriddb.com/grid/sgdb-105.jpg" }];
        }
      }
    });

    expect(status).toMatchObject({ status: "success", added: 1, repaired: 1, skipped: 0, failed: 0 });
    expect(calls).toEqual(["Wide Artwork Game"]);
    expect((await createBackendApp({ db, autoSync: false }).inject({ method: "GET", url: "/api/releases/igdb-105" })).json().artworks).toEqual([
      { imageId: "igdb-wide-art", source: "artwork" },
      { imageId: "sgdb-105", source: "steamgriddb", url: "https://cdn2.steamgriddb.com/grid/sgdb-105.jpg" }
    ]);
  });

  test("sync does not auto-enrich cover-only artwork or existing local artwork", async () => {
    const { db } = setup();
    const { startSync } = await import("../../apps/backend/src/sync/syncRun");
    const calls: string[] = [];
    db.prepare(`
      insert into releases (id, igdb_id, title, normalized_title, date_text, release_date, date_precision, category, eligible, effective_sort_date)
      values ('igdb-106', 106, 'Local Artwork Game', 'local artwork game', 'Feb 18, 2027', '2027-02-18', 'Exact', 'Main', 1, '2027-02-18')
    `).run();
    db.prepare("insert into release_artworks (release_id, image_id, source, url, sort_order) values (?, ?, ?, ?, ?)").run("igdb-106", "local.png", "local", "/api/artworks/local/local.png", 0);

    const status = await startSync(db, [
      {
        id: 106,
        name: "Local Artwork Game",
        game_type: 0,
        first_release_date: 1802908800,
        platforms: [{ id: 6, abbreviation: "PC", slug: "win" }],
        involved_companies: [{ publisher: true, company: { id: 1, name: "Atlus" } }],
        artworks: [{ image_id: "igdb-wide-art" }]
      },
      {
        id: 107,
        name: "Cover Artwork Game",
        game_type: 0,
        first_release_date: 1802908800,
        platforms: [{ id: 6, abbreviation: "PC", slug: "win" }],
        involved_companies: [{ publisher: true, company: { id: 1, name: "Atlus" } }],
        cover: { image_id: "igdb-cover-art" }
      }
    ], undefined, {
      steamGridClient: {
        findArtwork: async title => {
          calls.push(title);
          return [{ imageId: `sgdb-${title}`, source: "steamgriddb" as const, url: `https://cdn2.steamgriddb.com/grid/${encodeURIComponent(title)}.jpg` }];
        }
      }
    });

    expect(status.failed).toBe(0);
    expect(calls).toEqual([]);
    expect((await createBackendApp({ db, autoSync: false }).inject({ method: "GET", url: "/api/releases/igdb-106" })).json().artworks[0]).toMatchObject({ imageId: "local.png", source: "local" });
    expect((await createBackendApp({ db, autoSync: false }).inject({ method: "GET", url: "/api/releases/igdb-107" })).json().artworks).toEqual([
      { imageId: "igdb-cover-art", source: "cover" }
    ]);
  });

  test("sync reports partial when SteamGridDB enrichment fails", async () => {
    const { db } = setup();
    const { startSync } = await import("../../apps/backend/src/sync/syncRun");

    const status = await startSync(db, [{
      id: 103,
      name: "SteamGrid Down Game",
      game_type: 0,
      first_release_date: 1802908800,
      platforms: [{ id: 6, abbreviation: "PC", slug: "win" }],
      involved_companies: [{ publisher: true, company: { id: 1, name: "Atlus" } }]
    }], undefined, {
      steamGridClient: {
        findArtwork: async () => {
          throw new Error("SteamGridDB 500");
        }
      }
    });

    expect(status).toMatchObject({ status: "partial", added: 1, repaired: 0, skipped: 0, failed: 1 });
  });

  test("sync applies user date overrides over IGDB fields", async () => {
    const { db } = setup();
    const { startSync } = await import("../../apps/backend/src/sync/syncRun");
    db.prepare(`
      insert into releases (id, igdb_id, title, normalized_title, date_text, release_date, date_precision, category, eligible, effective_sort_date)
      values ('igdb-102', 102, 'Override Game', 'override game', 'TBA', null, 'TBA', 'Main', 0, null)
    `).run();
    db.prepare(`
      insert into manual_overrides (release_id, field, value, source_type, source_url, source_name)
      values
        ('igdb-102', 'dateText', 'Late 2027', 'user', 'https://example.test/date', 'User source'),
        ('igdb-102', 'datePrecision', 'Window', 'user', 'https://example.test/date', 'User source'),
        ('igdb-102', 'releaseWindow', 'Late 2027', 'user', 'https://example.test/date', 'User source')
    `).run();

    await startSync(db, [{
      id: 102,
      name: "Override Game",
      game_type: 0,
      first_release_date: 1798761600,
      platforms: [{ id: 6, abbreviation: "PC", slug: "win" }],
      involved_companies: [{ publisher: true, company: { id: 1, name: "Atlus" } }],
      cover: { image_id: "igdb-cover" }
    }], undefined, { steamGridClient: { findArtwork: async () => [] } });

    expect(db.prepare("select date_text dateText, date_precision datePrecision, release_window releaseWindow, effective_sort_date effectiveSortDate from releases where id = 'igdb-102'").get()).toEqual({
      dateText: "Late 2027",
      datePrecision: "Window",
      releaseWindow: "Late 2027",
      effectiveSortDate: "2027-10-01"
    });
  });

  test("sync applies seeded title overrides over matching IGDB fields", async () => {
    const { db } = setup();
    const { startSync } = await import("../../apps/backend/src/sync/syncRun");
    db.prepare(`
      insert into releases (id, title, normalized_title, date_text, date_precision, category, source_confidence)
      values ('seed-override-game', 'Override Game', 'override game', 'TBA', 'TBA', 'Main', 50)
    `).run();
    db.prepare(`
      insert into manual_overrides (release_id, field, value, source_type, source_url, source_name)
      values
        ('seed-override-game', 'dateText', 'Late 2027', 'seeded', 'https://example.test/date', 'Seed source'),
        ('seed-override-game', 'datePrecision', 'Window', 'seeded', 'https://example.test/date', 'Seed source'),
        ('seed-override-game', 'releaseWindow', 'Late 2027', 'seeded', 'https://example.test/date', 'Seed source')
    `).run();

    await startSync(db, [{
      id: 104,
      name: "Override Game",
      game_type: 0,
      first_release_date: 1798761600,
      platforms: [{ id: 6, abbreviation: "PC", slug: "win" }],
      involved_companies: [{ publisher: true, company: { id: 1, name: "Atlus" } }]
    }], undefined, { steamGridClient: { findArtwork: async () => [] } });

    expect(db.prepare("select date_text dateText, date_precision datePrecision, release_window releaseWindow, effective_sort_date effectiveSortDate from releases where id = 'igdb-104'").get()).toEqual({
      dateText: "Late 2027",
      datePrecision: "Window",
      releaseWindow: "Late 2027",
      effectiveSortDate: "2027-10-01"
    });
  });

});

