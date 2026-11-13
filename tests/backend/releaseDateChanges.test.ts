import { afterEach, describe, expect, test } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { openDatabase, type TrackerDatabase } from "../../apps/backend/src/database/db";
import { runMigrations } from "../../apps/backend/src/database/migrations";
import { getRelease, listReleases } from "../../apps/backend/src/database/releaseReadModel";
import { updateRelease } from "../../apps/backend/src/actions/releaseActions";
import { runSync } from "../../apps/backend/src/sync/syncRun";
import { resetWriteQueueForTests } from "../../apps/backend/src/database/writeQueue";
import { createSyncSettingsStore } from "../../apps/backend/src/sync/syncSettingsStore";
import { classifyDateChange, type DateSnapshot } from "../../apps/backend/src/releaseDates/dateChanges";
import type { IgdbGameLike } from "../../shared/types";

let dirs: string[] = [];
let dbs: TrackerDatabase[] = [];

function tempDb() {
  const dir = mkdtempSync(join(tmpdir(), "grt-date-changes-"));
  dirs.push(dir);
  const db = openDatabase(join(dir, "tracker.db"));
  dbs.push(db);
  runMigrations(db);
  createSyncSettingsStore(db).addPublishers([{ id: 1, name: "Atlus" }]);
  return db;
}

afterEach(() => {
  for (const db of dbs) db.close();
  dbs = [];
  for (const dir of dirs) rmSync(dir, { recursive: true, force: true });
  dirs = [];
  resetWriteQueueForTests();
});

const noArtwork = { steamGridClient: { findArtwork: async () => [] } };
const unix = (day: string) => Date.parse(`${day}T00:00:00Z`) / 1000;
const game = (day: string): IgdbGameLike => ({
  id: 777,
  name: "Trails Beyond the Horizon",
  game_type: 0,
  first_release_date: unix(day),
  platforms: [{ id: 6, abbreviation: "PC", slug: "win" }],
  involved_companies: [{ publisher: true, company: { id: 1, name: "NIS America" } }]
});

const snap = (dateText: string, datePrecision: DateSnapshot["datePrecision"], sortDate: string | null, releaseDate: string | null = null): DateSnapshot =>
  ({ dateText, datePrecision, sortDate, releaseDate });

describe("classifying a date change", () => {
  test("a later date is a delay, an earlier one moved the game up, rewording is no change", () => {
    expect(classifyDateChange(snap("Mar 14, 2027", "Exact", "2027-03-14", "2027-03-14"), snap("Jun 2, 2027", "Exact", "2027-06-02", "2027-06-02"))).toBe("delayed");
    expect(classifyDateChange(snap("Jun 2, 2027", "Exact", "2027-06-02", "2027-06-02"), snap("Mar 14, 2027", "Exact", "2027-03-14", "2027-03-14"))).toBe("earlier");
    expect(classifyDateChange(snap("2027", "Year", "2027-12-31"), snap("2028", "Year", "2028-12-31"))).toBe("delayed");
    expect(classifyDateChange(snap("Q4 2027", "Window", "2027-12-31"), snap("Fourth quarter 2027", "Window", "2027-12-31"))).toBeNull();
    expect(classifyDateChange(snap("2027", "Year", "2027-12-31"), snap("2027", "Year", "2027-12-31"))).toBeNull();
  });

  test("a sharper date inside the old period is the date being announced", () => {
    expect(classifyDateChange(snap("2027", "Year", "2027-12-31"), snap("Mar 14, 2027", "Exact", "2027-03-14", "2027-03-14"))).toBe("announced");
    expect(classifyDateChange(snap("Mar 2027", "Month", "2027-03-31"), snap("Mar 14, 2027", "Exact", "2027-03-14", "2027-03-14"))).toBe("announced");
    expect(classifyDateChange(snap("Q4 2027", "Window", "2027-12-31"), snap("Nov 2027", "Month", "2027-11-30"))).toBe("announced");
    expect(classifyDateChange(snap("TBA", "TBA", null), snap("2027", "Year", "2027-12-31"))).toBe("announced");
  });

  test("a vague date sorted by the start of its period (no IGDB timestamp, or typed by hand) is announced, not delayed, when it gets a day", () => {
    expect(classifyDateChange(snap("2027", "Year", "2027-01-01"), snap("Mar 14, 2027", "Exact", "2027-03-14", "2027-03-14"))).toBe("announced");
    expect(classifyDateChange(snap("Q4 2027", "Window", "2027-10-01"), snap("Nov 20, 2027", "Exact", "2027-11-20", "2027-11-20"))).toBe("announced");
    expect(classifyDateChange(snap("Q4 2027", "Window", "2027-10-01"), snap("Feb 2028", "Month", "2028-02-01"))).toBe("delayed");
  });

  test("a sharper date before the old period moved the game up; losing the date is a delay", () => {
    expect(classifyDateChange(snap("Q4 2027", "Window", "2027-12-31"), snap("Feb 2027", "Month", "2027-02-28"))).toBe("earlier");
    expect(classifyDateChange(snap("Mar 14, 2027", "Exact", "2027-03-14", "2027-03-14"), snap("TBA", "TBA", null))).toBe("delayed");
  });
});

