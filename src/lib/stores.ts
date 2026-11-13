import { writable } from 'svelte/store';

// ---- Theme (light default, dark = Merlin look) -----------------------------
export type Theme = 'light' | 'dark';

function readTheme(): Theme {
  try {
    const t = localStorage.getItem('untangled-theme');
    if (t === 'light' || t === 'dark') return t;
  } catch { /* storage may be unavailable */ }
  return 'light';
}

export const theme = writable<Theme>(readTheme());
theme.subscribe((t) => {
  document.documentElement.setAttribute('data-theme', t);
  try { localStorage.setItem('untangled-theme', t); } catch { /* ignore */ }
});
export function toggleTheme() {
  theme.update((t) => (t === 'dark' ? 'light' : 'dark'));
}

// ---- Session ---------------------------------------------------------------
export interface SessionState {
  username: string | null;
}
export const session = writable<SessionState>({ username: null });

// ---- Hash routing (#screen-id) ---------------------------------------------
function currentHash(): string {
  return location.hash.replace(/^#/, '') || 'map';
}
export const route = writable<string>(currentHash());
window.addEventListener('hashchange', () => route.set(currentHash()));
export function go(id: string) {
  if (location.hash.replace(/^#/, '') !== id) location.hash = id;
  route.set(id);
}

// ---- Command palette -------------------------------------------------------
export const paletteOpen = writable(false);
