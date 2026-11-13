import { describe, expect, test, vi } from "vitest";
import { SteamGridDbClient } from "../../apps/backend/src/steamgriddb/client";

describe("SteamGridDB client", () => {
  test("uses bearer auth, searches by title, and returns safe static grid artwork", async () => {
    const calls: Array<{ url: string; auth?: string | null }> = [];
    const fetcher = vi.fn(async (url: string | URL, init?: RequestInit) => {
      calls.push({ url: String(url), auth: init?.headers ? new Headers(init.headers).get("Authorization") : null });
      if (String(url).includes("/search/autocomplete/")) {
        return new Response(JSON.stringify({ success: true, data: [{ id: 44, name: "Persona 4 Revival" }] }), { status: 200 });
      }
      return new Response(JSON.stringify({
        success: true,
        data: [
          { id: 1, url: "https://cdn2.steamgriddb.com/grid/nsfw.jpg", nsfw: true, style: "alternate", animated: false },
          { id: 2, url: "https://cdn2.steamgriddb.com/grid/hero.webm", nsfw: false, style: "alternate", animated: true },
          { id: 3, url: "https://cdn2.steamgriddb.com/grid/hero.jpg", nsfw: false, style: "alternate", animated: false }
        ]
      }), { status: 200 });
    }) as unknown as typeof fetch;

    const client = new SteamGridDbClient("sgdb-key", fetcher);
    await expect(client.findArtwork("Persona 4 Revival")).resolves.toEqual([
      { imageId: "steamgriddb-3", source: "steamgriddb", url: "https://cdn2.steamgriddb.com/grid/hero.jpg" }
    ]);

    expect(calls).toHaveLength(2);
    expect(calls.every(call => call.auth === "Bearer sgdb-key")).toBe(true);
    expect(calls[0].url).toContain("/search/autocomplete/Persona%204%20Revival");
    expect(calls[1].url).toContain("/grids/game/44");
  });

  test("returns no artwork when the API key is missing and throws on provider lookup failure", async () => {
    const missing = new SteamGridDbClient("", vi.fn() as unknown as typeof fetch);
    await expect(missing.findArtwork("Anything")).resolves.toEqual([]);

    const failing = new SteamGridDbClient("sgdb-key", vi.fn(async () => new Response("nope", { status: 500 })) as unknown as typeof fetch);
    await expect(failing.findArtwork("Anything")).rejects.toThrow("SteamGridDB request failed: 500");
  });
});
