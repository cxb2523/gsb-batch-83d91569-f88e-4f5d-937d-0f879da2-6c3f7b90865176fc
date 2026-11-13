import { useEffect, useRef, useState } from "react";
import type { YearInReviewSettingsPatch, YearInReviewSummary, YearInReviewYear } from "../../../shared/types";
import type { ApiClient } from "./api/client";
import type { AppShell } from "./appShell";

export type YearInReviewWorkflow = ReturnType<typeof useYearInReviewWorkflow>;

// Where you were when you opened a game, so coming back from its detail page lands there again.
export interface YearInReviewPlace {
  year: number;
  chapter: number;
  shelf: string | null;
}

// The year to open: the latest year with finished games (the current year once it has some), else the current year.
export function defaultReviewYear(years: YearInReviewYear[]) {
  return (years.find(entry => entry.count > 0) ?? years.find(entry => entry.inProgress) ?? years[0])?.year ?? null;
}

// Year in Review data: the year list, the selected year's summary, and saving its settings.
// Everything reloads each time the view opens, so edits in the Completed Library show up.
// `themeAutoplay`: whether a year's theme music starts by itself (a preference, off by default).
export function useYearInReviewWorkflow({ api, shell, active, themeAutoplay = false }: { api: ApiClient; shell: Pick<AppShell, "reportOperationError">; active: boolean; themeAutoplay?: boolean }) {
  const [years, setYears] = useState<YearInReviewYear[]>([]);
  const [year, setYear] = useState<number | null>(null);
  const [summary, setSummary] = useState<YearInReviewSummary | null>(null);
  const [status, setStatus] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [place, setPlace] = useState<YearInReviewPlace | null>(null);
  const request = useRef(0);
  // The selected year right now, for saves that resolve after the user picked another year.
  const selectedYear = useRef<number | null>(null);

  const loadSummary = async (next: number) => {
    const ticket = ++request.current;
    selectedYear.current = next;
    setYear(next);
    setStatus("loading");
    try {
      const loaded = await api.getYearInReview(next);
      if (ticket !== request.current) return;
      setSummary(loaded);
      setStatus("ready");
    } catch (error) {
      if (ticket !== request.current) return;
      setStatus("error");
      shell.reportOperationError("load-year-in-review", error);
    }
  };

  useEffect(() => {
    if (!active) return;
    void (async () => {
      try {
        const loaded = (await api.getYearInReviewYears()).years;
        setYears(loaded);
        const keep = year !== null && loaded.some(entry => entry.year === year) ? year : defaultReviewYear(loaded);
        if (keep !== null) await loadSummary(keep);
      } catch (error) {
        setStatus("error");
        shell.reportOperationError("load-year-in-review-years", error);
      }
    })();
  }, [active]);

  // Resolves to an error message for the form, or null once saved.
  const saveSettings = async (patch: YearInReviewSettingsPatch): Promise<string | null> => {
    if (year === null) return "No year selected";
    try {
      const saved = await api.saveYearInReviewSettings(year, patch);
      if (saved.year === selectedYear.current) setSummary(saved);
      return null;
    } catch (error) {
      return error instanceof Error ? error.message : String(error);
    }
  };

  return {
    years,
    year,
    summary: summary && summary.year === year ? summary : null,
    status,
    place,
    themeAutoplay,
    actions: {
      selectYear: (next: number) => void loadSummary(next),
      saveSettings,
      rememberPlace: setPlace,
      forgetPlace: () => setPlace(null)
    }
  };
}
