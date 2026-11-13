import { afterEach, describe, expect, test } from "vitest";
import { randomBytes } from "node:crypto";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { openDatabase, type TrackerDatabase } from "../../apps/backend/src/database/db";
import { runMigrations } from "../../apps/backend/src/database/migrations";
import { createSecretCipher } from "../../apps/backend/src/settings/secretCipher";
import { createSettingsStore } from "../../apps/backend/src/settings/settingsStore";

let cleanups: Array<() => void> = [];
afterEach(() => {
  for (const cleanup of cleanups) cleanup();
  cleanups = [];
});

function tempDb(): TrackerDatabase {
  const dir = mkdtempSync(join(tmpdir(), "grt-cipher-"));
  const db = openDatabase(join(dir, "tracker.db"));
  runMigrations(db);
  cleanups.push(() => {
    db.close();
    rmSync(dir, { recursive: true, force: true });
  });
  return db;
}

const rawValue = (db: TrackerDatabase, key: string) =>
  (db.prepare("select value from settings where key = ?").get(key) as { value: string } | undefined)?.value;

describe("credential encryption at rest", () => {
  test("credentials are stored encrypted and read back as entered", () => {
    const db = tempDb();
    const cipher = createSecretCipher(randomBytes(32).toString("hex"));
    const store = createSettingsStore(db, {}, cipher);

    store.saveCredentials({ IGDB_CLIENT_ID: "client-id", IGDB_CLIENT_SECRET: "super-secret", STEAMGRIDDB_API_KEY: "sgdb-key" });

    expect(rawValue(db, "IGDB_CLIENT_SECRET")).toMatch(/^enc:v1:/);
    expect(rawValue(db, "IGDB_CLIENT_SECRET")).not.toContain("super-secret");
    expect(rawValue(db, "STEAMGRIDDB_API_KEY")).not.toContain("sgdb-key");
    expect(store.igdbTokenConfig()).toMatchObject({ clientId: "client-id", clientSecret: "super-secret" });
    expect(store.steamGridDbApiKey()).toBe("sgdb-key");
  });

  test("keys saved in plain text by older versions are encrypted in place", () => {
    const db = tempDb();
    createSettingsStore(db, {}).saveCredentials({ IGDB_CLIENT_SECRET: "legacy-secret" });
    expect(rawValue(db, "IGDB_CLIENT_SECRET")).toBe("legacy-secret");

    const store = createSettingsStore(db, {}, createSecretCipher(randomBytes(32).toString("hex")));
    expect(store.encryptStoredCredentials()).toBe(1);

    expect(rawValue(db, "IGDB_CLIENT_SECRET")).toMatch(/^enc:v1:/);
    expect(store.igdbTokenConfig().clientSecret).toBe("legacy-secret");
  });

  test("a value that cannot be decrypted (key lost) counts as not saved, flagged unreadable, instead of leaking ciphertext", () => {
    const db = tempDb();
    createSettingsStore(db, {}, createSecretCipher(randomBytes(32).toString("hex"))).saveCredentials({ STEAMGRIDDB_API_KEY: "sgdb-key" });

    const withOtherKey = createSettingsStore(db, {}, createSecretCipher(randomBytes(32).toString("hex")));

    expect(withOtherKey.steamGridDbApiKey()).toBeUndefined();
    expect(withOtherKey.savedCredentials().STEAMGRIDDB_API_KEY).toEqual({ saved: false, unreadable: true });
  });

  test("a tampered ciphertext is refused", () => {
    const cipher = createSecretCipher(randomBytes(32).toString("hex"));
    const sealed = cipher.encrypt("value");
    // Change a character in the middle of the payload, never to itself and never in base64 padding bits.
    const at = Math.floor((sealed.indexOf(":", 4) + sealed.length) / 2);
    const tampered = sealed.slice(0, at) + (sealed[at] === "A" ? "B" : "A") + sealed.slice(at + 1);
    expect(tampered).not.toBe(sealed);

    expect(cipher.decrypt(tampered)).toBeUndefined();
  });
});
