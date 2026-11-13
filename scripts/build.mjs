import { readFile, writeFile, mkdir, rm } from 'node:fs/promises';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { validateSeed } from './lib/seed.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const mode = process.env.DATA_MODE || 'demo';
const output = resolve(root, process.env.BUILD_OUTPUT_DIR || 'dist');
if (output !== resolve(root, 'dist') && !output.startsWith(resolve(root, '.local/releases') + '/')) throw new Error('Build output must be dist or inside .local/releases');
if (!['demo', 'live'].includes(mode)) throw new Error('DATA_MODE must be demo or live');
const file = mode === 'demo' ? resolve(root, 'data/demo-seed.json') : resolve(root, process.env.FTSHARE_SEED_FILE || 'data/private/seed.json');
let seed;
try { seed = validateSeed(JSON.parse(await readFile(file, 'utf8')), mode); }
catch (error) { throw new Error('Cannot build ' + mode + ' data. See docs/data.md. ' + error.message); }
const assets = {};
for (const [path, type] of [['index.html','text/html'],['style.css','text/css'],['echarts.min.js','text/javascript'],['assets/flow-math.js','text/javascript'],['assets/radar-math.js','text/javascript'],['assets/radar.js','text/javascript'],['assets/dashboard.js','text/javascript'],['assets/presentation.js','text/javascript'],['assets/brush.js','text/javascript'],['assets/ftai-mark.svg','image/svg+xml']]) {
  let body = await readFile(resolve(root, 'src', path), 'utf8');
  if (path === 'index.html') body = body.replace('data-data-mode="demo"', 'data-data-mode="' + mode + '"');
  if (path === 'index.html') body = body.replace('data-radar="off"', 'data-radar="' + (process.env.ENABLE_RADAR === '1' ? 'on' : 'off') + '"');
  assets['/' + path] = { body, type: type + '; charset=utf-8' };
}
for (const [url, file] of [['/licenses/MIT.txt','LICENSE'],['/licenses/echarts-LICENSE.txt','third_party/echarts/LICENSE'],['/licenses/echarts-NOTICE.txt','third_party/echarts/NOTICE'],['/licenses/d3-LICENSE.txt','third_party/echarts/licenses/LICENSE-d3']]) assets[url] = { body: await readFile(resolve(root, file), 'utf8'), type: 'text/plain; charset=utf-8' };
let code = '// Generated build. Provider credentials are runtime-only.\nconst ASSETS=' + JSON.stringify(assets) + ';\nconst SEED=' + JSON.stringify(seed) + ';\n';
for (const path of ['assets/flow-math.js','server/model.js','server/ftshare.js','server/service.js','server/demo.js','server/read-only.js','gateway.js']) code += (await readFile(resolve(root, 'src', path), 'utf8')).replace(/^import .*?;\s*$/gm, '').replace(/^export (?=(?:async )?(?:function|class)|const|let|var)/gm, '') + '\n';
if (/ftshare_sk_[A-Za-z0-9_-]{20,}/.test(code)) throw new Error('A credential was detected in the build');
await rm(output, { recursive: true, force: true });
await mkdir(resolve(output, 'server'), { recursive: true });
await writeFile(resolve(output, 'server/index.js'), code);
await writeFile(resolve(output, 'metadata.json'), JSON.stringify({ mode, radar: process.env.ENABLE_RADAR === '1', built_at: seed.built_at, source_date: seed.latest_flow_date, funds: seed.universe.length }, null, 2) + '\n');
console.log('Built ' + mode + ' dashboard (' + seed.universe.length + ' ETFs). Dashboard assets and data snapshot are ready.');