describe("date history from sync", () => {
  test("a sync that moves a game's date records the change; the list shows the newest and the page all of them", async () => {
    const db = tempDb();
    await runSync(db, [game("2027-03-14")], undefined, noArtwork);
    expect(listReleases(db, {}).items[0].lastDateChange).toBeNull();

    await runSync(db, [game("2027-06-02")], undefined, noArtwork);
    await runSync(db, [game("2027-06-02")], undefined, noArtwork);
    await runSync(db, [game("2027-05-20")], undefined, noArtwork);

    const [item] = listReleases(db, {}).items;
    expect(item.lastDateChange).toMatchObject({ kind: "earlier", toText: item.dateText });
    expect(getRelease(db, item.id)!.dateChanges!.map(change => change.kind)).toEqual(["earlier", "delayed"]);
  });

  test("the list shows the newest delay or move up; a date announced later doesn't hide it", async () => {
    const db = tempDb();
    const vague = (human: string, day: string): IgdbGameLike => ({ ...game(day), release_dates: [{ human, date: Date.parse(`${day}T00:00:00Z`) / 1000 }] });
    await runSync(db, [vague("2027", "2027-12-31")], undefined, noArtwork);
    await runSync(db, [vague("2028", "2028-12-31")], undefined, noArtwork);
    await runSync(db, [game("2028-05-05")], undefined, noArtwork);

    const [item] = listReleases(db, {}).items;
    expect(getRelease(db, item.id)!.dateChanges!.map(change => change.kind)).toEqual(["announced", "delayed"]);
    expect(item.lastDateChange).toMatchObject({ kind: "delayed", fromText: "2027" });
  });

  test("a date the user set by hand is kept, so sync records nothing", async () => {
    const db = tempDb();
    await runSync(db, [game("2027-03-14")], undefined, noArtwork);
    const [item] = listReleases(db, {}).items;
    await updateRelease(db, item.id, { dateText: "2028", releaseDate: "", datePrecision: "Year", releaseWindow: "2028" });

    await runSync(db, [game("2027-09-01")], undefined, noArtwork);

    expect(getRelease(db, item.id)!.dateChanges).toEqual([]);
  });

  test("changing a game's date to a vague one by hand drops the old exact day, so it sorts by the new date", async () => {
    const db = tempDb();
    await runSync(db, [game("2027-03-14")], undefined, noArtwork);
    const [item] = listReleases(db, {}).items;

    await updateRelease(db, item.id, { dateText: "2028", datePrecision: "Year", releaseWindow: "2028" });

    expect(getRelease(db, item.id)).toMatchObject({ dateText: "2028", datePrecision: "Year", releaseDate: null, effectiveSortDate: "2028-01-01" });
    await runSync(db, [game("2027-09-01")], undefined, noArtwork);
    expect(getRelease(db, item.id)).toMatchObject({ dateText: "2028", releaseDate: null, effectiveSortDate: "2028-01-01" });
    expect(getRelease(db, item.id)!.dateChanges).toEqual([]);
  });

  test("typing a vague date over an exact one, with the precision left as it was, takes the precision from the words", async () => {
    const db = tempDb();
    await runSync(db, [game("2027-03-14")], undefined, noArtwork);
    const [item] = listReleases(db, {}).items;

    await updateRelease(db, item.id, { dateText: "Q4 2027" });

    expect(getRelease(db, item.id)).toMatchObject({ dateText: "Q4 2027", datePrecision: "Window", releaseDate: null, effectiveSortDate: "2027-10-01" });
  });

  test("retyping an exact date's words keeps its day", async () => {
    const db = tempDb();
    await runSync(db, [game("2027-03-14")], undefined, noArtwork);
    const [item] = listReleases(db, {}).items;

    await updateRelease(db, item.id, { dateText: "14 March 2027" });

    expect(getRelease(db, item.id)).toMatchObject({ datePrecision: "Exact", releaseDate: "2027-03-14" });
  });

  test("deleting a release deletes its date history", async () => {
    const db = tempDb();
    await runSync(db, [game("2027-03-14")], undefined, noArtwork);
    await runSync(db, [game("2027-06-02")], undefined, noArtwork);
    db.prepare("delete from releases").run();
    expect(db.prepare("select count(*) n from release_date_changes").get()).toEqual({ n: 0 });
  });
});
