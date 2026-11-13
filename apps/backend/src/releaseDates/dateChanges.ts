import type { DateChangeKind, DatePrecision, ReleaseDateChange } from "../../../../shared/types";
import type { TrackerDatabase } from "../database/db";

// A release's date as stored: its words, its day (if known), how exact it is and the date it sorts by
// (the end of a vague period, per ADR 0005).
export interface DateSnapshot {
  dateText: string;
  releaseDate: string | null;
  datePrecision: DatePrecision;
  sortDate: string | null;
}

const PRECISION_RANK: Record<DatePrecision, number> = { TBA: 0, Year: 1, Window: 2, Month: 3, Exact: 4 };

// What a date change means for the person waiting for the game, or null when nothing a reader would call
// a change happened (the same date reworded). Dates are compared as the periods they name ("2027" is all
// of 2027), because a vague date's sort date is the start of its period when typed or given as words,
// and the end when IGDB sends a timestamp. Ending later is a delay, starting earlier moved the game up,
// and a sharper date inside the old period is the date being announced.
export function classifyDateChange(before: DateSnapshot, after: DateSnapshot): DateChangeKind | null {
  if (before.dateText === after.dateText && before.releaseDate === after.releaseDate) return null;
  const was = periodOf(before);
  const now = periodOf(after);
  if (!was) return now ? "announced" : null;
  if (!now) return "delayed";
  const sharper = PRECISION_RANK[after.datePrecision] > PRECISION_RANK[before.datePrecision];
  if (sharper && within(now, was)) return "announced";
  // One period inside the other with no sharper date: the same date in other words, or a less exact one.
  if (within(now, was) || within(was, now)) return null;
  if (now.end > was.end) return "delayed";
  if (now.start < was.start) return "earlier";
  return null;
}

const within = (inner: Period, outer: Period) => inner.start >= outer.start && inner.end <= outer.end;

interface Period { start: string; end: string }

// The first and last day a date could mean, or null for TBA.
export function periodOf({ dateText, releaseDate, datePrecision, sortDate }: DateSnapshot): Period | null {
  const day = releaseDate ?? sortDate;
  if (datePrecision === "TBA" || !day) return null;
  const year = Number(dateText.match(/\b(20\d{2})\b/)?.[1] ?? day.slice(0, 4));
  if (datePrecision === "Exact") return { start: day, end: day };
  if (datePrecision === "Month") return monthsOf(year, Number(day.slice(5, 7)), Number(day.slice(5, 7)));
  if (datePrecision === "Window") {
    const [first, last] = windowMonths(dateText);
    return monthsOf(year, first, last);
  }
  return monthsOf(year, 1, 12);
}

// The months a window phrase names; a phrase it can't read counts as the whole year.
function windowMonths(text: string): [number, number] {
  const words = text.toLowerCase();
  if (/\bq1\b|first quarter|winter|early/.test(words)) return [1, 3];
  if (/\bq2\b|second quarter|spring/.test(words)) return [4, 6];
  if (/\bq3\b|third quarter|summer/.test(words)) return [7, 9];
  if (/\bq4\b|fourth quarter|fall|autumn|late|holiday/.test(words)) return [10, 12];
  if (/\bh1\b/.test(words)) return [1, 6];
  if (/\bh2\b/.test(words)) return [7, 12];
  if (/\bmid\b/.test(words)) return [4, 9];
  return [1, 12];
}

function monthsOf(year: number, first: number, last: number): Period {
  const lastDay = new Date(Date.UTC(year, last, 0)).getUTCDate();
  const pad = (value: number) => String(value).padStart(2, "0");
  return { start: `${year}-${pad(first)}-01`, end: `${year}-${pad(last)}-${pad(lastDay)}` };
}

export function readDateSnapshot(db: TrackerDatabase, releaseId: string): DateSnapshot | null {
  const row = db.prepare(`
    select date_text dateText, release_date releaseDate, date_precision datePrecision, effective_sort_date sortDate
    from releases where id = ?
  `).get(releaseId) as DateSnapshot | undefined;
  return row ?? null;
}

// Records the change between two snapshots, if it is one. Returns the kind recorded.
export function recordDateChange(db: TrackerDatabase, releaseId: string, before: DateSnapshot, after: DateSnapshot, syncRunId: number | null): DateChangeKind | null {
  const kind = classifyDateChange(before, after);
  if (!kind) return null;
  db.prepare(`
    insert into release_date_changes (release_id, kind, from_text, to_text, from_sort_date, to_sort_date, sync_run_id)
    values (?, ?, ?, ?, ?, ?, ?)
  `).run(releaseId, kind, before.dateText, after.dateText, before.sortDate, after.sortDate, syncRunId);
  return kind;
}

const changeColumns = "kind, from_text fromText, to_text toText, changed_at changedAt";

// Every recorded change for one release, newest first (its detail page).
export function listDateChanges(db: TrackerDatabase, releaseId: string): ReleaseDateChange[] {
  return db.prepare(`select ${changeColumns} from release_date_changes where release_id = ? order by id desc`).all(releaseId) as ReleaseDateChange[];
}

// The newest delay or move up of each listed release, in one query (the list's "Delayed from" badge).
// A date announced later doesn't replace it: "2027" delayed to "2028" is still a delay once the day is known.
export function latestDateChanges(db: TrackerDatabase, idsJson: string): Map<string, ReleaseDateChange> {
  const rows = db.prepare(`
    select release_id releaseId, ${changeColumns} from release_date_changes
    where id in (
      select max(id) from release_date_changes
      where release_id in (select value from json_each(?)) and kind != 'announced'
      group by release_id
    )
  `).all(idsJson) as Array<ReleaseDateChange & { releaseId: string }>;
  return new Map(rows.map(({ releaseId, ...change }) => [releaseId, change]));
}
