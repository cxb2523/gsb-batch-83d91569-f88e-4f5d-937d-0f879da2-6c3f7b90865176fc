/// <reference types="svelte" />
/// <reference types="vite/client" />

// Injected at build time from package.json (see vite.config.ts `define`).
declare const __APP_VERSION__: string;

// Custom dev env flag: set VITE_MOCK=false to bypass the mock ubus backend
// and hit a real router through the /ubus proxy.
interface ImportMetaEnv {
  readonly VITE_MOCK?: string;
}
interface ImportMeta {
  readonly env: ImportMetaEnv;
}
