import { describe, expect, test } from "vitest";
import { buildPublisherGameQuery, discoverIgdbCandidates, findCompanyByName, searchCompanies } from "../../apps/backend/src/sync/igdbCandidateSource";
import type { IgdbGameLike } from "../../shared/types";

class FakeIgdbClient {
  calls: Array<{ endpoint: string; body: string }> = [];

  async query<T>(endpoint: string, body: string): Promise<T[]> {
    this.calls.push({ endpoint, body });
    if (endpoint === "games" && body.includes("involved_companies.company = (1)")) return [game(101, "Publisher Game")] as T[];
    if (endpoint === "companies" && body.includes('name ~ *"cap"*')) {
      return [{ id: 9, name: "Capcom Shop", published: [1] }, { id: 37, name: "Capcom", published: [1, 2, 3] }] as T[];
    }
    if (endpoint === "companies" && body.includes('name = "Sega"')) {
      return [{ id: 500, name: "Sega", published: [1] }, { id: 112, name: "Sega", published: [1, 2, 3, 4] }] as T[];
    }
    return [];
  }
}

describe("IGDB candidate source", () => {
  test("discovers the tracked publishers' games", async () => {
    const client = new FakeIgdbClient();

    const games = await discoverIgdbCandidates(client, { publisherIds: [1], trackFrom: "2026-01-01" });

    expect(games.map(item => item.name)).toEqual(["Publisher Game"]);
  });

  test("with no tracked publishers, sync explains what to do instead of asking IGDB", async () => {
    const client = new FakeIgdbClient();

    await expect(discoverIgdbCandidates(client, { publisherIds: [], trackFrom: "2026-01-01" })).rejects.toThrow("No publishers are tracked yet");
    expect(client.calls).toEqual([]);
  });

  test("the game query keeps accepted game types, the tracked ids, the track-from date and the metadata fields", () => {
    const query = buildPublisherGameQuery([17, 42], "2025-06-01", 0);

    expect(query).toContain("involved_companies.company = (17,42)");
    expect(query).toContain("game_type = (0,1,2,4,8,9,10,11)");
    expect(query).toContain("first_release_date >= 1748736000");
    expect(query).toContain("release_dates.y >= 2025");
    expect(query).not.toContain("updated_at >=");
    expect(query).toContain("artworks.image_id");
    expect(query).toContain("involved_companies.company.id");
  });

  test("company search lists the companies that published the most games first", async () => {
    expect(await searchCompanies(new FakeIgdbClient(), "cap")).toEqual([{ id: 37, name: "Capcom" }, { id: 9, name: "Capcom Shop" }]);
  });

  test("an exact-name lookup picks the company with that name that published the most games", async () => {
    expect(await findCompanyByName(new FakeIgdbClient(), "Sega")).toEqual({ id: 112, name: "Sega" });
    expect(await findCompanyByName(new FakeIgdbClient(), "Nobody Games")).toBeNull();
  });
});

function game(id: number, name: string): IgdbGameLike {
  return { id, name, game_type: 0, first_release_date: 1767225600 };
}
