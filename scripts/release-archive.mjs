import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { auditRelease } from './lib/release.mjs';
const root = fileURLToPath(new URL('../', import.meta.url)), files = await auditRelease(root);
const pkg = JSON.parse(await readFile(resolve(root, 'package.json'), 'utf8'));
const name = pkg.name + '-v' + pkg.version + '.tar.gz', directory = resolve(root, 'releases'), archive = resolve(directory, name);
await mkdir(directory, { recursive: true });
const version = spawnSync('tar', ['--version'], { encoding: 'utf8' });
if (version.status !== 0) throw new Error('A compatible tar command is required to create the source archive');
// Normalize file ownership so release metadata contains only the project files.
const ownership = /bsdtar|libarchive/i.test(version.stdout)
  ? ['--uid=0', '--gid=0', '--uname=root', '--gname=root']
  : ['--owner=0', '--group=0', '--numeric-owner'];
const result = spawnSync('tar', [...ownership, '-czf', archive, '-T', '-'], { cwd: root, input: files.join('\n') + '\n', encoding: 'utf8', env: { ...process.env, COPYFILE_DISABLE: '1' } });
if (result.status !== 0) throw new Error('Source archive failed: ' + (result.stderr || result.error));
const hash = createHash('sha256').update(await readFile(archive)).digest('hex');
await writeFile(archive + '.sha256', hash + '  ' + name + '\n');
console.log(archive); console.log('SHA256: ' + hash);
