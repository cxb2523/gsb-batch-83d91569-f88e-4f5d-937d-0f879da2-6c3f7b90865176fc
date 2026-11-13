import { readdir, lstat, readFile } from 'node:fs/promises';
import { resolve, relative } from 'node:path';
export const releaseRoots = ['src', 'scripts', 'tests', 'config', 'docs', 'third_party', '.github', 'data/demo-seed.json', 'README.md', 'CHANGELOG.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'CONTRIBUTING.md', 'SECURITY.md', '.gitignore', '.dockerignore', '.env.example', '.dev.vars.example', 'Dockerfile', 'compose.yaml', 'wrangler.jsonc', 'package.json', 'package-lock.json'];
export async function releaseFiles(root) {
  const files = [];
  async function walk(path) {
    const file = relative(root, path).replaceAll('\\', '/');
    if (/(^|\/)(node_modules|private|\.local|\.openai|\.git|\.wrangler|dist|worker|releases)(\/|$)/.test(file) || /(^|\/)\.DS_Store$/.test(file)) return;
    if (file === '.github/workflows/cloud-test-update.yml' || /^docs\/domain-migration-/.test(file)) return;
    const info = await lstat(path);
    if (info.isSymbolicLink()) throw new Error('Release must not include symlinks: ' + relative(root, path));
    if (info.isDirectory()) for (const item of await readdir(path)) await walk(resolve(path, item));
    else files.push(relative(root, path).replaceAll('\\', '/'));
  }
  for (const entry of releaseRoots) await walk(resolve(root, entry));
  return files.sort();
}
export async function auditRelease(root) {
  const files = await releaseFiles(root);
  for (const file of files) {
    if (/(^|\/)(node_modules|private|\.local|\.openai|\.git|dist)(\/|$)/.test(file)) throw new Error('Private/generated path selected: ' + file);
    if (!['.env.example', '.dev.vars.example'].includes(file) && /(^|\/)(\.env(?:\..*)?|\.dev\.vars(?:\..*)?|[^/]+\.(key|pem|log))$/.test(file)) throw new Error('Environment/credential file selected: ' + file);
    const buffer = await readFile(resolve(root, file));
    if (/\.(png|jpg|jpeg|webp)$/.test(file)) continue;
    const text = buffer.toString('utf8');
    if (/ftshare_sk_[A-Za-z0-9_-]{20,}/.test(text)) throw new Error('Credential detected in ' + file);
    if (/(?:ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)/.test(text)) throw new Error('Credential detected in ' + file);
    if (/appg(?:prj|ver|dep)_[a-z0-9]{20,}/.test(text)) throw new Error('Hosted project identity detected in ' + file);
    if (/\/Users\/[a-zA-Z0-9][^\s"']*|\/var\/folders\//.test(text)) throw new Error('Machine path detected in ' + file);
  }
  return files;
}
