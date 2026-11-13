// Optional: produce .gz copies of built assets for a gzip-capable front-end
// (e.g. nginx `gzip_static`). NOT used by the OpenWrt apk/ipk — stock uhttpd
// does not negotiate precompressed files, and the overlay/squashfs filesystem
// already compresses the plain assets on flash.
import { readdirSync, statSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { gzipSync } from 'node:zlib';

const DIST = 'dist';
const EXT = /\.(js|css|html|svg|json|map)$/;
let count = 0, before = 0, after = 0;

function walk(dir) {
  for (const entry of readdirSync(dir)) {
    const p = join(dir, entry);
    const s = statSync(p);
    if (s.isDirectory()) walk(p);
    else if (EXT.test(entry)) {
      const buf = readFileSync(p);
      const gz = gzipSync(buf, { level: 9 });
      writeFileSync(p + '.gz', gz);
      count++; before += buf.length; after += gz.length;
    }
  }
}

try {
  walk(DIST);
  console.log(`gzipped ${count} files: ${(before / 1024).toFixed(1)} KB -> ${(after / 1024).toFixed(1)} KB`);
} catch (e) {
  console.error('gzip-dist: build dist/ first (npm run build).', e.message);
  process.exit(1);
}
