import type { NormalizedRelease } from "../../../../shared/types";
import type { CompletedMetadataPatch } from "../completed/completedIgdbMatcher";
import { createCompletedGameStore } from "../completed/completedGameStore";
import type { TrackerDatabase } from "../database/db";
import { createReleaseStore } from "../database/releaseStore";
import { runWrite } from "../database/writeQueue";
import { normalizeText } from "../text/normalizeText";
import { computeSortDateAndEligibility } from "../sync/releasePolicy";

// The sample library a new user can load to try the app without IGDB keys: real games with their public
// IGDB data (covers, artwork, genres, ratings), and made-up personal data (ratings, finish dates, platforms,
// notes). It is written through the normal stores, so it behaves like any library, and the ids it created
// are remembered so "Remove sample data" takes out exactly those rows.

type SampleRelease = Omit<NormalizedRelease, "id" | "normalizedTitle" | "developers" | "sourceConfidence" | "eligible" | "eligibilityReason" | "effectiveSortDate" | "igdbId"> & { igdbId: number };
interface SampleCompletedGame {
  title: string;
  userPlatform: string;
  ratingRaw: string;
  // Finished `yearsAgo` years before the current one, on this month and day.
  yearsAgo: number;
  month: number;
  day: number;
  notes: string | null;
  metadata: CompletedMetadataPatch;
}

const SAMPLE_KEY = "DEMO_LIBRARY";
interface SampleData { releases: SampleRelease[]; completedGames: SampleCompletedGame[] }

// The sample (about 100 KB) loads the first time it is added, not every time the backend starts.
let sampleData: Promise<SampleData> | null = null;
const loadSampleData = () => (sampleData ??= import("./demoLibrary.json").then(module => module.default as unknown as SampleData));

interface LoadedSample {
  releaseIds: string[];
  completedIds: string[];
}

export function isDemoLibraryLoaded(db: TrackerDatabase) {
  return Boolean(db.prepare("select 1 from settings where key = ?").get(SAMPLE_KEY));
}

export function createDemoLibrary(db: TrackerDatabase, today: () => Date) {
  const readLoaded = () => {
    const row = db.prepare("select value from settings where key = ?").get(SAMPLE_KEY) as { value: string } | undefined;
    return row ? (JSON.parse(row.value) as LoadedSample) : null;
  };

  return {
    isLoaded: () => readLoaded() !== null,

    // Resolves to the counts written, or null when the sample is already loaded.
    async load() {
      const { releases, completedGames } = await loadSampleData();
      return runWrite(db, () => {
        if (readLoaded()) return null;
        const now = today();
        const releaseStore = createReleaseStore(db);
        const releaseIds = shiftedReleases(releases, now).map(release => {
          releaseStore.save(release);
          return release.id;
        });
        const completedStore = createCompletedGameStore(db);
        const completedIds = finishedByToday(completedGames, now).map(({ game, completionDate }) => {
          const saved = completedStore.createManual({ title: game.title, userPlatform: game.userPlatform, ratingRaw: game.ratingRaw, completionDate, notes: game.notes });
          completedStore.applyMatch(saved.id, game.metadata.igdbId!, game.metadata);
          return saved.id;
        });
        db.prepare("insert or replace into settings (key, value, updated_at) values (?, ?, current_timestamp)").run(SAMPLE_KEY, JSON.stringify({ releaseIds, completedIds }));
        return { releases: releaseIds.length, completedGames: completedIds.length };
      });
    },

    remove() {
      return runWrite(db, () => {
        const loaded = readLoaded();
        if (!loaded) return;
        const releaseStore = createReleaseStore(db);
        for (const id of loaded.releaseIds) releaseStore.delete(id);
        const completedStore = createCompletedGameStore(db);
        for (const id of loaded.completedIds) completedStore.deleteById(id);
        db.prepare("delete from settings where key = ?").run(SAMPLE_KEY);
      });
    }
  };
}

// The sample's upcoming dates, moved by whole months so its first release lands last month: a new user sees
// a game or two just out and the rest still to come. In January it lands this month instead, because the
// default "from January 1" filter would hide last year's games. A vague date ("Q4 2026", "2027") moves by
// whole years, rounded up, so it stays after the exact dates around it.
function shiftedReleases(releases: SampleRelease[], now: Date): NormalizedRelease[] {
  const first = releases.map(release => release.releaseDate).filter((date): date is string => Boolean(date)).sort()[0];
  const target = Math.max(now.getUTCFullYear() * 12 + now.getUTCMonth() - 1, now.getUTCFullYear() * 12);
  const months = target - (Number(first.slice(0, 4)) * 12 + Number(first.slice(5, 7)) - 1);
  const years = Math.ceil(months / 12);
  const moveYears = (text: string | null) => (text ? text.replace(/\b(20\d{2})\b/g, year => String(Number(year) + years)) : text);
  return releases.map(release => {
    const date = release.datePrecision === "Exact" && release.releaseDate
      ? exactDate(addMonths(release.releaseDate, months))
      : { dateText: moveYears(release.dateText)!, releaseDate: moveYears(release.releaseDate), datePrecision: release.datePrecision, releaseWindow: moveYears(release.releaseWindow) };
    // No IGDB id: a later sync of the same game adds the user's own row instead of taking over the sample's.
    const { igdbId: _igdbId, ...rest } = release;
    return { ...rest, ...date, id: `demo-${release.igdbId}`, normalizedTitle: normalizeText(release.title), developers: [], sourceConfidence: date.releaseDate ? 90 : 60, ...computeSortDateAndEligibility(date) };
  });
}

// "2026-01-31" plus one month is "2026-02-28": the day is kept where the month has it.
function addMonths(iso: string, months: number) {
  const index = Number(iso.slice(0, 4)) * 12 + Number(iso.slice(5, 7)) - 1 + months;
  const year = Math.floor(index / 12);
  const month = index % 12;
  const day = Math.min(Number(iso.slice(8, 10)), new Date(Date.UTC(year, month + 1, 0)).getUTCDate());
  return `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// The sample's own date text style, "Jan 07, 2026".
function exactDate(iso: string) {
  const dateText = `${MONTH_NAMES[Number(iso.slice(5, 7)) - 1]} ${iso.slice(8, 10)}, ${iso.slice(0, 4)}`;
  return { dateText, releaseDate: iso, datePrecision: "Exact" as const, releaseWindow: null };
}

// Last year's finishes all count; this year's only up to today, so "so far" stays true.
function finishedByToday(completedGames: SampleCompletedGame[], now: Date) {
  const todayIso = now.toISOString().slice(0, 10);
  return completedGames
    .map(game => {
      const year = now.getUTCFullYear() - game.yearsAgo;
      return { game, completionDate: `${year}-${String(game.month).padStart(2, "0")}-${String(game.day).padStart(2, "0")}` };
    })
    .filter(({ completionDate }) => completionDate <= todayIso);
}
