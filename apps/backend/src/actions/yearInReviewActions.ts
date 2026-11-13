import type { YearInReviewSettingsPatch, YearInReviewSummary, YearInReviewYear } from "../../../../shared/types";
import { parseYoutubeLink } from "../../../../shared/youtubeLink";
import { createCompletedGameStore } from "../completed/completedGameStore";
import type { TrackerDatabase } from "../database/db";
import { runWrite } from "../database/writeQueue";
import { buildYearInReview, listReviewYears } from "../yearInReview/buildYearInReview";
import { createYearInReviewSettingsStore, type YearInReviewSettings } from "../yearInReview/yearInReviewSettingsStore";
import type { ActionResult } from "./actionResult";

const MIN_YEAR = 1970;
const MAX_YEAR = 2100;

// Year in Review reads completed games through the Completed Library store and writes only its own settings.
export function createYearInReviewActions(db: TrackerDatabase, { today }: { today: () => Date }) {
  const completed = createCompletedGameStore(db);
  const settings = createYearInReviewSettingsStore(db);

  const summarize = (year: number): YearInReviewSummary => {
    const rows = completed.yearInReviewRows(year);
    return buildYearInReview({ year, today: today(), ...rows, settings: settings.read(year) });
  };

  return {
    years(): { years: YearInReviewYear[] } {
      return { years: listReviewYears(completed.completionYearCounts(), today()) };
    },

    summary(yearText: string): ActionResult<YearInReviewSummary> {
      const year = parseYear(yearText);
      if (year === null) return badYear;
      return { ok: true, value: summarize(year) };
    },

    async saveSettings(yearText: string, body: unknown): Promise<ActionResult<YearInReviewSummary>> {
      const year = parseYear(yearText);
      if (year === null) return badYear;
      const patch = (body && typeof body === "object" ? body : {}) as YearInReviewSettingsPatch;
      const next: Partial<YearInReviewSettings> = {};

      if (patch.musicLink !== undefined) {
        if (patch.musicLink === null || patch.musicLink === "") next.musicVideoId = null;
        else {
          const videoId = typeof patch.musicLink === "string" ? parseYoutubeLink(patch.musicLink) : null;
          if (!videoId) return { ok: false, statusCode: 400, error: "That isn't a YouTube video link" };
          next.musicVideoId = videoId;
        }
      }
      if (patch.gotyCompletedId !== undefined) {
        if (patch.gotyCompletedId === null) next.gotyCompletedId = null;
        else {
          const game = typeof patch.gotyCompletedId === "string" ? completed.getDetail(patch.gotyCompletedId) : null;
          if (!game || game.completionYear !== year) return { ok: false, statusCode: 400, error: `That game wasn't finished in ${year}` };
          next.gotyCompletedId = game.id;
        }
      }
      await runWrite(db, () => settings.save(year, next));
      return { ok: true, value: summarize(year) };
    }
  };
}

const badYear = { ok: false, statusCode: 400, error: `Year must be between ${MIN_YEAR} and ${MAX_YEAR}` } as const;

function parseYear(text: string) {
  if (!/^\d{4}$/.test(text)) return null;
  const year = Number(text);
  return year >= MIN_YEAR && year <= MAX_YEAR ? year : null;
}
