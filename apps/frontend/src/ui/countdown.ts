import type { ReleaseListItem } from "../../../../shared/types";

const weekdayFormatter = new Intl.DateTimeFormat("en-US", { weekday: "short", timeZone: "UTC" });

function parseDay(value: string): Date | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!match) return null;
  const day = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  return day.getFullYear() === Number(match[1]) && day.getMonth() === Number(match[2]) - 1 && day.getDate() === Number(match[3]) ? day : null;
}

export function daysUntil(releaseDate: string, today: Date): number {
  const target = parseDay(releaseDate);
  if (!target) return Number.NaN;
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  return Math.round((target.getTime() - start.getTime()) / 86_400_000);
}

function exactDays(item: ReleaseListItem, today: Date): number | null {
  if (item.datePrecision !== "Exact" || !item.releaseDate) return null;
  const value = daysUntil(item.releaseDate, today);
  return Number.isNaN(value) ? null : value;
}

export function rowWhenLabel(item: ReleaseListItem, today: Date): string {
  const days = exactDays(item, today);
  if (days === null) return item.dateText;
  if (days < 0) return "released";
  if (days === 0) return "today";
  if (days === 1) return "tomorrow";
  return `${days} days`;
}

export function rowSubLine(item: ReleaseListItem): string {
  if (item.datePrecision !== "Exact" || !item.releaseDate) return item.category;
  const date = new Date(`${item.releaseDate.slice(0, 10)}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return item.category;
  const weekday = weekdayFormatter.format(date);
  return `${weekday} ${date.getUTCDate()}`;
}

export function bannerLabel(item: ReleaseListItem, today: Date): string {
  const days = exactDays(item, today);
  if (days === null) return `Arrives ${item.dateText}`;
  if (days < 0) return "Released";
  if (days === 0) return "Out today";
  if (days === 1) return "Arrives tomorrow";
  return `Arrives in ${days} days`;
}

export function stripCurrentYear(heading: string, today: Date): string {
  return heading.replace(new RegExp(` ${today.getFullYear()}$`), "");
}
