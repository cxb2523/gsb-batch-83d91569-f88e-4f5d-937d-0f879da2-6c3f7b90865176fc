import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  root: "apps/frontend",
  base: "./",
  plugins: [react()],
  build: {
    outDir: "../../dist/frontend",
    emptyOutDir: true
  },
  server: {
    host: "127.0.0.1",
    port: 5173
  }
});
