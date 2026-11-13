import { describe, expect, test } from "vitest";
import { planReleaseSync, prepareSyncCandidate } from "../../apps/backend/src/sync/releaseSyncPlanner";
import { createReleasePolicy } from "../../apps/backend/src/sync/releasePolicy";
import type { IgdbGameLike, ReleaseOverride } from "../../shared/types";

// The sync rules these tests run under: Atlus (IGDB company 1) on PC from 2026.
const policy = createReleasePolicy({ publisherIds: [1], platforms: ["pc"], trackFrom: "2026-01-01" });
const prepare = (game: IgdbGameLike) => prepareSyncCandidate(game, policy);

describe("release sync planner", () => {
  test("skips blocked candidates before evaluating sync rules", () => {
    const plan = planReleaseSync({
      candidate: prepare(game(101, "Blocked Game")),
      blocked: true,
      existedBefore: false,
      existing: null,
      enrichedArtworks: []
    });

    expect(plan).toEqual({ action: "skip", title: "Blocked Game", reason: "manually blocked" });
  });

  test("a candidate is decided once: rejected games carry their reasons into the skip plan", () => {
    const rejected = prepare({ ...game(105, "Too Old"), first_release_date: 1735603200 });

    expect(rejected.accepted).toBe(false);
    expect(planReleaseSync({ candidate: rejected, blocked: false, existedBefore: false, existing: null, enrichedArtworks: [] }))
      .toMatchObject({ action: "skip", title: "Too Old" });
  });

  test("plans added and repaired for a new release with SteamGridDB enrichment", () => {
    const plan = planReleaseSync({
      candidate: prepare(game(102, "Persona 4 Revival")),
      blocked: false,
      existedBefore: false,
      existing: null,
      enrichedArtworks: [{ imageId: "sgdb-102", source: "steamgriddb", url: "https://cdn2.steamgriddb.com/grid/sgdb-102.jpg" }]
    });

    expect(plan.action).toBe("save");
    if (plan.action !== "save") return;
    expect(plan.outcome).toBe("repaired");
    expect(plan.release.id).toBe("igdb-102");
    expect(plan.release.artworks).toEqual([{ imageId: "sgdb-102", source: "steamgriddb", url: "https://cdn2.steamgriddb.com/grid/sgdb-102.jpg" }]);
  });

  test("plans unchanged for an existing release with no merge changes", () => {
    const candidate = prepare(game(103, "Existing Game"));
    const plan = planReleaseSync({
      candidate,
      blocked: false,
      existedBefore: true,
      existing: { releaseId: "igdb-103", artworks: [], overrides: [] },
      enrichedArtworks: []
    });

    expect(plan.action).toBe("save");
    if (plan.action !== "save") return;
    expect(plan.outcome).toBe("unchanged");
  });

  test("plans repaired when existing overrides change incoming release fields", () => {
    const overrides: ReleaseOverride[] = [
      { field: "dateText", value: "Late 2027", sourceType: "user" },
      { field: "datePrecision", value: "Window", sourceType: "user" },
      { field: "releaseWindow", value: "Late 2027", sourceType: "user" }
    ];
    const plan = planReleaseSync({
      candidate: prepare(game(104, "Override Game")),
      blocked: false,
      existedBefore: true,
      existing: { releaseId: "igdb-104", artworks: [], overrides },
      enrichedArtworks: []
    });

    expect(plan.action).toBe("save");
    if (plan.action !== "save") return;
    expect(plan.outcome).toBe("repaired");
    expect(plan.release).toMatchObject({
      dateText: "Late 2027",
      datePrecision: "Window",
      releaseWindow: "Late 2027",
      effectiveSortDate: "2027-10-01"
    });
  });
});

function game(id: number, name: string): IgdbGameLike {
  return {
    id,
    name,
    game_type: 0,
    first_release_date: 1802908800,
    platforms: [{ id: 6, abbreviation: "PC", slug: "win" }],
    involved_companies: [{ publisher: true, company: { id: 1, name: "Atlus" } }]
  };
}
