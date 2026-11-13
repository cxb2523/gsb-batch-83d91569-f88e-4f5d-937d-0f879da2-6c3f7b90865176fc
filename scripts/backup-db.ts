/**
 * Create a PostgreSQL backup using pg_dump.
 *
 * Usage: npx tsx scripts/backup-db.ts [--output ./backups/]
 */

import { execFileSync } from 'node:child_process';
import { mkdirSync, statSync } from 'node:fs';
import { resolve } from 'node:path';

const args = process.argv.slice(2);
const outputIdx = args.indexOf('--output');
const outputDir = resolve(
  outputIdx !== -1 && args[outputIdx + 1] ? args[outputIdx + 1] : './backups'
);

const databaseUrl = process.env.DATABASE_URL;
if (!databaseUrl) {
  console.error('DATABASE_URL environment variable is required');
  process.exit(1);
}

const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
const filename = `crawlee-cloud-backup-${timestamp}.dump`;
const filepath = resolve(outputDir, filename);

mkdirSync(outputDir, { recursive: true });

console.log('Creating database backup...');
console.log(`  Output: ${filepath}`);

try {
  execFileSync('pg_dump', ['--format=custom', '-f', filepath, databaseUrl], { stdio: 'inherit' });
  const size = statSync(filepath).size;
  const sizeMb = (size / 1024 / 1024).toFixed(2);
  console.log(`Backup created successfully (${sizeMb} MB)`);
  console.log(`  File: ${filepath}`);
} catch (err) {
  console.error('Backup failed:', (err as Error).message);
  process.exit(1);
}
