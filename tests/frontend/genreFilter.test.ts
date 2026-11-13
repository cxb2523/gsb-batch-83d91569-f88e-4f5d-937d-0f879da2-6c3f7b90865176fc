import { describe, expect, test } from "vitest";
import { filterByGenre, genreOptions } from "../../apps/frontend/src/genreFilter";
import { completedGenres } from "../../shared/completedGenres";

const items = [
  { id: "a", genres: ["Shooter", "Adventure"] },
  { id: "b", genres: ["adventure ", "RPG"] },
  { id: "c", genres: [] as string[] }
];

describe("genre filter", () => {
  test("collects unique, sorted genre options ignoring case", () => {
    expect(genreOptions(items, item => item.genres)).toEqual(["Adventure", "RPG", "Shooter"]);
  });

  test("keeps every item when no genre is chosen", () => {
    expect(filterByGenre(items, "", item => item.genres)).toHaveLength(3);
  });

  test("matches genres case-insensitively", () => {
    expect(filterByGenre(items, "Adventure", item => item.genres).map(item => item.id)).toEqual(["a", "b"]);
  });

  test("completed games match on their own and IGDB genres", () => {
    expect(completedGenres({ genres: ["Strategy"], igdbGenres: ["Tactical"] })).toEqual(["Strategy", "Tactical"]);
  });
});
