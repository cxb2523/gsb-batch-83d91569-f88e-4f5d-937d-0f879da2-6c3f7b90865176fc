import { randomUUID } from "node:crypto";
import { existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { extname, join } from "node:path";
import type { ReleaseArtwork } from "../../../../shared/types";
import { resolveBackendRuntimeLayout } from "../../../runtime/src/layout";

export interface LocalArtworkPayload {
  fileName?: string;
  mimeType?: string;
  dataBase64?: string;
}

const maxLocalArtworkBytes = 10 * 1024 * 1024;

const allowedMimeExtensions = new Map([
  ["image/jpeg", ".jpg"],
  ["image/jpg", ".jpg"],
  ["image/png", ".png"],
  ["image/webp", ".webp"]
]);

const allowedExtensions = new Set([".jpg", ".jpeg", ".png", ".webp"]);

// A problem with the uploaded file itself; callers report it as a bad request.
export class ArtworkValidationError extends Error {}

export interface PreparedLocalArtwork {
  artwork: ReleaseArtwork;
  write(): void;
}

// Validates and names the upload without touching disk, so the caller can record it first and write after.
export function prepareLocalArtwork(payload: LocalArtworkPayload): PreparedLocalArtwork {
  const extension = resolveArtworkExtension(payload);
  const bytes = decodeArtworkBytes(payload.dataBase64);
  if (bytes.byteLength > maxLocalArtworkBytes) throw new ArtworkValidationError("Artwork upload is larger than 10 MB");
  const fileName = `${randomUUID()}${extension === ".jpeg" ? ".jpg" : extension}`;
  return {
    artwork: { imageId: fileName, source: "local", url: localArtworkUrl(fileName) },
    write() {
      mkdirSync(localArtworkDir(), { recursive: true });
      writeFileSync(join(localArtworkDir(), fileName), bytes);
    }
  };
}

export function removeLocalArtwork(fileName: string) {
  const file = localArtworkPath(fileName);
  if (existsSync(file)) rmSync(file, { force: true });
}

export function localArtworkPath(fileName: string) {
  return join(localArtworkDir(), sanitizeLocalArtworkFileName(fileName));
}

export function localArtworkUrl(fileName: string) {
  return `/api/artworks/local/${encodeURIComponent(fileName)}`;
}

function localArtworkDir() {
  return resolveBackendRuntimeLayout().artworkDir;
}

function resolveArtworkExtension(payload: LocalArtworkPayload) {
  const mime = payload.mimeType ?? "";
  const extension = allowedMimeExtensions.get(mime) || extname(payload.fileName ?? "").toLowerCase();
  if (!allowedExtensions.has(extension)) throw new ArtworkValidationError("Unsupported artwork file type");
  return extension;
}

function decodeArtworkBytes(dataBase64?: string) {
  if (!dataBase64) throw new ArtworkValidationError("Artwork data is required");
  return Buffer.from(dataBase64, "base64");
}

function sanitizeLocalArtworkFileName(fileName: string) {
  const safeName = fileName.replace(/[^a-zA-Z0-9._-]/g, "");
  return safeName || "__invalid_artwork__";
}
