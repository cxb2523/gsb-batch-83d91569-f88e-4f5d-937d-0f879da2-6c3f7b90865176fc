import type { TrackerDatabase } from "../database/db";
import type { ActionResult } from "./actionResult";
import { createCompletedGameStore } from "../completed/completedGameStore";
import type { ManualCompletedGamePayload } from "../completed/completedPersonalFields";
import { createCompletedMatcher, type CompletedMatchLookup } from "../completed/completedIgdbMatcher";
import type { IgdbGateway } from "../igdb/gateway";
import { runWrite } from "../database/writeQueue";

// A failed IGDB lookup as the caller sees it.
function lookupFailure(lookup: Extract<CompletedMatchLookup<unknown>, { ok: false }>): ActionResult<never> {
  return lookup.reason === "no-credentials"
    ? { ok: false, statusCode: 409, error: "IGDB credentials are required to match completed games" }
    : { ok: false, statusCode: 404, error: "IGDB game not found" };
}

// IGDB failures are not the caller's fault, so they surface as server errors rather than 400s.
export async function createManualCompletedGame(db: TrackerDatabase, igdb: IgdbGateway, payload: ManualCompletedGamePayload): Promise<ActionResult<{ ok: true; item: unknown }>> {
  const store = createCompletedGameStore(db);
  if (!payload.title?.trim()) return { ok: false, statusCode: 400, error: "Title is required" };
  const igdbId = typeof payload.igdbId === "number" && Number.isFinite(payload.igdbId) ? payload.igdbId : null;
  const metadata = igdbId === null ? null : await createCompletedMatcher(igdb).metadataFor(igdbId);
  if (metadata && !metadata.ok) return lookupFailure(metadata);
  const item = await runWrite(db, () => {
    const saved = store.createManual(payload);
    if (igdbId === null || !metadata) return saved;
    store.applyMatch(saved.id, igdbId, metadata.value);
    return store.getDetail(saved.id) ?? saved;
  });
  return { ok: true, value: { ok: true, item } };
}

export async function searchManualCompletedCandidates(igdb: IgdbGateway, input: { title?: string; userPlatform?: string; completionYear?: number | null }): Promise<ActionResult<{ items: unknown }>> {
  const title = input.title?.trim();
  if (!title) return { ok: false, statusCode: 400, error: "Title is required for IGDB search" };
  const ranked = await createCompletedMatcher(igdb).candidates({ title, userPlatform: input.userPlatform?.trim() ?? "", completionYear: input.completionYear ?? null });
  return ranked.ok ? { ok: true, value: { items: ranked.value } } : lookupFailure(ranked);
}

export function updateCompletedGame(db: TrackerDatabase, id: string, body: Record<string, unknown> | undefined): Promise<ActionResult<{ ok: true; item: unknown }>> {
  return runWrite(db, () => updateCompletedGameNow(db, id, body));
}

function updateCompletedGameNow(db: TrackerDatabase, id: string, body: Record<string, unknown> | undefined): ActionResult<{ ok: true; item: unknown }> {
  const store = createCompletedGameStore(db);
  if (!body) return { ok: false, statusCode: 400, error: "Body is required" };
  const result = store.edit(id, body);
  if (!result.ok && result.reason === "conflict") return { ok: false, statusCode: 409, error: "Another completed game already has this title and platform" };
  if (!result.ok) return { ok: false, statusCode: 404, error: "Completed game not found" };
  return { ok: true, value: { ok: true, item: store.getDetail(id) } };
}

export function deleteCompletedGame(db: TrackerDatabase, id: string): Promise<ActionResult<{ ok: true }>> {
  return runWrite(db, () => deleteCompletedGameNow(db, id));
}

function deleteCompletedGameNow(db: TrackerDatabase, id: string): ActionResult<{ ok: true }> {
  const store = createCompletedGameStore(db);
  const deleted = store.deleteById(id);
  if (!deleted) return { ok: false, statusCode: 404, error: "Completed game not found" };
  return { ok: true, value: { ok: true } };
}

export async function getMatchCandidates(db: TrackerDatabase, igdb: IgdbGateway, id: string): Promise<ActionResult<{ items: unknown }>> {
  const store = createCompletedGameStore(db);
  const item = store.getDetail(id);
  if (!item) return { ok: false, statusCode: 404, error: "Completed game not found" };
  const ranked = await createCompletedMatcher(igdb).candidates(item);
  return ranked.ok ? { ok: true, value: { items: ranked.value } } : lookupFailure(ranked);
}

export async function matchCompletedGame(db: TrackerDatabase, igdb: IgdbGateway, id: string, igdbId: number): Promise<ActionResult<{ ok: true; item: unknown }>> {
  const store = createCompletedGameStore(db);
  if (!Number.isFinite(igdbId)) return { ok: false, statusCode: 400, error: "igdbId is required" };
  const item = store.getDetail(id);
  if (!item) return { ok: false, statusCode: 404, error: "Completed game not found" };
  const metadata = await createCompletedMatcher(igdb).metadataFor(igdbId);
  if (!metadata.ok) return lookupFailure(metadata);
  await runWrite(db, () => store.applyMatch(id, igdbId, metadata.value));
  return { ok: true, value: { ok: true, item: store.getDetail(id) } };
}
