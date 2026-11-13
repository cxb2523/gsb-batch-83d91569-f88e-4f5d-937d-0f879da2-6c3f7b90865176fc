import { createCipheriv, createDecipheriv, randomBytes } from "node:crypto";

const PREFIX = "enc:v1:";

export interface SecretCipher {
  encrypt(plain: string): string;
  // Undefined when the value was sealed with another key or has been tampered with.
  decrypt(sealed: string): string | undefined;
}

export const isSealed = (value: string) => value.startsWith(PREFIX);

// AES-256-GCM with a 32-byte data key given as hex. The desktop app keeps that key encrypted with the
// OS keychain (Electron safeStorage; DPAPI on Windows) and hands it to the backend for each launch,
// so API keys in the SQLite file are unreadable without the user's OS account.
export function createSecretCipher(keyHex: string): SecretCipher {
  const key = Buffer.from(keyHex, "hex");
  if (key.length !== 32) throw new Error("The credential data key must be 32 bytes");
  return {
    encrypt(plain) {
      const iv = randomBytes(12);
      const cipher = createCipheriv("aes-256-gcm", key, iv);
      const body = Buffer.concat([cipher.update(plain, "utf8"), cipher.final()]);
      return `${PREFIX}${iv.toString("base64")}:${cipher.getAuthTag().toString("base64")}:${body.toString("base64")}`;
    },
    decrypt(sealed) {
      if (!isSealed(sealed)) return undefined;
      const [iv, tag, body] = sealed.slice(PREFIX.length).split(":");
      try {
        const decipher = createDecipheriv("aes-256-gcm", key, Buffer.from(iv, "base64"));
        decipher.setAuthTag(Buffer.from(tag, "base64"));
        return Buffer.concat([decipher.update(Buffer.from(body, "base64")), decipher.final()]).toString("utf8");
      } catch {
        return undefined;
      }
    }
  };
}

// The cipher the backend process uses, set once at startup from the desktop app's data key. Without
// one (backend started directly for development) credentials stay as they were.
let processCipher: SecretCipher | undefined;

export function configureProcessCipher(keyHex: string | undefined) {
  processCipher = keyHex ? createSecretCipher(keyHex) : undefined;
}

export const getProcessCipher = () => processCipher;
