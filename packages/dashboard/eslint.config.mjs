import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Silence the React 19 set-state-in-effect rule for the run-detail
  // page. The two effects there call setLoading(true) before kicking off
  // a fetch on tab-switch — a real anti-pattern, but the fix requires
  // moving each fetch from useEffect into an onTabChange handler, which
  // is a behavior change that deserves its own PR. Tracked separately;
  // remove this override once the refactor lands.
  //
  // Why an override (not an inline eslint-disable comment): pre-commit
  // lint-staged runs `eslint --fix` from the repo root, where the React
  // plugin isn't loaded. An inline disable for that rule would either
  // error ("rule not found") or be auto-stripped as "unused". A
  // file-scoped override applies only when the dashboard's config
  // actually loads, so both contexts behave correctly.
  {
    // Parentheses and brackets are minimatch special chars and must be
    // escaped to match the literal Next.js route-group / dynamic-segment
    // directory names.
    files: ["src/app/\\(dashboard\\)/runs/\\[id\\]/page.tsx"],
    rules: {
      "react-hooks/set-state-in-effect": "off",
    },
  },
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
]);

export default eslintConfig;
