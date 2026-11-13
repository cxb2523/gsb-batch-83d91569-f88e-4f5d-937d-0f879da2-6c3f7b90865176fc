import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    coverage: {
      enabled: true,
      provider: "v8",
      reporter: ["text", "json-summary", "json"],
      include: ["app/(app)/raHash.ts", "app/(app)/consoleCompanies.ts", "app/(app)/i18n.ts"],
      // Umbral inicial anclado a lo que cubren los tests de hoy (con margen),
      // no al 100% -- sube a medida que se agreguen más tests, no al revés.
      thresholds: {
        lines: 55,
        statements: 50,
        functions: 65,
        branches: 35,
      },
    },
  },
});
