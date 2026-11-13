import type { CompletedDatePrecision } from "../../../../shared/types";
import { parseCompletionDate, type CompletedDateParts } from "./completedDate";
import { parseRating } from "./completedRating";

export interface ManualCompletedGamePayload {
  igdbId?: number | null;
  title?: string;
  userPlatform?: string;
  ratingRaw?: string | null;
  completionDate?: string | null;
  completionMonth?: string | null;
  completionYear?: number | null;
  completionPrecision?: CompletedDatePrecision;
  notes?: string | null;
}

// Most precise first: when several completion fields arrive together, the first filled one wins.
const completionFields = ["completionDate", "completionMonth", "completionYear"] as const;

export function normalizeCompletedPersonalPatch(patch: Record<string, unknown>) {
  const normalizedPatch = { ...patch };
  // The score always follows the rating text, so cards, charts and filters see an edited rating.
  delete normalizedPatch.ratingScore;
  if (hasOwn(normalizedPatch, "ratingRaw")) normalizedPatch.ratingScore = parseRating(normalizedPatch.ratingRaw as string | null);
  if (completionFields.some(field => hasOwn(normalizedPatch, field))) {
    // All sent fields empty clears the completion date.
    Object.assign(normalizedPatch, parseCompletionDate(firstFilledCompletion(normalizedPatch) ?? null));
  }
  return normalizedPatch;
}

// The completion date parts for a manually added game: the most precise field the user filled in wins.
export function normalizeManualCompletion(payload: ManualCompletedGamePayload): CompletedDateParts {
  const filled = firstFilledCompletion(payload);
  if (filled !== undefined) return parseCompletionDate(filled);
  return {
    completionDate: null,
    completionMonth: null,
    completionYear: null,
    completionPrecision: payload.completionPrecision ?? "none"
  };
}

function firstFilledCompletion(fields: Partial<Record<(typeof completionFields)[number], unknown>>) {
  return completionFields.map(field => fields[field]).find(value => value !== undefined && value !== null && String(value).trim() !== "");
}

function hasOwn(value: object, key: string) {
  return Object.prototype.hasOwnProperty.call(value, key);
}
