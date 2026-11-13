import type { CompletedDatePrecision } from "../../../../shared/types";

export interface CompletedDateParts {
  completionDate: string | null;
  completionMonth: string | null;
  completionYear: number | null;
  completionPrecision: CompletedDatePrecision;
}

export function parseCompletionDate(value: unknown): CompletedDateParts {
  if (value instanceof Date && !Number.isNaN(value.getTime())) {
    return exactParts(value.getUTCFullYear(), value.getUTCMonth() + 1, value.getUTCDate());
  }
  const text = String(value ?? "").trim();
  if (!text) return emptyParts();

  const isoExact = text.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (isoExact) return exactParts(Number(isoExact[1]), Number(isoExact[2]), Number(isoExact[3]));

  const dayFirstExact = text.match(/^(\d{1,2})[ ./-](\d{1,2})[ ./-](\d{4})$/);
  if (dayFirstExact) return exactParts(Number(dayFirstExact[3]), Number(dayFirstExact[2]), Number(dayFirstExact[1]));

  const numericMonth = text.match(/^(\d{4})-(\d{1,2})$/);
  if (numericMonth) return monthParts(Number(numericMonth[1]), Number(numericMonth[2]));

  const monthYear = text.match(/^(jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|aug|august|sep|sept|september|oct|october|nov|november|dec|december)\s+(\d{4})$/i);
  if (monthYear) return monthParts(Number(monthYear[2]), monthNumber(monthYear[1]));

  if (/^\d{4}$/.test(text)) return { completionDate: null, completionMonth: null, completionYear: Number(text), completionPrecision: "year" };

  const exact = new Date(text);
  if (!Number.isNaN(exact.getTime())) {
    return exactParts(exact.getUTCFullYear(), exact.getUTCMonth() + 1, exact.getUTCDate());
  }
  return emptyParts();
}

function exactParts(year: number, month: number, day: number): CompletedDateParts {
  if (!isValidDate(year, month, day)) return emptyParts();
  const completionDate = `${year}-${pad2(month)}-${pad2(day)}`;
  return {
    completionDate,
    completionMonth: `${year}-${pad2(month)}`,
    completionYear: year,
    completionPrecision: "exact"
  };
}

function monthParts(year: number, month: number): CompletedDateParts {
  if (!Number.isInteger(year) || year < 1000 || year > 9999 || !Number.isInteger(month) || month < 1 || month > 12) {
    return emptyParts();
  }
  return {
    completionDate: null,
    completionMonth: `${year}-${pad2(month)}`,
    completionYear: year,
    completionPrecision: "month"
  };
}

function isValidDate(year: number, month: number, day: number) {
  if (!Number.isInteger(year) || !Number.isInteger(month) || !Number.isInteger(day)) return false;
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day;
}

function emptyParts(): CompletedDateParts {
  return { completionDate: null, completionMonth: null, completionYear: null, completionPrecision: "none" };
}

function pad2(value: number) {
  return String(value).padStart(2, "0");
}

function monthNumber(value: string) {
  const month = value.slice(0, 3).toLowerCase();
  return ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"].indexOf(month) + 1;
}
