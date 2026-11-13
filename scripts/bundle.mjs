// Bundles the Electron main process, the preload script and the backend child into one file each,
// written over the files tsc emitted, so the package ships three scripts instead of a node_modules tree.
// electron is provided at runtime; better-sqlite3 is a native module and stays in node_modules.
import { build } from "esbuild";

const entries = {
  "dist/apps/desktop/src/main": "apps/desktop/src/main.ts",
  "dist/apps/desktop/src/preload": "apps/desktop/src/preload.ts",
  "dist/apps/backend/src/child": "apps/backend/src/child.ts"
};

await build({
  entryPoints: entries,
  outdir: ".",
  bundle: true,
  platform: "node",
  format: "cjs",
  target: "node22",
  external: ["electron", "better-sqlite3"],
  logLevel: "warning"
});
