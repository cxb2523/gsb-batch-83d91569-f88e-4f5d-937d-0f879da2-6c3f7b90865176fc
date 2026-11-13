import { useEffect, useState } from "react";
import type { ApiClient } from "./api/client";

let wallpaperDisplayRevision = 0;

export function useWallpaperWorkflow({
  api,
  apiBaseUrl,
  onError
}: {
  api: ApiClient;
  apiBaseUrl: string;
  onError?: (action: string, error: unknown) => void;
}) {
  const [hasNativeWallpaperPicker] = useState(() => Boolean(typeof window !== "undefined" && window.releaseTracker?.chooseWallpaper));
  const [wallpaperUrl, setWallpaperUrl] = useState("");

  useEffect(() => {
    void loadWallpaper();
  }, [apiBaseUrl]);

  const loadWallpaper = async () => {
    try {
      const wallpaper = await api.getWallpaper();
      setWallpaperUrl(wallpaper.url ? resolveWallpaperDisplayUrl(apiBaseUrl, wallpaper.url) : "");
    } catch (error) {
      onError?.("load-wallpaper", error);
      setWallpaperUrl("");
    }
  };

  const chooseWallpaper = async (file?: File | null) => {
    if (window.releaseTracker?.chooseWallpaper) {
      try {
        const selected = await window.releaseTracker.chooseWallpaper();
        if (!selected) return;
        setResolvedWallpaperUrl(setWallpaperUrl, apiBaseUrl, selected);
      } catch (error) {
        onError?.("choose-wallpaper", error);
      }
      return;
    }
    if (!file) return;
    const selected = URL.createObjectURL(file);
    setWallpaperUrl(current => replaceBlobUrl(current, selected));
  };

  const clearWallpaper = async () => {
    try {
      if (window.releaseTracker?.chooseWallpaper) await api.clearWallpaper();
      setWallpaperUrl(current => replaceBlobUrl(current, ""));
    } catch (error) {
      onError?.("clear-wallpaper", error);
    }
  };

  return {
    hasNativeWallpaperPicker,
    wallpaperUrl,
    actions: {
      chooseWallpaper,
      clearWallpaper
    }
  };
}

export function resolveApiUrl(apiBaseUrl: string, pathOrUrl: string) {
  return new URL(pathOrUrl, apiBaseUrl).toString();
}

export function resolveWallpaperDisplayUrl(apiBaseUrl: string, pathOrUrl: string) {
  const resolved = new URL(pathOrUrl, apiBaseUrl);
  if (resolved.pathname === "/api/wallpaper/current") {
    wallpaperDisplayRevision += 1;
    resolved.searchParams.set("v", `${Date.now()}-${wallpaperDisplayRevision}`);
  }
  return resolved.toString();
}

export function setResolvedWallpaperUrl(setWallpaperUrl: (updater: (current: string) => string) => void, apiBaseUrl: string, pathOrUrl: string) {
  setWallpaperUrl(current => replaceBlobUrl(current, resolveWallpaperDisplayUrl(apiBaseUrl, pathOrUrl)));
}

export function replaceBlobUrl(current: string, next: string) {
  if (current.startsWith("blob:")) URL.revokeObjectURL(current);
  return next;
}
