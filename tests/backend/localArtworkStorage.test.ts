import { afterEach, describe, expect, test } from "vitest";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { localArtworkPath, prepareLocalArtwork, removeLocalArtwork, type LocalArtworkPayload } from "../../apps/backend/src/artwork/localArtworkStorage";

function saveLocalArtwork(payload: LocalArtworkPayload) {
  const prepared = prepareLocalArtwork(payload);
  prepared.write();
  return prepared.artwork;
}

let dirs: string[] = [];

function setupStorage() {
  const dir = mkdtempSync(join(tmpdir(), "grt-artwork-"));
  dirs.push(dir);
  process.env.GRT_DATA_DIR = dir;
  return dir;
}

afterEach(() => {
  for (const dir of dirs) rmSync(dir, { recursive: true, force: true });
  dirs = [];
  delete process.env.GRT_DATA_DIR;
});

describe("local artwork storage", () => {
  test("saves uploaded artwork under the runtime artwork directory", () => {
    const dir = setupStorage();

    const artwork = saveLocalArtwork({
      fileName: "hero.jpeg",
      mimeType: "image/jpeg",
      dataBase64: Buffer.from("fake-jpg").toString("base64")
    });

    expect(artwork).toMatchObject({ source: "local" });
    expect(artwork.imageId.endsWith(".jpg")).toBe(true);
    expect(artwork.url).toBe(`/api/artworks/local/${encodeURIComponent(artwork.imageId)}`);
    expect(readFileSync(join(dir, "artworks", artwork.imageId), "utf8")).toBe("fake-jpg");
  });

  test("removes stored artwork and keeps path resolution inside the artwork directory", () => {
    const dir = setupStorage();
    const artwork = saveLocalArtwork({
      fileName: "hero.png",
      mimeType: "image/png",
      dataBase64: Buffer.from("fake-png").toString("base64")
    });

    expect(localArtworkPath("../bad/hero.png")).toBe(join(dir, "artworks", "..badhero.png"));
    removeLocalArtwork(artwork.imageId);

    expect(existsSync(join(dir, "artworks", artwork.imageId))).toBe(false);
  });

  test("rejects unsupported artwork uploads before writing", () => {
    setupStorage();

    expect(() => saveLocalArtwork({
      fileName: "hero.gif",
      mimeType: "image/gif",
      dataBase64: Buffer.from("fake-gif").toString("base64")
    })).toThrow("Unsupported artwork file type");
  });
});
