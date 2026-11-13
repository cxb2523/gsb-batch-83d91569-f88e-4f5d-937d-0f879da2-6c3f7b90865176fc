import { afterEach, describe, expect, test } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { openDatabase, type TrackerDatabase } from "../../apps/backend/src/database/db";
import { runMigrations } from "../../apps/backend/src/database/migrations";
import { resetWriteQueueForTests } from "../../apps/backend/src/database/writeQueue";
import type { IgdbGateway } from "../../apps/backend/src/igdb/gateway";
import { createBackendApp } from "../../apps/backend/src/server";

let cleanup: Array<() => void | Promise<void>> = [];

afterEach(async () => {
  for (const run of cleanup) await run();
  cleanup = [];
  resetWriteQueueForTests();
});

const quietLogger = { log: () => undefined };

// A fake IGDB that reads the `id != (...)` exclusion and `limit`/`offset` from each body.
function fakeGateway(ids: number[], overrides: Partial<IgdbGateway> = {}, similar: Record<number, number[]> = {}) {
  const bodies: Array<{ endpoint: string; body: string }> = [];
  const excluded = (body: string) => (body.match(/(?:id|game) != \(([^)]*)\)/)?.[1] ?? "").split(",").filter(Boolean).map(Number);
  // The "similar to" candidate list, written `id = (...)` (or `game = (...)`) inside the where clause.
  const candidates = (body: string) => body.match(/& (?:id|game) = \(([^)]*)\)/)?.[1].split(",").map(Number);
  const pool = (body: string) => ids.filter(id => !excluded(body).includes(id) && (candidates(body)?.includes(id) ?? true)).sort((a, b) => a - b);
  const gateway: IgdbGateway = {
    hasCredentials: () => true,
    async query<T>(endpoint: string, body: string) {
      bodies.push({ endpoint, body });
      if (endpoint === "keywords") return [{ id: 17326, name: "soulslike" }] as T[];
      if (body.startsWith("fields similar_games;")) {
        const seeds = body.match(/where id = \(([^)]*)\)/)![1].split(",").map(Number);
        return seeds.map(id => ({ id, similar_games: similar[id] ?? [] })) as T[];
      }
      if (body.startsWith("search ")) return [{ id: 119133, name: "Elden Ring", first_release_date: 1_645_747_200, cover: { image_id: "er" } }] as T[];
      const byId = body.match(/where id = \(([^)]*)\)/)?.[1];
      if (byId) return byId.split(",").map(Number).map(id => ({ id, name: `Game ${id}`, cover: { image_id: `cover-${id}` }, first_release_date: 1_400_000_000 })) as T[];
      const limit = Number(body.match(/limit (\d+);/)?.[1] ?? 10);
      const offset = Number(body.match(/offset (\d+);/)?.[1] ?? 0);
      // Made in Japan pages are involved-company rows that point at games.
      if (endpoint === "involved_companies") return pool(body).slice(offset, offset + limit).map(id => ({ id: id + 1000, game: id })) as T[];
      return pool(body).slice(offset, offset + limit).map(id => ({ id, name: `Game ${id}`, cover: { image_id: `cover-${id}` }, first_release_date: 1_400_000_000 })) as T[];
    },
    async count(endpoint, body) {
      bodies.push({ endpoint: `${endpoint}/count`, body });
      return pool(body).length;
    },
    async multiquery<T>(body: string) {
      bodies.push({ endpoint: "multiquery", body });
      if (body.includes('query franchises "franchises"')) {
        return [
          { name: "franchises", result: [{ id: 4, name: "Final Fantasy" }] as T[] },
          { name: "collections", result: [{ id: 39, name: "Final Fantasy" }, { id: 67, name: "Final Fantasy Crystal Chronicles" }] as T[] }
        ];
      }
      return [
        { name: "genres", result: [{ id: 12, name: "Role-playing (RPG)" }] as T[] },
        { name: "themes", result: [{ id: 19, name: "Horror" }] as T[] },
        { name: "gameModes", result: [{ id: 1, name: "Single player" }] as T[] },
        { name: "perspectives", result: [{ id: 2, name: "Third person" }] as T[] }
      ];
    },
    searchReleaseCandidates: async () => [],
    completed: { searchGames: async () => [], getGameDetails: async () => null },
    validateCredentials: async () => undefined,
    ...overrides
  };
  return { gateway, bodies };
}

