/** ISO-date helpers for expanding a collection range (UTC arithmetic, no DST surprises). */

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

export function isValidIsoDate(value: string): boolean {
  if (!ISO_DATE.test(value)) return false;
  const t = Date.parse(`${value}T00:00:00Z`);
  return Number.isFinite(t) && new Date(t).toISOString().slice(0, 10) === value;
}

function utc(iso: string): number {
  return Date.parse(`${iso}T00:00:00Z`);
}

export function addDays(iso: string, days: number): string {
  return new Date(utc(iso) + days * 86_400_000).toISOString().slice(0, 10);
}

/** Inclusive expansion: `expandDateRange('2026-10-14', '2026-10-16')` → 14, 15, 16. */
export function expandDateRange(from: string, to: string): string[] {
  if (!isValidIsoDate(from)) throw new Error(`invalid dateFrom "${from}" (expected YYYY-MM-DD)`);
  if (!isValidIsoDate(to)) throw new Error(`invalid dateTo "${to}" (expected YYYY-MM-DD)`);
  if (from > to) throw new Error(`dateFrom ${from} is after dateTo ${to}`);
  const out: string[] = [];
  for (let d = from; d <= to; d = addDays(d, 1)) {
    out.push(d);
    if (out.length > 3660) throw new Error('date range is longer than 10 years');
  }
  return out;
}

/** First day of the month an ISO date falls in. */
export function monthStart(iso: string): string {
  return `${iso.slice(0, 7)}-01`;
}

/** Shifts a `YYYY-MM` month key by `delta` months. */
export function shiftMonth(month: string, delta: number): string {
  const [y, m] = month.split('-').map(Number);
  const d = new Date(Date.UTC(y, m - 1 + delta, 1));
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`;
}
