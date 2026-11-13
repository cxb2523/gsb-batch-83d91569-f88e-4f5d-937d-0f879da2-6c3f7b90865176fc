import type { FlightItem, FlightRecord, PageFetch } from './types.ts';

/** Raised when a payload does not look like the fixture's flights response. */
export class PayloadError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'PayloadError';
  }
}

const str = (v: unknown): string => (typeof v === 'string' ? v.trim() : '');
const num = (v: unknown): number | null => {
  if (typeof v === 'number' && Number.isFinite(v)) return v;
  if (typeof v === 'string' && v.trim() !== '') {
    const n = Number(v.replace(/[\s ]/g, ''));
    return Number.isFinite(n) ? n : null;
  }
  return null;
};

/**
 * Validates a parsed `/api/flights` payload. Items that cannot be normalized are dropped (and reported) rather
 * than poisoning the whole page; a payload that is not an object with an `items` array is a hard failure.
 */
export function parseFlightsPayload(raw: unknown): { items: FlightItem[]; total: number; dropped: number } {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new PayloadError('response is not a JSON object');
  const body = raw as { items?: unknown; total?: unknown };
  if (!Array.isArray(body.items)) throw new PayloadError('response has no "items" array');
  const total = num(body.total);
  if (total === null || total < 0) throw new PayloadError('response has no numeric "total"');
  const items: FlightItem[] = [];
  let dropped = 0;
  for (const entry of body.items) {
    const item = normalizeItem(entry);
    if (item) items.push(item);
    else dropped++;
  }
  return { items, total: Math.floor(total), dropped };
}

/** One API item → FlightItem, or null when a required field is missing/unusable. */
export function normalizeItem(entry: unknown): FlightItem | null {
  if (!entry || typeof entry !== 'object') return null;
  const e = entry as Record<string, unknown>;
  const price = num(e.price);
  const airline = str(e.airline);
  const depart = str(e.depart);
  const arrive = str(e.arrive);
  const stops = num(e.stops);
  if (price === null || price < 0) return null;
  if (!airline || !depart || !arrive) return null;
  if (stops === null || stops < 0) return null;
  return { price, airline, depart, arrive, stops: Math.floor(stops) };
}

/** Parses a response body: JSON text when present, otherwise a structured failure. */
export function parseBody(body: string): unknown {
  try {
    return JSON.parse(body);
  } catch {
    throw new PayloadError('response body is not JSON');
  }
}

export function toRecord(date: string, page: number, item: FlightItem): FlightRecord {
  return {
    date, price: item.price, airline: item.airline, depart: item.depart, arrive: item.arrive,
    stops: item.stops, sourcePage: page,
  };
}

/** Stable ordering: date ascending, then price ascending; ties keep collection order. */
export function sortRecords(records: FlightRecord[]): FlightRecord[] {
  return records
    .map((r, i) => ({ r, i }))
    .sort((a, b) => (a.r.date < b.r.date ? -1 : a.r.date > b.r.date ? 1 : a.r.price - b.r.price || a.i - b.i))
    .map((x) => x.r);
}

/** Convenience for building a success/empty PageFetch from a raw body. */
export function pageFetchFromBody(body: string, httpStatus: number): PageFetch {
  let parsed: { items: FlightItem[]; total: number };
  try {
    parsed = parseFlightsPayload(parseBody(body));
  } catch (e) {
    return { outcome: 'failed', httpStatus, error: e instanceof Error ? e.message : String(e) };
  }
  return {
    outcome: parsed.items.length ? 'success' : 'empty',
    httpStatus,
    items: parsed.items,
    total: parsed.total,
  };
}
