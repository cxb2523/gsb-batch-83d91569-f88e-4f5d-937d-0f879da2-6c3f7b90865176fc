import { randomBytes } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { join } from "node:path";

interface OsEncryption {
  isEncryptionAvailable(): boolean;
  encryptString(plain: string): Buffer;
  decryptString(sealed: Buffer): string;
}

const KEY_FILE = "credential-key.bin";

// The data key the backend uses to encrypt API keys at rest. It is stored only in OS-encrypted form
// (Electron safeStorage: DPAPI on Windows, Keychain on macOS, the secret service on Linux), so a copy of
// the app-data folder alone cannot reveal the credentials. Undefined when the OS offers no encryption or
// the key cannot be stored; startup never fails because of it.
export function loadCredentialDataKey({ dir, safeStorage, log = () => undefined }: {
  dir: string;
  safeStorage: OsEncryption;
  log?: (event: string, details?: Record<string, unknown>) => void;
}): string | undefined {
  const safeLog = (event: string, details?: Record<string, unknown>) => {
    try {
      log(event, details);
    } catch {
      // Diagnostics must not stop the app from starting.
    }
  };
  try {
    if (!safeStorage.isEncryptionAvailable()) {
      safeLog("credentials.os_encryption_unavailable");
      return undefined;
    }
    const file = join(dir, KEY_FILE);
    if (existsSync(file)) {
      try {
        const key = safeStorage.decryptString(readFileSync(file));
        if (/^[0-9a-f]{64}$/.test(key)) return key;
      } catch {
        // Fall through: the file came from another OS account or is damaged.
      }
      // Keep the old file for recovery; credentials sealed with it will ask to be entered again.
      renameSync(file, freeRecoveryPath(`${file}.unreadable`));
      safeLog("credentials.key_unreadable");
    }
    const key = randomBytes(32).toString("hex");
    mkdirSync(dir, { recursive: true });
    writeFileSync(file, safeStorage.encryptString(key));
    return key;
  } catch (error) {
    safeLog("credentials.key_unavailable", { message: error instanceof Error ? error.message : String(error) });
    return undefined;
  }
}

// An earlier recovery copy is never overwritten: later ones get a numbered name.
function freeRecoveryPath(base: string) {
  if (!existsSync(base)) return base;
  for (let index = 2; ; index++) {
    if (!existsSync(`${base}.${index}`)) return `${base}.${index}`;
  }
}
