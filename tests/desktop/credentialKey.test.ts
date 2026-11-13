import { afterEach, describe, expect, test } from "vitest";
import { existsSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { loadCredentialDataKey } from "../../apps/desktop/src/credentialKey";

const dirs: string[] = [];
afterEach(() => {
  for (const dir of dirs) rmSync(dir, { recursive: true, force: true });
  dirs.length = 0;
});

function tempDir() {
  const dir = mkdtempSync(join(tmpdir(), "grt-key-"));
  dirs.push(dir);
  return dir;
}

// Stands in for Electron safeStorage: "encrypts" by reversing bytes, fails on anything it did not write.
function fakeSafeStorage(available = true) {
  return {
    isEncryptionAvailable: () => available,
    encryptString: (plain: string) => Buffer.concat([Buffer.from("SEALED:"), Buffer.from(plain).reverse()]),
    decryptString: (sealed: Buffer) => {
      if (!sealed.subarray(0, 7).equals(Buffer.from("SEALED:"))) throw new Error("Error while decrypting the ciphertext");
      return Buffer.from(sealed.subarray(7)).reverse().toString();
    }
  };
}

describe("credential data key", () => {
  test("is created once, stored only in OS-encrypted form, and reused on the next launch", () => {
    const dir = tempDir();
    const safeStorage = fakeSafeStorage();

    const first = loadCredentialDataKey({ dir, safeStorage });
    const second = loadCredentialDataKey({ dir, safeStorage });

    expect(first).toMatch(/^[0-9a-f]{64}$/);
    expect(second).toBe(first);
    expect(readFileSync(join(dir, "credential-key.bin")).toString()).not.toContain(first!);
  });

  test("without OS encryption there is no key, so nothing pretends to be protected", () => {
    expect(loadCredentialDataKey({ dir: tempDir(), safeStorage: fakeSafeStorage(false) })).toBeUndefined();
  });

  test("an unreadable key file is set aside, not overwritten, and a new key is made", () => {
    const dir = tempDir();
    writeFileSync(join(dir, "credential-key.bin"), "garbage from another account");
    const events: string[] = [];

    const key = loadCredentialDataKey({ dir, safeStorage: fakeSafeStorage(), log: event => events.push(event) });

    expect(key).toMatch(/^[0-9a-f]{64}$/);
    expect(readFileSync(join(dir, "credential-key.bin.unreadable"), "utf8")).toBe("garbage from another account");
    expect(existsSync(join(dir, "credential-key.bin"))).toBe(true);
    expect(events).toContain("credentials.key_unreadable");
  });

  test("a second unreadable key file does not overwrite the first recovery copy", () => {
    const dir = tempDir();
    writeFileSync(join(dir, "credential-key.bin"), "first bad key");
    loadCredentialDataKey({ dir, safeStorage: fakeSafeStorage() });
    writeFileSync(join(dir, "credential-key.bin"), "second bad key");

    loadCredentialDataKey({ dir, safeStorage: fakeSafeStorage() });

    const copies = readdirSync(dir).filter(name => name.startsWith("credential-key.bin.unreadable")).map(name => readFileSync(join(dir, name), "utf8"));
    expect(copies.sort()).toEqual(["first bad key", "second bad key"]);
  });

  test("a data folder that cannot be written leaves credentials unencrypted instead of stopping startup", () => {
    const events: string[] = [];
    const safeStorage = { ...fakeSafeStorage(), encryptString: () => { throw new Error("keychain error"); } };

    expect(loadCredentialDataKey({ dir: tempDir(), safeStorage, log: event => events.push(event) })).toBeUndefined();
    expect(events).toContain("credentials.key_unavailable");
  });

  test("a failing log does not stop startup", () => {
    const dir = tempDir();
    writeFileSync(join(dir, "credential-key.bin"), "garbage");

    expect(loadCredentialDataKey({ dir, safeStorage: fakeSafeStorage(), log: () => { throw new Error("log rotated away"); } })).toMatch(/^[0-9a-f]{64}$/);
  });
});
