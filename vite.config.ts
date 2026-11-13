import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { readFileSync } from 'node:fs';

// During `npm run dev`, forward /ubus to a real router so you can develop
// against live data. Point it at your router:  ROUTER=192.168.1.1 npm run dev
const ROUTER = process.env.ROUTER || '192.168.1.1';

// Single source of truth for the app version: package.json.
const pkg = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8'));

export default defineConfig({
  plugins: [svelte()],
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version)
  },
  // Relative base so the built app can be served from /untangled/ as well as /.
  base: './',
  build: {
    target: 'es2020',
    outDir: 'dist',
    assetsInlineLimit: 0,
    chunkSizeWarningLimit: 400
  },
  server: {
    // Bind to all interfaces so the dev server is reachable from the LAN
    // (and from the container host's published port). Override with
    // `--host <ip>` on the CLI if you ever need to narrow it.
    host: '0.0.0.0',
    port: 5173,
    strictPort: false,
    // Accept requests regardless of the Host header — needed when reaching
    // the server via the container host's LAN IP rather than localhost.
    allowedHosts: true,
    proxy: {
      '/ubus': {
        target: `https://${ROUTER}`,
        changeOrigin: true,
        secure: false // routers ship a self-signed cert
      }
    }
  }
});
