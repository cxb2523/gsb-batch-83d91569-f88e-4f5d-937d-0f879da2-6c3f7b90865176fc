import { afterEach, describe, expect, test } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { openDatabase } from "../../apps/backend/src/database/db";
import { runMigrations } from "../../apps/backend/src/database/migrations";
import {
  clearSettingsCredentials,
  readSettingsStatus,
  testSettingsCredentials,
  updateSettingsCredentials
} from "../../apps/backend/src/settings/settingsCredentialModule";
import { createSettingsStore } from "../../apps/backend/src/settings/settingsStore";

let dirs: string[] = [];
let dbs: Array<{ close(): void }> = [];

afterEach(() => {
  for (const db of dbs) db.close();
  dbs = [];
  for (const dir of dirs) rmSync(dir, { recursive: true, force: true });
  dirs = [];
});

describe("settings credential module", () => {
  test("stores credential presence without exposing credential values", async () => {
    const db = setupDb();

    await updateSettingsCredentials(db, {
      IGDB_CLIENT_ID: "client",
      IGDB_ACCESS_TOKEN: "token",
      STEAMGRIDDB_API_KEY: "sgdb-secret"
    });

    const status = readSettingsStatus(db);
    expect(status).toMatchObject({
      credentialStatus: { status: "ready" },
      credentials: {
        IGDB_CLIENT_ID: { saved: true },
        IGDB_CLIENT_SECRET: { saved: false },
        IGDB_ACCESS_TOKEN: { saved: true },
        STEAMGRIDDB_API_KEY: { saved: true }
      }
    });
    expect(JSON.stringify(status)).not.toContain("token");
    expect(JSON.stringify(status)).not.toContain("sgdb-secret");
    expect(createSettingsStore(db, {}).igdbTokenConfig()).toEqual({ clientId: "client", clientSecret: undefined, accessToken: "token" });
  });

  test("clears all stored credentials through one interface", async () => {
    const db = setupDb();
    const previous = clearProcessCredentialEnv();
    await updateSettingsCredentials(db, {
      IGDB_CLIENT_ID: "client",
      IGDB_CLIENT_SECRET: "secret",
      IGDB_ACCESS_TOKEN: "token",
      STEAMGRIDDB_API_KEY: "sgdb-secret"
    });

    try {
      const result = await clearSettingsCredentials(db);

      expect(result.settings.credentialStatus.status).toBe("missing");
      expect(result.settings.credentials).toEqual({
        IGDB_CLIENT_ID: { saved: false },
        IGDB_CLIENT_SECRET: { saved: false },
        IGDB_ACCESS_TOKEN: { saved: false },
        STEAMGRIDDB_API_KEY: { saved: false }
      });
    } finally {
      restoreProcessCredentialEnv(previous);
    }
  });

  test("tests saved credentials through the IGDB gateway", async () => {
    const db = setupDb();
    await updateSettingsCredentials(db, { IGDB_CLIENT_ID: "client", IGDB_ACCESS_TOKEN: "token" });
    let validated = 0;

    const result = await testSettingsCredentials(db, {
      async validateCredentials() {
        validated++;
      }
    });

    expect(result).toEqual({ credentialStatus: { status: "ready" } });
    expect(validated).toBe(1);
  });

  test("a saved value wins over the environment, and a blank value falls back to it", async () => {
    const db = setupDb();
    const env = { STEAMGRIDDB_API_KEY: "from-env" };
    expect(createSettingsStore(db, env).steamGridDbApiKey()).toBe("from-env");

    await updateSettingsCredentials(db, { STEAMGRIDDB_API_KEY: "saved" });
    expect(createSettingsStore(db, env).steamGridDbApiKey()).toBe("saved");

    await updateSettingsCredentials(db, { STEAMGRIDDB_API_KEY: "" });
    expect(createSettingsStore(db, env).steamGridDbApiKey()).toBe("from-env");
  });

  test("maps validation failures to credential status", async () => {
    const db = setupDb();
    await updateSettingsCredentials(db, { IGDB_CLIENT_ID: "client", IGDB_ACCESS_TOKEN: "bad-token" });

    const result = await testSettingsCredentials(db, {
      async validateCredentials() {
        throw new Error("IGDB rejected credentials: 401");
      }
    });

    expect(result).toEqual({ credentialStatus: { status: "expired-or-rejected", message: "IGDB rejected credentials: 401" } });
  });
});

function setupDb() {
  const dir = mkdtempSync(join(tmpdir(), "grt-settings-"));
  dirs.push(dir);
  const db = openDatabase(join(dir, "tracker.db"));
  dbs.push(db);
  runMigrations(db);
  return db;
}

function clearProcessCredentialEnv() {
  const previous = {
    IGDB_CLIENT_ID: process.env.IGDB_CLIENT_ID,
    IGDB_CLIENT_SECRET: process.env.IGDB_CLIENT_SECRET,
    IGDB_ACCESS_TOKEN: process.env.IGDB_ACCESS_TOKEN
  };
  delete process.env.IGDB_CLIENT_ID;
  delete process.env.IGDB_CLIENT_SECRET;
  delete process.env.IGDB_ACCESS_TOKEN;
  return previous;
}

function restoreProcessCredentialEnv(previous: Record<string, string | undefined>) {
  for (const [key, value] of Object.entries(previous)) {
    if (value === undefined) delete process.env[key];
    else process.env[key] = value;
  }
}
