export function formatCompletedDateLabel(date?: string | null, month?: string | null, year?: number | null) {
  if (date) {
    const exact = date.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (exact) return `${exact[3]} ${exact[2]} ${exact[1]}`;
    return date;
  }
  if (month) {
    const partial = month.match(/^(\d{4})-(\d{2})$/);
    if (partial) return `${partial[2]} ${partial[1]}`;
    return month;
  }
  if (year) return String(year);
  return "Completion date missing";
}
