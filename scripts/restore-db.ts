/**
 * Restore a PostgreSQL backup using pg_restore.
 *
 * Usage: npx tsx scripts/restore-db.ts <backup-file>
 */

import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { createInterface } from 'node:readline';

const backupFile = process.argv[2];
if (!backupFile || !existsSync(backupFile)) {
  console.error('Usage: npx tsx scripts/restore-db.ts <backup-file>');
  console.error('  The backup file must exist.');
  process.exit(1);
}

const databaseUrl = process.env.DATABASE_URL;
if (!databaseUrl) {
  console.error('DATABASE_URL environment variable is required');
  process.exit(1);
}

const rl = createInterface({ input: process.stdin, output: process.stdout });

rl.question(`Restore from ${backupFile}? This will overwrite current data. (yes/no) `, (answer) => {
  rl.close();
  if (answer !== 'yes') {
    console.log('Restore cancelled.');
    process.exit(0);
  }

  console.log('Restoring database...');
  try {
    execFileSync('pg_restore', ['--clean', '--if-exists', `--dbname=${databaseUrl}`, backupFile], {
      stdio: 'inherit',
    });
    console.log('Restore completed successfully');
  } catch (err) {
    console.error('Restore failed:', (err as Error).message);
    process.exit(1);
  }
});
