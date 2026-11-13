import { fileURLToPath } from 'node:url';
import { preparePages } from './lib/pages.mjs';
console.log(JSON.stringify(await preparePages(fileURLToPath(new URL('../', import.meta.url)))));
