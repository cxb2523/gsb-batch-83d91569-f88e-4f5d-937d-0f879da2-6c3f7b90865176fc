import { fileURLToPath } from 'node:url';
import { refreshDeployment } from './lib/deployment.mjs';
try {
  const result = await refreshDeployment({ root: fileURLToPath(new URL('../', import.meta.url)), collect: !process.argv.includes('--snapshot-only') });
  console.log(JSON.stringify(result));
} catch (error) {
  console.error(error.message.replace(/ftshare_sk_[A-Za-z0-9_-]+/g, '[redacted]'));
  process.exitCode = 1;
}
