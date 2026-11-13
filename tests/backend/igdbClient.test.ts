import { describe, expect, test, vi } from "vitest";
import { IgdbClient } from "../../apps/backend/src/igdb/client";

describe("IGDB client authentication", () => {
  test("refreshes with client secret instead of using stale static token", async () => {
    const calls: Array<{ url: string; body?: BodyInit | null; auth?: string | null }> = [];
    const fetcher = vi.fn(async (url: string | URL, init?: RequestInit) => {
      calls.push({ url: String(url), body: init?.body, auth: init?.headers ? new Headers(init.headers).get("Authorization") : null });
      if (String(url).includes("oauth2/token")) {
        return new Response(JSON.stringify({ access_token: "fresh-token" }), { status: 200 });
      }
      return new Response(JSON.stringify([{ id: 1, name: "Atlus" }]), { status: 200 });
    }) as unknown as typeof fetch;

    const client = new IgdbClient({ clientId: "client", clientSecret: "secret", accessToken: "stale-token" }, fetcher);

    await client.query("companies", "fields id,name; limit 1;");

    expect(calls[0].url).toContain("oauth2/token");
    expect(calls[1].auth).toBe("Bearer fresh-token");
  });

  test("retries once with refreshed token after 401", async () => {
    let gameCalls = 0;
    const fetcher = vi.fn(async (url: string | URL, init?: RequestInit) => {
      if (String(url).includes("oauth2/token")) {
        return new Response(JSON.stringify({ access_token: "retry-token" }), { status: 200 });
      }
      gameCalls++;
      if (gameCalls === 1) return new Response("nope", { status: 401 });
      return new Response(JSON.stringify([{ id: 1, name: "Atlus" }]), { status: 200 });
    }) as unknown as typeof fetch;

    const client = new IgdbClient({ clientId: "client", clientSecret: "secret" }, fetcher);

    await expect(client.query("companies", "fields id,name; limit 1;")).resolves.toHaveLength(1);
    expect(gameCalls).toBe(2);
  });

  test("a hung request fails with a timeout error instead of retrying", async () => {
    let gameCalls = 0;
    const fetcher = vi.fn((_url: string | URL, init?: RequestInit) => {
      gameCalls++;
      return new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => reject(init.signal?.reason));
      });
    }) as unknown as typeof fetch;

    const client = new IgdbClient({ clientId: "client", accessToken: "static" }, fetcher, 20);

    await expect(client.query("games", "fields id; limit 1;")).rejects.toThrow("IGDB games timed out after 20 ms");
    expect(gameCalls).toBe(1);
  });
});
