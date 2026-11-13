import { describe, expect, test } from "vitest";
import { addIds, keepOfferedPlatforms, labelKey, removeIds, setFlag, setNumber, setSimilarTo, toggleGroup, toggleId, togglePreset } from "../../apps/frontend/src/randomizerFilters";

describe("randomizer filter edits", () => {
  test("id lists never repeat an id and become absent when emptied", () => {
    const withTags = addIds(addIds({}, "tagIds", [5, 7]), "tagIds", [7]);
    expect(withTags.tagIds).toEqual([5, 7]);

    const cleared = removeIds(withTags, "tagIds", [5, 7]);
    expect(cleared).toHaveProperty("tagIds", undefined);
  });

  test("toggleId adds then removes; toggleGroup selects a whole family or clears it", () => {
    const on = toggleId({}, "platformIds", 6);
    expect(on.platformIds).toEqual([6]);
    expect(toggleId(on, "platformIds", 6).platformIds).toBeUndefined();

    const family = toggleGroup({ platformIds: [6] }, "platformIds", [6, 48]);
    expect(family.platformIds).toEqual([6, 48]);
    expect(toggleGroup(family, "platformIds", [6, 48]).platformIds).toBeUndefined();
  });

  test("presets and on-only flags are absent when off", () => {
    const jrpg = togglePreset({}, "jrpg");
    expect(jrpg.presets).toEqual(["jrpg"]);
    expect(togglePreset(jrpg, "jrpg").presets).toBeUndefined();
    expect(setFlag({ madeInJapan: true }, "madeInJapan", false).madeInJapan).toBeUndefined();
  });

  test("number fields clear on blank or non-numeric text", () => {
    expect(setNumber({}, "minRating", " 70 ").minRating).toBe(70);
    expect(setNumber({ minRating: 70 }, "minRating", "").minRating).toBeUndefined();
    expect(setNumber({ minRating: 70 }, "minRating", "abc").minRating).toBeUndefined();
  });

  test("similar-to sets and clears the seed game and its title together", () => {
    const seeded = setSimilarTo({}, { id: 119133, name: "Elden Ring" });
    expect(seeded).toMatchObject({ similarToId: 119133, similarToTitle: "Elden Ring" });
    expect(setSimilarTo(seeded, null)).toMatchObject({ similarToId: undefined, similarToTitle: undefined });
  });

  test("saved platforms the server no longer offers are dropped, and unchanged filters keep their identity", () => {
    const filters = { platformIds: [6, 999] };
    expect(keepOfferedPlatforms(filters, new Set([6])).platformIds).toEqual([6]);
    const current = { platformIds: [6] };
    expect(keepOfferedPlatforms(current, new Set([6]))).toBe(current);
  });

  test("label keys name tags and series for remembered chip names", () => {
    expect(labelKey("tag", 477)).toBe("tag:477");
    expect(labelKey("franchise", 4)).toBe("franchise:4");
  });
});
