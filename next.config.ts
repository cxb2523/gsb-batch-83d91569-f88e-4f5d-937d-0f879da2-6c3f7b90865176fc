import type { NextConfig } from "next";
import { BASE_PATH } from "./src/lib/base-path";

const config: NextConfig = {
  basePath: BASE_PATH || undefined,
  turbopack: { root: process.cwd() },
  // Ship the OpenF1 snapshot (gitignored) with the server functions when deployed.
  outputFileTracingIncludes: { "/api/**": ["./data/**"] },
  async redirects() {
    // With a base path, the deployment's own domain still opens the demo at its root.
    return BASE_PATH ? [{ source: "/", destination: BASE_PATH, basePath: false, permanent: false }] : [];
  },
};

export default config;
