import type { TrackerDatabase } from "../database/db";
import type { SavedCredential } from "../../../../shared/types";
import { readTokenConfig, type TokenConfig } from "../igdb/token";
import { getProcessCipher, isSealed, type SecretCipher } from "./secretCipher";
import { CREDENTIAL_KEYS } from "../../../../shared/constants";

type CredentialKey = (typeof CREDENTIAL_KEYS)[number];

const IGDB_KEYS: CredentialKey[] = ["IGDB_CLIENT_ID", "IGDB_CLIENT_SECRET", "IGDB_ACCESS_TOKEN"];

const isCredentialKey = (key: string): key is CredentialKey => (CREDENTIAL_KEYS as readonly string[]).includes(key);

// The Settings Store: the only module that reads or writes the settings table. A saved value wins over
// the matching environment variable; a blank value counts as not saved. With a cipher (the desktop
// app), credentials are encrypted at rest; a value that cannot be decrypted counts as not saved.
export function createSettingsStore(db: TrackerDatabase, env: NodeJS.ProcessEnv = process.env, cipher: SecretCipher | undefined = getProcessCipher()) {
  const readRaw = (key: string) => {
    const row = db.prepare("select value from settings where key = ? and coalesce(value, '') != ''").get(key) as { value: string } | undefined;
    return row?.value;
  };
  const read = (key: string) => {
    const value = readRaw(key);
    if (value === undefined || !isCredentialKey(key) || !isSealed(value)) return value;
    return cipher?.decrypt(value);
  };
  const write = (key: string, value: string) => {
    const stored = cipher && isCredentialKey(key) ? cipher.encrypt(value) : value;
    db.prepare("insert or replace into settings (key, value, updated_at) values (?, ?, current_timestamp)").run(key, stored);
  };
  const remove = (keys: readonly string[]) => {
    const drop = db.prepare("delete from settings where key = ?");
    for (const key of keys) drop.run(key);
  };

  return {
    // Saves the credential fields present in the payload; a blank field deletes the saved value.
    saveCredentials(payload: Record<string, unknown>) {
      for (const [key, value] of Object.entries(payload)) {
        if (!isCredentialKey(key) || typeof value !== "string") continue;
        if (value.trim()) write(key, value);
        else remove([key]);
      }
    },
    clearCredentials() {
      remove(CREDENTIAL_KEYS);
    },
    // Encrypts credentials an older version saved in plain text. Returns how many were sealed.
    encryptStoredCredentials() {
      if (!cipher) return 0;
      let sealed = 0;
      for (const key of CREDENTIAL_KEYS) {
        const value = readRaw(key);
        if (value === undefined || isSealed(value)) continue;
        write(key, value);
        sealed++;
      }
      return sealed;
    },
    // Unreadable: a value is stored but cannot be decrypted (the data key was lost), so it must be entered again.
    savedCredentials(): Record<CredentialKey, SavedCredential> {
      return Object.fromEntries(CREDENTIAL_KEYS.map(key => {
        const saved = read(key) !== undefined;
        return [key, !saved && readRaw(key) !== undefined ? { saved, unreadable: true } : { saved }];
      })) as Record<CredentialKey, SavedCredential>;
    },
    igdbTokenConfig(): TokenConfig {
      const saved = Object.fromEntries(IGDB_KEYS.map(key => [key, read(key)]).filter(([, value]) => value !== undefined));
      return readTokenConfig({ ...env, ...saved });
    },
    steamGridDbApiKey() {
      return read("STEAMGRIDDB_API_KEY") ?? env.STEAMGRIDDB_API_KEY;
    },
    // The version of data/source-overrides.json last applied.
    sourceOverrideVersion() {
      return read("sourceOverrideVersion") ?? null;
    },
    setSourceOverrideVersion(version: string) {
      write("sourceOverrideVersion", version);
    },
    // The HD-2D palette the user picked. The palette list lives in the frontend; this keeps only its id.
    palette() {
      return read("UI_PALETTE") ?? null;
    },
    setPalette(id: string) {
      write("UI_PALETTE", id);
    },
    // Whether Year in Review's theme music starts by itself; off until the user turns it on.
    themeAutoplay() {
      return read("UI_THEME_AUTOPLAY") === "1";
    },
    setThemeAutoplay(on: boolean) {
      write("UI_THEME_AUTOPLAY", on ? "1" : "0");
    }
  };
}
