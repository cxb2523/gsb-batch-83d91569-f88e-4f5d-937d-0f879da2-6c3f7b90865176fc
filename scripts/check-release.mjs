import { fileURLToPath } from 'node:url';
import { auditRelease } from './lib/release.mjs';
const files = await auditRelease(fileURLToPath(new URL('../', import.meta.url)));
console.log('Release source audit passed: ' + files.length + ' files; private data, environment files, hosting IDs and generated builds excluded.');
