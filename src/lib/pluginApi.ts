// The stable surface passed to every plugin's mount(). Keep this backwards
// compatible — plugins depend on it, so additions are fine but don't break
// existing shapes. Bump PLUGIN_API_VERSION only on a breaking change.
import { call, uciGet, uciSet, uciAdd, uciDelete, uciApply } from './ubus';
import { toast } from './toast';
import { go, theme } from './stores';
import { get } from 'svelte/store';

export const PLUGIN_API_VERSION = '1';

export interface PluginAPI {
  version: string;
  /** Talk to the router (same client the core uses). */
  ubus: {
    call: typeof call;
    uciGet: typeof uciGet;
    uciSet: typeof uciSet;
    uciAdd: typeof uciAdd;
    uciDelete: typeof uciDelete;
    uciApply: typeof uciApply;
  };
  /** Show a toast notification. */
  toast: (msg: string) => void;
  /** Navigate to a screen/plugin by id. */
  navigate: (id: string) => void;
  /** Current theme, for plugins that draw their own charts. */
  getTheme: () => 'light' | 'dark';
}

export function makeApi(): PluginAPI {
  return {
    version: PLUGIN_API_VERSION,
    ubus: { call, uciGet, uciSet, uciAdd, uciDelete, uciApply },
    toast,
    navigate: go,
    getTheme: () => get(theme)
  };
}
