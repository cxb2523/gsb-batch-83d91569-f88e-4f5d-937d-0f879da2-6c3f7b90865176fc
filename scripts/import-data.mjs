import { readFile, writeFile, mkdir, rename } from 'node:fs/promises';
import { resolve } from 'node:path';
import { validateSeed } from './lib/seed.mjs';

const file = process.argv[2];
if (!file || file === '--help') {
  console.log('npm run data:import -- /absolute/path/to/authorized-seed.json\nValidates and copies a compatible live snapshot to ignored data/private/seed.json. No credentials are read.');
  if (!file) process.exitCode = 1;
} else {
  const seed = validateSeed(JSON.parse(await readFile(resolve(file), 'utf8')), 'live');
  const directory = new URL('../data/private/', import.meta.url), path = new URL('seed.json', directory);
  await mkdir(directory, { recursive: true });
  await writeFile(new URL('seed.json.tmp', directory), JSON.stringify(seed) + '\n'); await rename(new URL('seed.json.tmp', directory), path);
  console.log('Imported authorized live snapshot: ' + seed.universe.length + ' ETFs, through ' + seed.latest_flow_date + '. DATA_MODE=live is required to build it.');
}
