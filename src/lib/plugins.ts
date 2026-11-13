// Runtime plugin registry. Plugins are self-contained ES modules discovered
// from plugins/index.json and loaded with dynamic import(), so installing a
// plugin package (which drops files under /www/untangled/plugins/) enriches
// the UI without rebuilding the core. LuCI-style, but framework-agnostic.
import { writable } from 'svelte/store';
import type { NavGroup, NavItem } from './nav';
import type { PluginAPI } from './pluginApi';

export interface UntangledPlugin {
  id: string;               // unique route id, e.g. 'ping'
  title: string;            // nav label / page title
  icon?: string;            // sprite id (e.g. 'i-plugin'); defaults to i-plugin
  group?: string;           // nav group label; defaults to 'Plugins'
  order?: number;           // sort hint
  mount: (container: HTMLElement, api: PluginAPI) => void | (() => void);
  commands?: { label: string; run: () => void }[]; // command-palette entries
}

export const plugins = writable<UntangledPlugin[]>([]);

const BASE = 'plugins/';

export async function loadPlugins(): Promise<void> {
  let manifest: any;
  try {
    const res = await fetch(BASE + 'index.json', { cache: 'no-store' });
    if (!res.ok) return; // no plugins installed — fine
    manifest = await res.json();
  } catch {
    return;
  }
  const entries: any[] = Array.isArray(manifest?.plugins) ? manifest.plugins : [];
  const loaded: UntangledPlugin[] = [];
  const seen = new Set<string>();
  for (const e of entries) {
    const entry = typeof e === 'string' ? e : e?.entry;
    if (!entry) continue;
    try {
      const url = new URL(BASE + entry, document.baseURI).href;
      const mod = await import(/* @vite-ignore */ url);
      const p: UntangledPlugin = mod.default ?? mod.plugin;
      if (p && typeof p.id === 'string' && typeof p.mount === 'function' && !seen.has(p.id)) {
        seen.add(p.id);
        loaded.push(p);
      } else {
        console.warn('[untangled] invalid or duplicate plugin:', entry);
      }
    } catch (err) {
      console.warn('[untangled] plugin failed to load:', entry, err);
    }
  }
  loaded.sort((a, b) => (a.order ?? 100) - (b.order ?? 100));
  plugins.set(loaded);
}

/** Merge plugin-contributed items into the core navigation. */
export function buildNav(core: NavGroup[], plugs: UntangledPlugin[]): NavGroup[] {
  if (!plugs.length) return core;
  const groups: NavGroup[] = core.map((g) => ({ label: g.label, items: [...g.items] }));
  for (const p of plugs) {
    const label = p.group || 'Plugins';
    const item: NavItem = { id: p.id, label: p.title, icon: p.icon?.startsWith('i-') ? p.icon : 'i-plugin' };
    const g = groups.find((x) => x.label === label);
    if (g) g.items.push(item);
    else groups.push({ label, items: [item] });
  }
  return groups;
}
