import { randomUUID } from "node:crypto";
import type { TrackerDatabase } from "../database/db";
import type { ActionResult } from "./actionResult";
import { computeSortDateAndEligibility, normalizeIgdbGame } from "../sync/releasePolicy";
import { normalizeText } from "../text/normalizeText";
import type { IgdbGateway } from "../igdb/gateway";
import type { DatePrecision, GameTrailer, IgdbGameLike, ManualReleaseCandidate, ReleaseArtwork, ReleaseCategory } from "../../../../shared/types";
import type { DiagnosticLogger } from "../diagnostics/logger";
import { createReleaseStore, type ReleaseEdit } from "../database/releaseStore";
import { runWrite } from "../database/writeQueue";

interface ManualReleasePayload {
  igdbId?: number;
  title?: string;
  publishers?: string | string[];
  developers?: string | string[];
  platforms?: string | string[];
  category?: ReleaseCategory;
  dateText?: string;
  datePrecision?: DatePrecision;
  releaseDate?: string | null;
  releaseWindow?: string | null;
  sourceUrl?: string;
  artworks?: ReleaseArtwork[];
  screenshots?: ReleaseArtwork[];
  trailers?: GameTrailer[];
}

interface UpdateReleasePayload {
  hidden?: boolean;
  watched?: boolean;
  released?: boolean;
  dateText?: string;
  sourceUrl?: string;
  sourceName?: string;
  title?: string;
  publishers?: string | string[];
  developers?: string | string[];
  platforms?: string | string[];
  category?: ReleaseCategory;
  releaseDate?: string | null;
  datePrecision?: DatePrecision;
  releaseWindow?: string | null;
}

export function createManualRelease(db: TrackerDatabase, payload: ManualReleasePayload): Promise<ActionResult<{ ok: true; item: unknown }>> {
  return runWrite(db, () => createManualReleaseNow(db, payload));
}

function createManualReleaseNow(db: TrackerDatabase, payload: ManualReleasePayload): ActionResult<{ ok: true; item: unknown }> {
  const releaseStore = createReleaseStore(db);
  if (!payload.title?.trim()) return { ok: false, statusCode: 400, error: "Title is required" };
  const igdbId = Number.isFinite(payload.igdbId) ? payload.igdbId : undefined;
  const alreadyTracked = igdbId !== undefined ? releaseStore.findByIgdbId(igdbId) : null;
  if (alreadyTracked) {
    const existing = releaseStore.getDetail(alreadyTracked);
    // Detail reads only cover Upcoming-eligible releases, so a tracked-but-hidden game has no item to show.
    if (!existing) return { ok: false, statusCode: 409, error: "This game is already tracked but hidden from Upcoming because it has no usable upcoming date." };
    return { ok: true, value: { ok: true, item: existing } };
  }
  const dateText = payload.dateText?.trim() || "TBA";
  const releaseDate = payload.releaseDate?.trim() || null;
  const datePrecision = payload.datePrecision || (releaseDate ? "Exact" : "TBA");
  const releaseWindow = payload.releaseWindow?.trim() || (datePrecision === "Window" || datePrecision === "Year" ? dateText : null);
  const baseRelease = {
    id: `manual-${randomUUID()}`,
    title: payload.title.trim(),
    normalizedTitle: normalizeText(payload.title.trim()),
    dateText,
    releaseDate,
    datePrecision,
    releaseWindow,
    sourceConfidence: 70,
    igdbId,
    category: payload.category || "Main",
    publishers: splitList(payload.publishers),
    developers: splitList(payload.developers),
    platforms: splitList(payload.platforms),
    genres: [],
    igdbUrl: payload.sourceUrl?.trim() || undefined,
    artworks: normalizeArtworkList(payload.artworks),
    screenshots: normalizeArtworkList(payload.screenshots).slice(0, 6),
    trailers: normalizeTrailerList(payload.trailers)
  };
  const release = { ...baseRelease, ...computeSortDateAndEligibility(baseRelease) };
  releaseStore.save(release);
  if (payload.sourceUrl?.trim()) {
    releaseStore.addManualSourceUrl(baseRelease.id, payload.sourceUrl.trim());
  }
  return { ok: true, value: { ok: true, item: releaseStore.getDetail(baseRelease.id) ?? release } };
}

export function updateRelease(db: TrackerDatabase, id: string, payload: UpdateReleasePayload): Promise<ActionResult<{ ok: true; item: unknown }>> {
  return runWrite(db, () => updateReleaseNow(db, id, payload));
}

