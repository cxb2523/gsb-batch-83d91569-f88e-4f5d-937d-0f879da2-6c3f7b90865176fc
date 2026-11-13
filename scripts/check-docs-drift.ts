/**
 * Docs drift check — compares source-of-truth code definitions
 * against documentation markdown files.
 *
 * Usage: npx tsx scripts/check-docs-drift.ts <docs-dir>
 *   e.g.: npx tsx scripts/check-docs-drift.ts ../crawlee-cloud.github.io/src/docs
 *
 * Exit 0 = in sync, Exit 1 = drift found
 */

import { readFileSync, readdirSync } from 'node:fs';
import { join, resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, '..');
const docsDir = process.argv[2];

if (!docsDir) {
  console.error('Usage: npx tsx scripts/check-docs-drift.ts <docs-directory>');
  process.exit(1);
}

let driftFound = false;

function report(category: string, item: string) {
  console.error(`  DRIFT [${category}]: ${item} — present in code but not in docs`);
  driftFound = true;
}

// --- 1. Extract API routes from source ---
function extractRoutes(): string[] {
  const routesDir = join(ROOT, 'packages/api/src/routes');
  const routes: string[] = [];
  const routePattern = /\.(get|post|put|delete|patch)\s*[<(]\s*['"`]([^'"`]+)/g;

  for (const file of readdirSync(routesDir).filter((f) => f.endsWith('.ts'))) {
    const content = readFileSync(join(routesDir, file), 'utf8');
    let match: RegExpExecArray | null;
    while ((match = routePattern.exec(content)) !== null) {
      const method = match[1].toUpperCase();
      const path = match[2];
      routes.push(`${method} ${path}`);
    }
  }
  return routes;
}

// --- 2. Extract CLI commands from source ---
function extractCliCommands(): string[] {
  const commandsDir = join(ROOT, 'packages/cli/src/commands');
  try {
    return readdirSync(commandsDir)
      .filter((f) => f.endsWith('.ts'))
      .map((f) => f.replace('.ts', ''));
  } catch {
    return [];
  }
}

// --- 3. Extract env vars from config files ---
function extractEnvVars(): { api: string[]; runner: string[] } {
  const envPattern = /process\.env\.(\w+)/g;

  function extract(filePath: string): string[] {
    try {
      const content = readFileSync(filePath, 'utf8');
      const vars: string[] = [];
      let match: RegExpExecArray | null;
      while ((match = envPattern.exec(content)) !== null) {
        vars.push(match[1]);
      }
      return [...new Set(vars)] as string[];
    } catch {
      return [];
    }
  }

  return {
    api: extract(join(ROOT, 'packages/api/src/config.ts')),
    runner: extract(join(ROOT, 'packages/runner/src/config.ts')),
  };
}

// --- 4. Check against docs ---
function readDoc(name: string): string {
  try {
    return readFileSync(join(resolve(docsDir), name), 'utf8');
  } catch {
    console.error(`  WARNING: docs file ${name} not found`);
    return '';
  }
}

// Check API routes
console.log('Checking API routes...');
const apiDoc = readDoc('api.md');
// Routes from auth.ts and users.ts are platform-specific (not Apify-compatible API)
// and documented separately from the main API reference
const skipRoutePrefixes = [
  '/v2/auth/',
  '/users/',
  '/actor-runs/:runId/logs/stream',
  '/webhooks',
  '/schedules',
  '/health',
  '/metrics',
];
for (const route of extractRoutes()) {
  const path = route.split(' ')[1];
  if (skipRoutePrefixes.some((prefix) => path.startsWith(prefix) || path === prefix)) continue;
  if (!apiDoc.includes(path)) {
    report('API route', route);
  }
}

// Check CLI commands
console.log('Checking CLI commands...');
const cliDoc = readDoc('cli.md');
for (const cmd of extractCliCommands()) {
  // Check command name appears in cli.md (as heading or backtick ref)
  if (!cliDoc.includes(cmd)) {
    report('CLI command', cmd);
  }
}

// Check env vars
console.log('Checking env vars...');
const deployDoc = readDoc('deployment.md');
const runnerDoc = readDoc('runner.md');

const envVars = extractEnvVars();
// Skip common/internal vars that don't need documentation
const skipVars = new Set(['NODE_ENV', 'npm_package_version']);

for (const v of envVars.api) {
  if (skipVars.has(v)) continue;
  if (!deployDoc.includes(v)) {
    report('API env var', `${v} (expected in deployment.md)`);
  }
}

for (const v of envVars.runner) {
  if (skipVars.has(v)) continue;
  if (!runnerDoc.includes(v) && !deployDoc.includes(v)) {
    report('Runner env var', `${v} (expected in runner.md or deployment.md)`);
  }
}

// --- Result ---
if (driftFound) {
  console.error('\nDocs drift detected! Please update documentation.');
  process.exit(1);
} else {
  console.log('\nAll checks passed — docs are in sync with code.');
  process.exit(0);
}
