import { describe, expect, test, vi } from "vitest";
import { createIgdbGateway } from "../../apps/backend/src/igdb/gateway";
import type { TokenConfig } from "../../apps/backend/src/igdb/token";

function fakeIgdb() {
  const calls: Array<{ url: string; at: number; auth: string | null }> = [];
  let tokenCount = 0;
  const fetcher = vi.fn(async (url: string | URL, init?: RequestInit) => {
    calls.push({ url: String(url), at: Date.now(), auth: init?.headers ? new Headers(init.headers).get("Authorization") : null });
    if (String(url).includes("oauth2/token")) {
      tokenCount++;
      return new Response(JSON.stringify({ access_token: `token-${tokenCount}` }), { status: 200 });
    }
    return new Response(JSON.stringify([{ id: 1, name: "Persona 4 Revival" }]), { status: 200 });
  }) as unknown as typeof fetch;
  return { fetcher, calls, tokenRequests: () => tokenCount };
}

describe("IGDB gateway", () => {
  test("reuses one token across searches from different callers", async () => {
    const igdb = fakeIgdb();
    const gateway = createIgdbGateway({ readConfig: () => ({ clientId: "id", clientSecret: "secret" }), fetcher: igdb.fetcher });

    await Promise.all([gateway.searchReleaseCandidates("Persona"), gateway.completed.searchGames("Persona"), gateway.completed.getGameDetails(1)]);

    expect(igdb.tokenRequests()).toBe(1);
  });

  test("fetches a new token when the saved credentials change", async () => {
    const igdb = fakeIgdb();
    let config: TokenConfig = { clientId: "id", clientSecret: "secret" };
    const gateway = createIgdbGateway({ readConfig: () => config, fetcher: igdb.fetcher });

    await gateway.searchReleaseCandidates("Persona");
    config = { clientId: "id", clientSecret: "new-secret" };
    await gateway.searchReleaseCandidates("Persona");

    expect(igdb.tokenRequests()).toBe(2);
    expect(igdb.calls.at(-1)?.auth).toBe("Bearer token-2");
  });

  test("spaces requests from concurrent callers by the shared rate limit", async () => {
    const igdb = fakeIgdb();
    const gateway = createIgdbGateway({ readConfig: () => ({ clientId: "id", accessToken: "static" }), fetcher: igdb.fetcher });

    await Promise.all([gateway.searchReleaseCandidates("A"), gateway.searchReleaseCandidates("B"), gateway.completed.searchGames("C")]);

    // 250 ms apart at 4 requests per second; Windows timers can fire up to one ~15 ms clock tick early.
    const times = igdb.calls.map(call => call.at);
    expect(times[1] - times[0]).toBeGreaterThanOrEqual(230);
    expect(times[2] - times[1]).toBeGreaterThanOrEqual(230);
  });

  test("escapes quotes in search titles", async () => {
    const igdb = fakeIgdb();
    const gateway = createIgdbGateway({ readConfig: () => ({ clientId: "id", accessToken: "static" }), fetcher: igdb.fetcher });

    await gateway.searchReleaseCandidates('Say "Hi"');

    const body = String(vi.mocked(igdb.fetcher).mock.calls[0][1]?.body);
    expect(body).toContain('search "Say \\"Hi\\"";');
  });

  test("count posts to the endpoint's count route and reads the single count object", async () => {
    const fetcher = vi.fn(async (url: string | URL, init?: RequestInit) => {
      expect(String(url)).toBe("https://api.igdb.com/v4/games/count");
      expect(init?.body).toBe("where cover != null;");
      return new Response(JSON.stringify({ count: 1234 }), { status: 200 });
    }) as unknown as typeof fetch;
    const gateway = createIgdbGateway({ readConfig: () => ({ clientId: "id", accessToken: "static" }), fetcher });

    await expect(gateway.count("games", "where cover != null;")).resolves.toBe(1234);
  });

  test("count rejects a response without a count", async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify([]), { status: 200 })) as unknown as typeof fetch;
    const gateway = createIgdbGateway({ readConfig: () => ({ clientId: "id", accessToken: "static" }), fetcher });

    await expect(gateway.count("games", "where cover != null;")).rejects.toThrow("returned no count");
  });

  test("multiquery returns every named sub-query result from one request", async () => {
    const fetcher = vi.fn(async (url: string | URL) => {
      expect(String(url)).toBe("https://api.igdb.com/v4/multiquery");
      return new Response(JSON.stringify([
        { name: "genres", result: [{ id: 12, name: "Role-playing (RPG)" }] },
        { name: "themes", result: [{ id: 19, name: "Horror" }] }
      ]), { status: 200 });
    }) as unknown as typeof fetch;
    const gateway = createIgdbGateway({ readConfig: () => ({ clientId: "id", accessToken: "static" }), fetcher });

    const results = await gateway.multiquery<{ id: number; name: string }>('query genres "genres" { fields id,name; limit 500; };');

    expect(results.map(entry => entry.name)).toEqual(["genres", "themes"]);
    expect(results[0].result).toEqual([{ id: 12, name: "Role-playing (RPG)" }]);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  test("reports whether credentials are configured", () => {
    expect(createIgdbGateway({ readConfig: () => ({ clientId: "id" }) }).hasCredentials()).toBe(false);
    expect(createIgdbGateway({ readConfig: () => ({ clientId: "id", accessToken: "t" }) }).hasCredentials()).toBe(true);
  });
});

describe("IGDB gateway seam", () => {
  test("the manual release search route uses the injected gateway", async () => {
    const { mkdtempSync, rmSync } = await import("node:fs");
    const { join } = await import("node:path");
    const { tmpdir } = await import("node:os");
    const { openDatabase } = await import("../../apps/backend/src/database/db");
    const { runMigrations } = await import("../../apps/backend/src/database/migrations");
    const { createBackendApp } = await import("../../apps/backend/src/server");
    const dir = mkdtempSync(join(tmpdir(), "grt-igdb-seam-"));
    const db = openDatabase(join(dir, "tracker.db"));
    runMigrations(db);
    const searched: string[] = [];
    const fakeGateway = {
      hasCredentials: () => true,
      query: async () => [],
      count: async () => 0,
      multiquery: async () => [],
      searchReleaseCandidates: async (title: string) => {
        searched.push(title);
        return [{ id: 42, name: "Octopath Traveler 0", game_type: 0, first_release_date: 1802908800, platforms: [{ abbreviation: "PC" }] }];
      },
      completed: { searchGames: async () => [], getGameDetails: async () => null },
      validateCredentials: async () => undefined
    };
    const app = createBackendApp({ db, autoSync: false, igdb: fakeGateway });

    const response = await app.inject({ method: "GET", url: "/api/releases/manual/search?q=Octopath" });

    expect(response.statusCode).toBe(200);
    expect(searched).toEqual(["Octopath"]);
    expect(response.json().items[0]).toMatchObject({ igdbId: 42, title: "Octopath Traveler 0" });
    await app.close();
    db.close();
    rmSync(dir, { recursive: true, force: true });
  });
});
