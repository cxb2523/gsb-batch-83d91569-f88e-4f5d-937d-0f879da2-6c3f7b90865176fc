import { copyFileSync, existsSync, mkdirSync, readFileSync, readdirSync, rmSync } from "node:fs";
import { extname, join } from "node:path";

interface WallpaperStatus {
  hasWallpaper: boolean;
  url: string | null;
}

export const wallpaperUrl = "/api/wallpaper/current";

const wallpaperBaseName = "current";
const allowedExtensions = new Set([".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"]);
const contentTypes: Record<string, string> = {
  ".bmp": "image/bmp",
  ".gif": "image/gif",
  ".jpeg": "image/jpeg",
  ".jpg": "image/jpeg",
  ".png": "image/png",
  ".webp": "image/webp"
};

export function wallpaperStatus(dataDir: string): WallpaperStatus {
  return currentWallpaperPath(dataDir) ? { hasWallpaper: true, url: wallpaperUrl } : { hasWallpaper: false, url: null };
}

export function saveWallpaperFromFile(dataDir: string, sourcePath: string): WallpaperStatus {
  const extension = resolveWallpaperExtension(sourcePath);
  clearWallpaper(dataDir);
  mkdirSync(wallpaperDir(dataDir), { recursive: true });
  copyFileSync(sourcePath, wallpaperPath(dataDir, extension));
  return { hasWallpaper: true, url: wallpaperUrl };
}

export function clearWallpaper(dataDir: string) {
  if (existsSync(wallpaperDir(dataDir))) rmSync(wallpaperDir(dataDir), { recursive: true, force: true });
}

export function currentWallpaperPath(dataDir: string) {
  const dir = wallpaperDir(dataDir);
  if (!existsSync(dir)) return null;
  const fileName = readdirSync(dir).find(name => name.startsWith(`${wallpaperBaseName}.`) && allowedExtensions.has(extname(name).toLowerCase()));
  return fileName ? join(dir, fileName) : null;
}

export function readCurrentWallpaper(dataDir: string) {
  const filePath = currentWallpaperPath(dataDir);
  if (!filePath) return null;
  const extension = extname(filePath).toLowerCase();
  return {
    bytes: readFileSync(filePath),
    contentType: contentTypes[extension] ?? "application/octet-stream"
  };
}

function wallpaperPath(dataDir: string, extension: string) {
  return join(wallpaperDir(dataDir), `${wallpaperBaseName}${extension === ".jpeg" ? ".jpg" : extension}`);
}

function wallpaperDir(dataDir: string) {
  return join(dataDir, "wallpaper");
}

function resolveWallpaperExtension(filePath: string) {
  return normalizeWallpaperExtension(extname(filePath).toLowerCase());
}

function normalizeWallpaperExtension(extension: string) {
  const normalized = extension.toLowerCase();
  if (!allowedExtensions.has(normalized)) throw new Error("Unsupported wallpaper file type");
  return normalized;
}