function updateReleaseNow(db: TrackerDatabase, id: string, payload: UpdateReleasePayload): ActionResult<{ ok: true; item: unknown }> {
  const releaseStore = createReleaseStore(db);
  if (!releaseStore.exists(id)) return { ok: false, statusCode: 404, error: "Release not found" };
  const edit: ReleaseEdit = {};
  if (payload.title !== undefined) {
    const trimmed = payload.title.trim();
    if (!trimmed) return { ok: false, statusCode: 400, error: "Title cannot be empty" };
    edit.title = trimmed;
  }
  if (payload.publishers !== undefined) edit.publishers = splitList(payload.publishers);
  if (payload.developers !== undefined) edit.developers = splitList(payload.developers);
  if (payload.platforms !== undefined) edit.platforms = splitList(payload.platforms);
  if (payload.category !== undefined) edit.category = payload.category;
  if (payload.releaseDate !== undefined) edit.releaseDate = payload.releaseDate?.trim() || null;
  if (payload.datePrecision !== undefined) edit.datePrecision = payload.datePrecision;
  if (payload.releaseWindow !== undefined) edit.releaseWindow = payload.releaseWindow?.trim() || null;
  if (payload.dateText !== undefined) edit.dateText = payload.dateText;
  releaseStore.edit(id, edit);
  releaseStore.updateUserState(id, payload);
  if (payload.dateText && payload.sourceUrl && payload.sourceName) {
    releaseStore.applyDateOverride(id, { dateText: payload.dateText, sourceUrl: payload.sourceUrl, sourceName: payload.sourceName });
  }
  return { ok: true, value: { ok: true, item: releaseStore.getDetail(id) } };
}

export function deleteReleaseWithOptionalBlock(db: TrackerDatabase, id: string, block: boolean, logger: Pick<DiagnosticLogger, "log">): Promise<ActionResult<{ ok: true }>> {
  return runWrite(db, () => deleteReleaseNow(db, id, block, logger));
}

function deleteReleaseNow(db: TrackerDatabase, id: string, block: boolean, logger: Pick<DiagnosticLogger, "log">): ActionResult<{ ok: true }> {
  logger.log("release.delete.requested", { id, block });
  const deleted = createReleaseStore(db).delete(id, { block });
  if (!deleted) {
    logger.log("release.delete.not_found", { id, block });
    return { ok: false, statusCode: 404, error: "Release not found" };
  }
  if (deleted.blocked) logger.log("release.delete.blocked", { id, igdbId: deleted.igdbId, normalizedTitle: deleted.normalizedTitle, title: deleted.title });
  logger.log("release.delete.deleted", { id, block, title: deleted.title });
  return { ok: true, value: { ok: true } };
}

function splitList(value: string | string[] | undefined) {
  if (Array.isArray(value)) return value.map(item => item.trim()).filter(Boolean);
  return (value ?? "").split(",").map(item => item.trim()).filter(Boolean);
}

function normalizeArtworkList(value: ReleaseArtwork[] | undefined) {
  if (!Array.isArray(value)) return [];
  const items: ReleaseArtwork[] = [];
  for (const artwork of value) {
    const imageId = String(artwork.imageId ?? "").trim();
    if (imageId) items.push({ imageId, source: artwork.source, url: artwork.url });
  }
  return items;
}

function normalizeTrailerList(value: GameTrailer[] | undefined) {
  if (!Array.isArray(value)) return [];
  const items: GameTrailer[] = [];
  for (const trailer of value) {
    const videoId = String(trailer.videoId ?? "").trim();
    if (videoId && trailer.provider === "youtube") items.push({ videoId, name: trailer.name ?? null, provider: "youtube" });
  }
  return items.slice(0, 1);
}

export async function searchManualReleaseCandidates(igdb: IgdbGateway, title: string): Promise<ActionResult<{ items: ManualReleaseCandidate[] }>> {
  if (!igdb.hasCredentials()) return { ok: false, statusCode: 409, error: "IGDB credentials are required for manual game search" };
  const games = await igdb.searchReleaseCandidates(title);
  return { ok: true, value: { items: games.map(toManualCandidate) } };
}

function toManualCandidate(game: IgdbGameLike): ManualReleaseCandidate {
  const normalized = normalizeIgdbGame(game);
  return {
    igdbId: game.id,
    title: normalized.title,
    publishers: normalized.publishers,
    developers: normalized.developers,
    platforms: normalized.platforms,
    category: normalized.category,
    dateText: normalized.dateText,
    datePrecision: normalized.datePrecision,
    releaseDate: normalized.releaseDate,
    releaseWindow: normalized.releaseWindow,
    sourceUrl: normalized.igdbUrl ?? null,
    coverImageId: game.cover?.image_id ?? null,
    artworks: normalized.artworks,
    screenshots: normalized.screenshots,
    trailers: normalized.trailers
  };
}

export function unblockRelease(db: TrackerDatabase, blockedId: string): Promise<ActionResult<{ ok: true }>> {
  return runWrite(db, () => {
    createReleaseStore(db).unblock(blockedId);
    return { ok: true, value: { ok: true } };
  });
}
