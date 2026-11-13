import { readFile, writeFile, mkdir, copyFile, rm } from 'node:fs/promises';
import { resolve } from 'node:path';

// Only publish the fixed client assets and the Pages-reserved server entrypoint.
export async function preparePages(root) {
  const dist = resolve(root, 'dist'), output = resolve(dist, 'pages');
  const metadata = JSON.parse(await readFile(resolve(dist, 'metadata.json'), 'utf8'));
  if (!['demo', 'live'].includes(metadata.mode)) throw new Error('Build the dashboard before preparing Pages');
  const worker = await readFile(resolve(dist, 'server/index.js'), 'utf8');
  if (/ftshare_sk_[A-Za-z0-9_-]{20,}/.test(worker)) throw new Error('Credential detected in Pages entrypoint');
  await rm(output, { recursive: true, force: true });
  await mkdir(resolve(output, 'assets'), { recursive: true });
  await mkdir(resolve(output, 'licenses'), { recursive: true });
  for (const name of ['index.html', 'style.css', 'echarts.min.js', 'assets/dashboard.js', 'assets/flow-math.js', 'assets/radar.js', 'assets/radar-math.js', 'assets/brush.js', 'assets/presentation.js', 'assets/ftai-mark.svg']) {
    if (name === 'index.html') {
      const body = (await readFile(resolve(root, 'src', name), 'utf8')).replace('data-data-mode="demo"', 'data-data-mode="' + metadata.mode + '"').replace('data-radar="off"', 'data-radar="' + (metadata.radar ? 'on' : 'off') + '"');
      await writeFile(resolve(output, name), body);
    } else await copyFile(resolve(root, 'src', name), resolve(output, name));
  }
  for (const [name, source] of [['MIT.txt','LICENSE'],['echarts-LICENSE.txt','third_party/echarts/LICENSE'],['echarts-NOTICE.txt','third_party/echarts/NOTICE'],['d3-LICENSE.txt','third_party/echarts/licenses/LICENSE-d3']]) await copyFile(resolve(root, source), resolve(output, 'licenses', name));
  await writeFile(resolve(output, '_worker.js'), worker);
  await writeFile(resolve(output, '_routes.json'), JSON.stringify({ version: 1, include: ['/api/*'], exclude: [] }) + '\n');
  await writeFile(resolve(output, '_headers'), '/*\n  X-Content-Type-Options: nosniff\n  Referrer-Policy: same-origin\n  Permissions-Policy: camera=(), microphone=(), geolocation=()\n');
  // Disable Pages' implicit SPA fallback: private/unknown paths should be 404,
  // rather than returning the dashboard HTML with an HTTP 200 response.
  await writeFile(resolve(output, '404.html'), '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>页面不存在 · FtShare</title><body><h1>页面不存在</h1><a href="/">返回看板</a></body></html>');
  return { directory: output, mode: metadata.mode, source_date: metadata.source_date };
}
