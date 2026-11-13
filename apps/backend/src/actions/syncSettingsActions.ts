import { SUGGESTED_PUBLISHERS } from "../../../../shared/constants";
import type { SyncSettings, TrackedPublisher } from "../../../../shared/types";
import type { TrackerDatabase } from "../database/db";
import { runWrite } from "../database/writeQueue";
import type { IgdbGateway } from "../igdb/gateway";
import { findCompanyByName, searchCompanies } from "../sync/igdbCandidateSource";
import { createSyncSettingsStore, parseSyncSettingsPatch } from "../sync/syncSettingsStore";
import type { ActionResult } from "./actionResult";

const missingCredentials: ActionResult<never> = { ok: false, statusCode: 409, error: "Add your IGDB keys in Settings → API keys to search publishers" };

export function readSyncSettings(db: TrackerDatabase): SyncSettings {
  return createSyncSettingsStore(db).read();
}

export async function updateSyncSettings(db: TrackerDatabase, body: unknown): Promise<ActionResult<SyncSettings>> {
  const parsed = parseSyncSettingsPatch(body);
  if (!parsed.ok) return { ok: false, statusCode: 400, error: parsed.error };
  const store = createSyncSettingsStore(db);
  await runWrite(db, () => store.update(parsed.patch));
  return { ok: true, value: store.read() };
}

export async function searchPublishers(igdb: IgdbGateway, text: unknown): Promise<ActionResult<{ items: TrackedPublisher[] }>> {
  const query = typeof text === "string" ? text.trim() : "";
  if (query.length < 2) return { ok: false, statusCode: 400, error: "Type at least two letters" };
  if (!igdb.hasCredentials()) return missingCredentials;
  return { ok: true, value: { items: await searchCompanies(igdb, query) } };
}

export async function trackPublisher(db: TrackerDatabase, body: unknown): Promise<ActionResult<SyncSettings>> {
  const { id, name } = (body ?? {}) as { id?: unknown; name?: unknown };
  if (!Number.isInteger(id) || (id as number) <= 0 || typeof name !== "string" || !name.trim()) {
    return { ok: false, statusCode: 400, error: "A publisher needs an IGDB company id and a name" };
  }
  const store = createSyncSettingsStore(db);
  await runWrite(db, () => store.addPublishers([{ id: id as number, name: name.trim() }]));
  return { ok: true, value: store.read() };
}

// Adds the suggested publishers IGDB knows by exact name; names it can't find are reported, not guessed.
export async function trackSuggestedPublishers(db: TrackerDatabase, igdb: IgdbGateway): Promise<ActionResult<SyncSettings & { notFound: string[] }>> {
  if (!igdb.hasCredentials()) return missingCredentials;
  const found: TrackedPublisher[] = [];
  const notFound: string[] = [];
  for (const name of SUGGESTED_PUBLISHERS) {
    const company = await findCompanyByName(igdb, name);
    if (company) found.push(company);
    else notFound.push(name);
  }
  const store = createSyncSettingsStore(db);
  await runWrite(db, () => store.addPublishers(found));
  return { ok: true, value: { ...store.read(), notFound } };
}

export async function untrackPublisher(db: TrackerDatabase, id: string): Promise<ActionResult<SyncSettings>> {
  const store = createSyncSettingsStore(db);
  const removed = await runWrite(db, () => store.removePublisher(Number(id)));
  if (!removed) return { ok: false, statusCode: 404, error: "That publisher is not tracked" };
  return { ok: true, value: store.read() };
}
