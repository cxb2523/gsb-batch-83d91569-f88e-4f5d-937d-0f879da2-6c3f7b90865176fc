import { useCallback, useEffect, useState } from "react";
import type { ApiClient } from "../api/client";
import { getPalette, paletteToCssVars, type Palette } from "./palettes";

// A fast first paint only. App data (through the API) is the saved choice; localStorage can be empty
// (a new profile, or the development server) or stale.
const STORAGE_KEY = "grt.palette";

function applyPalette(palette: Palette) {
  for (const [key, value] of Object.entries(paletteToCssVars(palette))) {
    document.documentElement.style.setProperty(key, value);
  }
  document.documentElement.dataset.theme = palette.id;
}

function readCached() {
  try { return localStorage.getItem(STORAGE_KEY); } catch { return null; }
}

function cache(id: string) {
  try { localStorage.setItem(STORAGE_KEY, id); } catch { /* Storage can be unavailable. */ }
}

// The app-wide choices saved in app data: the palette (with its localStorage first-paint cache) and whether
// Year in Review's theme music starts by itself. Both come back from one GET /api/preferences.
export function usePreferences(api: Pick<ApiClient, "getPreferences" | "savePalette" | "saveThemeAutoplay">) {
  const [palette, setPalette] = useState<Palette>(() => getPalette(readCached()));
  const [themeAutoplay, setThemeAutoplayState] = useState(false);

  const show = (next: Palette) => {
    setPalette(next);
    applyPalette(next);
    cache(next.id);
  };

  useEffect(() => {
    applyPalette(palette);
    let current = true;
    const cached = readCached();
    void api.getPreferences().then(({ palette: saved, themeAutoplay: autoplay }) => {
      if (!current) return;
      setThemeAutoplayState(autoplay);
      if (saved) show(getPalette(saved));
      // Carry a choice only this origin remembered (versions before app-data palettes) into app data.
      else if (cached && getPalette(cached).id === cached) void api.savePalette(cached).catch(() => undefined);
    }).catch(() => undefined);
    return () => { current = false; };
  }, [api]);

  const setPaletteId = useCallback((id: string) => {
    const resolved = getPalette(id);
    show(resolved);
    void api.savePalette(resolved.id).catch(() => undefined);
  }, [api]);

  const setThemeAutoplay = useCallback((on: boolean) => {
    setThemeAutoplayState(on);
    void api.saveThemeAutoplay(on).catch(() => undefined);
  }, [api]);

  return { palette, setPaletteId, themeAutoplay, setThemeAutoplay };
}
