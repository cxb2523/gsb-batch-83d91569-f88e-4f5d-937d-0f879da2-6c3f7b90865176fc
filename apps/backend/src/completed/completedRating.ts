// A rating as typed (add form, detail edit) to a 0..10 score: "9/10" → 9, "95%" → 9.5, "4/5" → 8,
// "85" → 8.5. Every write of `rating_raw` sets `rating_score` from it through here, so the two never disagree.
export function parseRating(value: string | null | undefined) {
  if (!value) return null;
  const trimmed = value.trim();
  const fraction = trimmed.match(/^(\d+(?:\.\d+)?)\s*\/\s*(\d+(?:\.\d+)?)$/);
  if (fraction) return roundToOne((Number(fraction[1]) / Math.max(Number(fraction[2]), 1)) * 10);
  const percent = trimmed.match(/^(\d+(?:\.\d+)?)\s*%$/);
  if (percent) return roundToOne(Number(percent[1]) / 10);
  const number = Number(trimmed);
  if (Number.isFinite(number)) return number <= 10 ? roundToOne(number) : roundToOne(number / 10);
  return null;
}

const roundToOne = (value: number) => Math.round(value * 10) / 10;
