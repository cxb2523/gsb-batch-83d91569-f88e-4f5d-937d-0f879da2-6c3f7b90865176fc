const monthYearFormatter = new Intl.DateTimeFormat("en-US", { month: "long", year: "numeric", timeZone: "UTC" });

// "February 2027" for a 1-based month.
export function monthYearLabel(year: number, month: number) {
  return monthYearFormatter.format(new Date(Date.UTC(year, month - 1, 1)));
}
