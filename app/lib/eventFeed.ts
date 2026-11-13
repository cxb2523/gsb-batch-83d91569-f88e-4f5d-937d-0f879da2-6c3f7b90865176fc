import { api, ApiError } from "./api";

export type SentinelEvent = {
  id: string;
  ledger: number;
  created_at: string;
  agent: string;
  subject: string;
  score: number;
  contract_id: string;
  transaction_hash?: string;
  tx_hash?: string;
};

export type EventPage = {
  events: SentinelEvent[];
  next_cursor: string | null;
  source?: { rpc_url: string; network: string };
};

export type EventFeedState = {
  events: SentinelEvent[];
  cursor: string | null;
  loading: boolean;
  error: string;
  /** Cursor of the request that most recently failed. Undefined for a refresh failure or when no failure is recorded. */
  failedCursor: string | undefined;
  retryAppend: boolean;
  network: string;
};

export const initialEventFeedState: EventFeedState = {
  events: [],
  cursor: null,
  loading: true,
  error: "",
  failedCursor: undefined,
  retryAppend: false,
  network: "",
};

type EventFeedAction =
  | { type: "load-start"; next: string | undefined; append: boolean }
  | { type: "load-success"; page: EventPage; append: boolean }
  | { type: "load-failure"; message: string; next: string | undefined; append: boolean };

export function eventFeedReducer(state: EventFeedState, action: EventFeedAction): EventFeedState {
  switch (action.type) {
    case "load-start":
      return { ...state, loading: true, error: "", failedCursor: undefined, retryAppend: false };
    case "load-success":
      return {
        ...state,
        loading: false,
        error: "",
        failedCursor: undefined,
        retryAppend: false,
        events: action.append ? [...state.events, ...action.page.events] : action.page.events,
        cursor: action.page.next_cursor,
        network: action.page.source?.network || state.network,
      };
    case "load-failure":
      // Already displayed events are intentionally preserved, including after a failed append.
      return {
        ...state,
        loading: false,
        error: action.message,
        failedCursor: action.next,
        retryAppend: action.append,
      };
    default:
      return state;
  }
}

type ErrorWithStatus = { status?: unknown };

function errorStatus(error: unknown): number | null {
  return typeof (error as ErrorWithStatus)?.status === "number" ? (error as ErrorWithStatus).status as number : null;
}

export type EventRequestOutcome = { ok: boolean; httpStatus: number | null };

/**
 * Runs one /events request through the reducer. A failed append leaves the
 * previously loaded events untouched and stores the original cursor so a
 * retry reuses it.
 */
export async function fetchEventPage(
  dispatch: (action: EventFeedAction) => void,
  next?: string,
  append = false,
): Promise<EventRequestOutcome> {
  dispatch({ type: "load-start", next, append });
  try {
    const query = new URLSearchParams({ limit: "20" });
    if (next) query.set("cursor", next);
    const page = await api<EventPage>(`/events?${query.toString()}`);
    dispatch({ type: "load-success", page, append });
    return { ok: true, httpStatus: null };
  } catch (error) {
    dispatch({
      type: "load-failure",
      message: error instanceof Error ? error.message : "Could not load event feed.",
      next,
      append,
    });
    // An HTTP status means the API replied (online); a network failure has no status.
    return { ok: false, httpStatus: errorStatus(error) };
  }
}

export function filterEvents(events: SentinelEvent[], searchTerm: string): SentinelEvent[] {
  const normalized = searchTerm.trim().toLowerCase();
  if (!normalized) return events;
  return events.filter((item) =>
    `${item.subject} ${item.agent} ${item.contract_id} ${item.transaction_hash ?? item.tx_hash ?? ""}`
      .toLowerCase()
      .includes(normalized),
  );
}

export type EventCsvMetadata = {
  exportedAt: string;
  filterTerm: string;
  loadedCount: number;
  matchedCount: number;
  hasOlderPages: boolean;
  lastError: string;
  lastErrorCursor: string;
};

export function buildEventCsvMetadata(input: {
  exportedAt: string;
  filterTerm: string;
  loadedCount: number;
  matchedCount: number;
  hasOlderPages: boolean;
  lastError: string;
  lastErrorCursor: string | undefined;
}): EventCsvMetadata {
  return {
    exportedAt: input.exportedAt,
    filterTerm: input.filterTerm,
    loadedCount: input.loadedCount,
    matchedCount: input.matchedCount,
    hasOlderPages: input.hasOlderPages,
    lastError: input.lastError,
    lastErrorCursor: input.lastErrorCursor ?? "",
  };
}

const CSV_HEADER = ["event_id", "ledger", "created_at", "agent", "account", "score", "contract_id"];

/** Prefixes a leading formula trigger (after optional whitespace) with an apostrophe, per the existing export guard. */
function escapeCsvCell(value: string | number): string {
  const text = String(value ?? "");
  const safeText = typeof value === "string" && /^[\t\r ]*[=+@-]/.test(text) ? `'${text}` : text;
  return `"${safeText.replaceAll('"', '""')}"`;
}

/**
 * Builds the export payload: original event rows followed by a clearly marked
 * metadata section describing which filter/page position the file represents.
 */
export function buildEventsCsv(events: SentinelEvent[], metadata: EventCsvMetadata): string {
  const eventRows = [
    CSV_HEADER,
    ...events.map((event) => [event.id, event.ledger, event.created_at, event.agent, event.subject, event.score, event.contract_id]),
  ];
  const metadataRows: string[][] = [
    ["# export metadata"],
    ["metadata_key", "metadata_value"],
    ["exported_at", metadata.exportedAt],
    ["filter_term", metadata.filterTerm],
    ["loaded_event_count", String(metadata.loadedCount)],
    ["matched_event_count", String(metadata.matchedCount)],
    ["has_older_pages", metadata.hasOlderPages ? "true" : "false"],
    ["last_error", metadata.lastError],
    ["last_error_cursor", metadata.lastErrorCursor],
  ];
  return [...eventRows, ...metadataRows]
    .map((row) => row.map((value) => escapeCsvCell(value)).join(","))
    .join("\r\n");
}

/** Downloads the filtered events as a UTF-8 BOM CSV with embedded export metadata. */
export function downloadEventsCsv(events: SentinelEvent[], metadata: EventCsvMetadata): void {
  const csv = buildEventsCsv(events, metadata);
  const url = URL.createObjectURL(new Blob([`\uFEFF${csv}`], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `stellar-sentinel-events-${new Date().toISOString().slice(0, 10)}.csv`;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

export { ApiError };
