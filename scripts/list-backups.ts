/**
 * List available database backups.
 *
 * Usage: npx tsx scripts/list-backups.ts [--dir ./backups/]
 */

import { readdirSync, statSync } from 'node:fs';
import { resolve } from 'node:path';

const args = process.argv.slice(2);
const dirIdx = args.indexOf('--dir');
const dir = resolve(dirIdx !== -1 && args[dirIdx + 1] ? args[dirIdx + 1] : './backups');

try {
  const files = readdirSync(dir)
    .filter((f) => f.endsWith('.dump'))
    .sort()
    .reverse();

  if (files.length === 0) {
    console.log(`No backups found in ${dir}`);
    process.exit(0);
  }

  console.log(`Backups in ${dir}:`);
  console.log('-'.repeat(60));

  for (const file of files) {
    const stat = statSync(resolve(dir, file));
    const sizeMb = (stat.size / 1024 / 1024).toFixed(2);
    const date = stat.mtime.toISOString().slice(0, 19).replace('T', ' ');
    console.log(`  ${file}  ${sizeMb} MB  ${date}`);
  }
} catch {
  console.log(`No backups directory found at ${dir}`);
}
