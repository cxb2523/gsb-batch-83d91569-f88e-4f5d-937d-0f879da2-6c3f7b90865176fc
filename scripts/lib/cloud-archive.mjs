import { createHash } from 'node:crypto';
import { gzipSync, gunzipSync } from 'node:zlib';
import { validateSeed } from './seed.mjs';

const prefix = 'etf-test-archive-';
const digest = bytes => createHash('sha256').update(bytes).digest('hex');
export function packSnapshot(seed, { id, trigger, collectedAt = new Date().toISOString() }) {
  validateSeed(seed, 'live');
  if (!/^\d{8}T\d{6}Z-[a-zA-Z0-9-]+$/.test(id)) throw new Error('Invalid archive id');
  const copy = structuredClone(seed);
  copy.cloud_update = { target: 'test', archive_id: id, collected_at: collectedAt, trigger,
    timezone: 'Asia/Shanghai', schedule: ['08:00', '12:30', '18:00'] };
  const bytes = gzipSync(JSON.stringify(copy) + '\n');
  const manifest = { schema: 1, target: 'test', id, file: 'seed-' + id + '.json.gz', sha256: digest(bytes),
    collected_at: collectedAt, flow_through: copy.latest_flow_date, market_through: copy.latest_market_date,
    history_start: copy.broad.dates[0], funds: copy.universe.length, snapshot_built_at: copy.built_at };
  return { seed: copy, bytes, manifest };
}
export function unpackSnapshot(bytes, manifest) {
  if (manifest.schema !== 1 || manifest.target !== 'test' || digest(bytes) !== manifest.sha256) throw new Error('Archive checksum or manifest mismatch');
  const seed = validateSeed(JSON.parse(gunzipSync(bytes, { maxOutputLength: 50 * 1024 * 1024 })), 'live');
  if (seed.cloud_update?.archive_id !== manifest.id || seed.latest_flow_date !== manifest.flow_through || seed.universe.length !== manifest.funds) throw new Error('Archive contents do not match manifest');
  return seed;
}
export function checkCandidate(previous, next) {
  validateSeed(next, 'live');
  if (next.latest_flow_date < previous.latest_flow_date || next.broad.dates[0] > previous.broad.dates[0]) throw new Error('Candidate would lose historical coverage');
  const dates = new Map(next.broad.dates.map((d, i) => [d, i]));
  for (const [i, d] of previous.broad.dates.entries()) {
    if (d <= previous.latest_flow_date && previous.broad.total[i] !== null && next.broad.total[dates.get(d)] == null) throw new Error('Candidate lost a complete historical day');
  }
  if (next.broad.dates.some((d, i) => d <= next.latest_flow_date && next.broad.total[i] === null)) throw new Error('Candidate contains incomplete published flow dates');
}
export function githubArchive({ repository, token, fetcher = fetch }) {
  if (!/^[\w.-]+\/[\w.-]+$/.test(repository || '') || !token) throw new Error('Configure private repository and GitHub authorization');
  const root = '/repos/' + repository;
  let privateCheck;
  async function request(path, { method = 'GET', body, binary = false, upload = false, allow404 = false, type } = {}) {
    const response = await fetcher(path.startsWith('https://') ? path : 'https://api.github.com' + path, {
      method, headers: { authorization: 'Bearer ' + token, accept: binary ? 'application/octet-stream' : 'application/vnd.github+json',
        'user-agent': 'ftshare-etf-cloud-archive', 'x-github-api-version': '2022-11-28',
        ...(body ? { 'content-type': type || 'application/json' } : {}) },
      ...(body ? { body: upload ? body : JSON.stringify(body) } : {}), signal: AbortSignal.timeout(60000)
    });
    if (response.status === 404 && allow404) return null;
    if (!response.ok) throw new Error('GitHub archive request failed (HTTP ' + response.status + ')');
    return binary ? Buffer.from(await response.arrayBuffer()) : response.json();
  }
  return {
    async restore(id) {
      privateCheck ||= request(root).then(repo => { if (!repo.private) throw new Error('Real archives require a private repository'); });
      await privateCheck;
      const releases = [];
      for (let page = 1; page <= 10; page++) {
        const rows = await request(root + '/releases?per_page=100&page=' + page);
        releases.push(...rows.filter(r => r.tag_name.startsWith(prefix) && !r.draft));
        if (rows.length < 100) break;
      }
      // A month contains more than one page of assets; do not rely on a nested list's defaults.
      for (const release of releases) {
        release.assets = [];
        for (let page = 1; page <= 100; page++) {
          const rows = await request(root + '/releases/' + release.id + '/assets?per_page=100&page=' + page);
          release.assets.push(...rows);
          if (rows.length < 100) break;
          if (page === 100) throw new Error('Archive asset listing incomplete');
        }
      }
      const candidates = releases.flatMap(r => r.assets.filter(a => /^seed-\d{8}T\d{6}Z-[\w-]+\.manifest\.json$/.test(a.name)).map(a => ({ release: r, asset: a })))
        .filter(c => !id || c.asset.name === 'seed-' + id + '.manifest.json').sort((a, b) => b.asset.name.localeCompare(a.asset.name));
      if (!candidates.length) throw new Error('No complete test archive found');
      const candidate = candidates.find(c => c.release.assets.some(a => a.name === c.asset.name.replace('.manifest.json', '.json.gz')));
      if (!candidate) throw new Error('Archive is missing its data file');
      const manifest = JSON.parse((await request(root + '/releases/assets/' + candidate.asset.id, { binary: true })).toString());
      if (manifest.file !== candidate.asset.name.replace('.manifest.json', '.json.gz')) throw new Error('Unexpected archive filename');
      const data = candidate.release.assets.find(a => a.name === manifest.file);
      const seed = unpackSnapshot(await request(root + '/releases/assets/' + data.id, { binary: true }), manifest);
      return { seed, manifest };
    },
    async save(packed, commit) {
      privateCheck ||= request(root).then(repo => { if (!repo.private) throw new Error('Real archives require a private repository'); });
      await privateCheck;
      const tag = prefix + packed.manifest.collected_at.slice(0, 7);
      let release = await request(root + '/releases/tags/' + tag, { allow404: true });
      if (!release) release = await request(root + '/releases', { method: 'POST', body: { tag_name: tag,
        ...(commit ? { target_commitish: commit } : {}), name: 'ETF test data archive ' + tag.slice(prefix.length),
        body: 'Private test snapshots with SHA-256 manifests. Independent from the formal website.', prerelease: true, make_latest: 'false' } });
      const url = release.upload_url.replace(/\{.*$/, '');
      await request(url + '?name=' + encodeURIComponent(packed.manifest.file), { method: 'POST', body: packed.bytes, upload: true, type: 'application/gzip' });
      // Publish the manifest last. An interrupted upload is never selected as a complete archive.
      await request(url + '?name=' + encodeURIComponent(packed.manifest.file.replace('.json.gz', '.manifest.json')), {
        method: 'POST', body: Buffer.from(JSON.stringify(packed.manifest, null, 2)), upload: true, type: 'application/json'
      });
      return { tag, id: packed.manifest.id };
    }
  };
}
