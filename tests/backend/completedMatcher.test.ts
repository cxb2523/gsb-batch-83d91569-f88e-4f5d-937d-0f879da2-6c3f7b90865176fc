import { describe, expect, test, vi } from "vitest";
import { createCompletedMatcher } from "../../apps/backend/src/completed/completedIgdbMatcher";
import type { IgdbGameLike } from "../../shared/types";

const hades: IgdbGameLike = { id: 1, name: "Hades", platforms: [{ abbreviation: "PC" }], summary: "Rogue-like." };
const hadesII: IgdbGameLike = { id: 2, name: "Hades II", platforms: [{ abbreviation: "PC" }] };

function matcher({ credentials = true, games = [hades, hadesII] }: { credentials?: boolean; games?: IgdbGameLike[] } = {}) {
  const completed = {
    searchGames: vi.fn(async () => games),
    getGameDetails: vi.fn(async (id: number) => games.find(game => game.id === id) ?? null)
  };
  return { completed, matcher: createCompletedMatcher({ hasCredentials: () => credentials, completed }) };
}

describe("completed IGDB matcher", () => {
  test("ranks candidates by title and platform", async () => {
    const { matcher: m } = matcher();

    const result = await m.candidates({ title: "Hades", userPlatform: "PC" });

    expect(result.ok && result.value.map(candidate => candidate.igdbId)).toEqual([1, 2]);
  });

  test("reports missing credentials and unknown games instead of calling IGDB", async () => {
    const { matcher: offline, completed } = matcher({ credentials: false });
    const { matcher: online } = matcher();

    expect(await offline.candidates({ title: "Hades", userPlatform: "PC" })).toEqual({ ok: false, reason: "no-credentials" });
    expect(await offline.metadataFor(1)).toEqual({ ok: false, reason: "no-credentials" });
    expect(completed.searchGames).not.toHaveBeenCalled();
    expect(await online.metadataFor(999)).toEqual({ ok: false, reason: "not-found" });
  });

  test("metadataFor returns the chosen game's IGDB metadata as matched", async () => {
    const { matcher: m } = matcher();

    expect(await m.metadataFor(1)).toMatchObject({ ok: true, value: { igdbId: 1, summary: "Rogue-like.", matchStatus: "matched" } });
  });

});