function setup(gateway: IgdbGateway) {
  const dir = mkdtempSync(join(tmpdir(), "grt-randomizer-api-"));
  const db = openDatabase(join(dir, "tracker.db"));
  runMigrations(db);
  const app = createBackendApp({ db, autoSync: false, igdb: gateway, logger: quietLogger });
  cleanup.push(async () => { await app.close(); db.close(); rmSync(dir, { recursive: true, force: true }); });
  return { app, db };
}

function addCompletedGame(db: TrackerDatabase, igdbId: number) {
  db.prepare("insert into completed_games (id, title, normalized_title, identity_key, igdb_id) values (?, ?, ?, ?, ?)")
    .run(`completed-${igdbId}`, `Game ${igdbId}`, `game ${igdbId}`, `game ${igdbId}|pc`, igdbId);
}

describe("randomizer API", () => {
  test("a spin returns a pick, records it, and the next spin excludes it", async () => {
    const { gateway } = fakeGateway([1, 2, 3, 4, 5]);
    const { app } = setup(gateway);

    const first = await app.inject({ method: "POST", url: "/api/randomizer/spin", payload: {} });
    expect(first.statusCode).toBe(200);
    const pick = first.json().pick;
    expect(pick).toMatchObject({ title: `Game ${pick.igdbId}`, coverImageId: `cover-${pick.igdbId}`, releaseYear: 2014 });
    expect(first.json()).toMatchObject({ poolSize: 5, repeatAllowed: false });
    expect(first.json().reels).toHaveLength(4);

    const history = (await app.inject({ method: "GET", url: "/api/randomizer/history" })).json();
    expect(history.items.map((item: { igdbId: number }) => item.igdbId)).toEqual([pick.igdbId]);

    const second = await app.inject({ method: "POST", url: "/api/randomizer/spin", payload: {} });
    expect(second.json().pick.igdbId).not.toBe(pick.igdbId);
    expect(second.json().poolSize).toBe(4);
  });

  test("clearing history resets the cooldown", async () => {
    const { gateway } = fakeGateway([1, 2, 3]);
    const { app } = setup(gateway);
    await app.inject({ method: "POST", url: "/api/randomizer/spin", payload: {} });

    expect((await app.inject({ method: "DELETE", url: "/api/randomizer/history" })).json()).toEqual({ ok: true });
    expect((await app.inject({ method: "GET", url: "/api/randomizer/history" })).json()).toEqual({ items: [] });
    expect((await app.inject({ method: "POST", url: "/api/randomizer/spin", payload: {} })).json().poolSize).toBe(3);
  });

  test("hides completed games by default and upcoming games on request", async () => {
    const { gateway, bodies } = fakeGateway([1, 2, 3]);
    const { app, db } = setup(gateway);
    addCompletedGame(db, 1);
    db.prepare("insert into releases (id, igdb_id, title, normalized_title) values (?, ?, ?, ?)").run("r2", 2, "Game 2", "game 2");

    const spin = await app.inject({ method: "POST", url: "/api/randomizer/spin", payload: { hideUpcoming: true } });

    expect(spin.json()).toMatchObject({ pick: { igdbId: 3 }, poolSize: 1 });
    expect(bodies[0].body).toContain("id != (1,2)");

    const withCompleted = await app.inject({ method: "POST", url: "/api/randomizer/spin", payload: { hideCompleted: false } });
    expect(withCompleted.json().poolSize).toBe(2);
  });

  test("an impossible filter set returns a reason instead of an error", async () => {
    const { gateway } = fakeGateway([]);
    const { app } = setup(gateway);
    await app.inject({ method: "GET", url: "/api/randomizer/options" });

    const spin = await app.inject({ method: "POST", url: "/api/randomizer/spin", payload: { themeIds: [19], platformIds: [167], minRating: 90, minRatingCount: 50 } });

    expect(spin.statusCode).toBe(200);
    expect(spin.json()).toEqual({ pick: null, reels: [], poolSize: 0, repeatAllowed: false, reason: "No released Horror games on PlayStation 5, rated 90+ with 50+ ratings." });
  });

  test("option lists come from one multiquery and are cached", async () => {
    const { gateway, bodies } = fakeGateway([]);
    const { app } = setup(gateway);

    const first = await app.inject({ method: "GET", url: "/api/randomizer/options" });
    await app.inject({ method: "GET", url: "/api/randomizer/options" });

    expect(first.json()).toMatchObject({
      genres: [{ id: 12, name: "Role-playing (RPG)" }],
      themes: [{ id: 19, name: "Horror" }],
      gameModes: [{ id: 1, name: "Single player" }],
      perspectives: [{ id: 2, name: "Third person" }]
    });
    // Platforms and popular tags are static: mainstream families only.
    expect(new Set(first.json().platforms.map((platform: { family: string }) => platform.family))).toEqual(new Set(["PC", "PlayStation", "Xbox", "Nintendo"]));
    expect(first.json().tags).toContainEqual({ id: 477, name: "Metroidvania" });
    expect(bodies.filter(entry => entry.endpoint === "multiquery")).toHaveLength(1);
  });

  test("every spin is limited to mainstream platforms", async () => {
    const { gateway, bodies } = fakeGateway([1, 2]);
    const { app } = setup(gateway);

    await app.inject({ method: "POST", url: "/api/randomizer/spin", payload: {} });

    expect(bodies[0].body).toMatch(/platforms = \(6,7,8,/);
  });

  test("Made in Japan draws developer rows, then loads those games", async () => {
    const { gateway, bodies } = fakeGateway([10, 20, 30]);
    const { app, db } = setup(gateway);
    addCompletedGame(db, 20);

    const spin = await app.inject({ method: "POST", url: "/api/randomizer/spin", payload: { madeInJapan: true, presets: ["jrpg"] } });

    expect(spin.statusCode).toBe(200);
    expect([10, 30]).toContain(spin.json().pick.igdbId);
    expect(spin.json().poolSize).toBe(2);
    expect(bodies.map(entry => entry.endpoint)).toEqual(["involved_companies/count", "involved_companies", "games"]);
    expect(bodies[0].body).toContain("developer = true & company.country = 392 & game.game_type");
    expect(bodies[0].body).toContain("game.keywords = (521,19521)");
    expect(bodies[0].body).toContain("game != (20)");
    expect(bodies[2].body).toMatch(/where id = \((10,30|30,10)\)/);
  });

  test("similar-to spins among the seed's similar games and records the pick", async () => {
    const { gateway, bodies } = fakeGateway([1, 2, 3, 4, 5, 6], {}, { 100: [2, 3] });
    const { app } = setup(gateway);

    const spin = await app.inject({ method: "POST", url: "/api/randomizer/spin", payload: { similarToId: 100, similarToTitle: "Seed" } });

    expect(spin.statusCode).toBe(200);
    expect([2, 3]).toContain(spin.json().pick.igdbId);
    expect(spin.json()).toMatchObject({ poolSize: 2 });
    expect(spin.json().similarWidened).toBeUndefined();
    expect(bodies.find(entry => entry.endpoint === "games/count")?.body).toContain("& id = (2,3)");
  });

  test("similar-to widens to games two matches agree on before repeating a pick", async () => {
    // 7 is similar to both direct matches; 8 and 9 to only one, so they stay out.
    const { gateway } = fakeGateway([2, 3, 7, 8, 9], {}, { 100: [2, 3], 2: [7, 8, 100], 3: [7, 9] });
    const { app } = setup(gateway);

    const direct = [];
    for (let spin = 0; spin < 2; spin++) direct.push((await app.inject({ method: "POST", url: "/api/randomizer/spin", payload: { similarToId: 100 } })).json().pick.igdbId);
    expect(direct.sort()).toEqual([2, 3]);

    const widened = await app.inject({ method: "POST", url: "/api/randomizer/spin", payload: { similarToId: 100 } });
    expect(widened.json()).toMatchObject({ pick: { igdbId: 7 }, similarWidened: true, repeatAllowed: false });
  });

  test("a seed with no similar games returns a reason", async () => {
    const { gateway } = fakeGateway([1, 2]);
    const { app } = setup(gateway);

    const spin = await app.inject({ method: "POST", url: "/api/randomizer/spin", payload: { similarToId: 100, similarToTitle: "Lonely Game" } });

    expect(spin.json()).toEqual({ pick: null, reels: [], poolSize: 0, repeatAllowed: false, reason: "IGDB lists no similar games for Lonely Game." });
  });

  test("series and game searches return labelled results", async () => {
    const { gateway } = fakeGateway([]);
    const { app } = setup(gateway);

    const series = await app.inject({ method: "GET", url: "/api/randomizer/series?search=final%20fantasy" });
    const games = await app.inject({ method: "GET", url: "/api/randomizer/games?search=elden" });

    expect(series.json()).toEqual({
      items: [
        { kind: "franchise", id: 4, name: "Final Fantasy" },
        { kind: "collection", id: 39, name: "Final Fantasy" },
        { kind: "collection", id: 67, name: "Final Fantasy Crystal Chronicles" }
      ]
    });
    expect(games.json()).toEqual({ items: [{ id: 119133, name: "Elden Ring", year: 2022, coverImageId: "er" }] });
    expect((await app.inject({ method: "GET", url: "/api/randomizer/games?search=e" })).statusCode).toBe(400);
  });

  test("tag search finds IGDB keywords and validates the text", async () => {
    const { gateway, bodies } = fakeGateway([]);
    const { app } = setup(gateway);

    const found = await app.inject({ method: "GET", url: "/api/randomizer/tags?search=souls" });
    const tooShort = await app.inject({ method: "GET", url: "/api/randomizer/tags?search=s" });

    expect(found.json()).toEqual({ items: [{ id: 17326, name: "soulslike" }] });
    expect(bodies).toEqual([{ endpoint: "keywords", body: 'fields id,name; where name ~ *"souls"*; sort name asc; limit 20;' }]);
    expect(tooShort.statusCode).toBe(400);
  });

  test("missing IGDB credentials return 409 before any request", async () => {
    const { gateway, bodies } = fakeGateway([1], { hasCredentials: () => false });
    const { app } = setup(gateway);

    const spin = await app.inject({ method: "POST", url: "/api/randomizer/spin", payload: {} });
    const options = await app.inject({ method: "GET", url: "/api/randomizer/options" });

    expect(spin.statusCode).toBe(409);
    expect(spin.json()).toEqual({ error: "IGDB credentials are required for the randomizer" });
    expect(options.statusCode).toBe(409);
    expect(bodies).toEqual([]);
  });

  test("invalid filters return 400", async () => {
    const { gateway } = fakeGateway([1]);
    const { app } = setup(gateway);

    const spin = await app.inject({ method: "POST", url: "/api/randomizer/spin", payload: { minRating: 150 } });

    expect(spin.statusCode).toBe(400);
    expect(spin.json().error).toContain("minRating");
  });

  test("an IGDB failure surfaces as the safe server error and records nothing", async () => {
    const { gateway } = fakeGateway([1], { count: async () => { throw new Error("IGDB games/count failed: 503"); } });
    const { app } = setup(gateway);

    const spin = await app.inject({ method: "POST", url: "/api/randomizer/spin", payload: {} });

    expect(spin.statusCode).toBe(500);
    expect(spin.json().error).not.toContain("503");
    expect((await app.inject({ method: "GET", url: "/api/randomizer/history" })).json()).toEqual({ items: [] });
  });
});
