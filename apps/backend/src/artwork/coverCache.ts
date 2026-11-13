import { existsSync, mkdirSync, renameSync, writeFileSync } from "node:fs";
import { join } from "node:path";

export type CoverFetch = (url: string) => Promise<Response>;

// IGDB image ids are short lower-case slugs ("co2vvt"); anything else could name a path outside the folder.
const IGDB_IMAGE_ID = /^[a-z0-9]{1,40}$/;
const MAX_COVER_BYTES = 5 * 1024 * 1024;

export const isIgdbImageId = (imageId: string) => IGDB_IMAGE_ID.test(imageId);

// Game covers kept in app data. The first request downloads the 2x IGDB cover; later ones read the disk.
// Serving covers from the app's own origin lets the renderer read their pixels (the detail-page tint),
// which it can't do for images.igdb.com, and keeps covers available offline once seen.
export function createCoverCache({ dir, fetchCover }: { dir: string; fetchCover: CoverFetch }) {
  const downloads = new Map<string, Promise<string | null>>();

  const download = async (imageId: string, file: string) => {
    try {
      const response = await fetchCover(`https://images.igdb.com/igdb/image/upload/t_cover_big_2x/${imageId}.jpg`);
      if (!response.ok || !response.headers.get("content-type")?.startsWith("image/")) return null;
      const bytes = Buffer.from(await response.arrayBuffer());
      if (!bytes.byteLength || bytes.byteLength > MAX_COVER_BYTES) return null;
      mkdirSync(dir, { recursive: true });
      // Written beside the final name and renamed, so a half-written cover is never served.
      const partial = `${file}.part`;
      writeFileSync(partial, bytes);
      renameSync(partial, file);
      return file;
    } catch {
      return null;
    }
  };

  return {
    // The cover's file path, downloading it first if needed; null when it can't be had.
    async file(imageId: string): Promise<string | null> {
      const file = join(dir, `${imageId}.jpg`);
      if (existsSync(file)) return file;
      let pending = downloads.get(imageId);
      if (!pending) {
        pending = download(imageId, file).finally(() => downloads.delete(imageId));
        downloads.set(imageId, pending);
      }
      return pending;
    }
  };
}
