// A preview failure never activates main. If main activated before any error,
// restore and confirm the previous canonical deployment before reporting rollback.
export function publicationTarget(env) {
  const target = env.CLOUD_PUBLISH_TARGET || 'test', project = env.CLOUDFLARE_PAGES_PROJECT || '';
  if (target === 'test' && /^[a-z0-9-]*test[a-z0-9-]*$/.test(project)) return target;
  if (target === 'formal' && project === env.CLOUDFLARE_FORMAL_PROJECT && /^[a-z0-9-]+$/.test(project) && /^[a-f0-9]{40}$/.test(env.CLOUDFLARE_FORMAL_SOURCE_REF || '')) return target;
  throw new Error('Configure an approved Pages target and pinned formal source revision');
}
export async function verifyFormalSource({ expected, proof, sourceRef, checkedOutRef, testProject, verify }) {
  if (sourceRef !== checkedOutRef) throw new Error('Formal source does not match its approved revision');
  const published = String(proof.published || '').match(/^https:\/\/([a-z0-9]+)\.([a-z0-9-]+)\.pages\.dev\/?$/);
  if (!/^[a-z0-9-]*test[a-z0-9-]*$/.test(testProject || '') || proof.target !== 'test' || proof.archive_id !== expected.cloud_update?.archive_id || !published || published[2] !== testProject) throw new Error('Missing matching verified test deployment');
  await verify(proof.published);
}
export async function promoteTest({ before, deploy, verify, current, rollback, stableURL, label = 'Test' }) {
  const preview = await deploy('cloud-archive-candidate');
  await verify(preview);
  let published;
  try {
    published = await deploy('main');
    await verify(published); await verify(stableURL);
  } catch {
    const active = await current();
    if (active?.id !== before.id) {
      await rollback(before.id);
      if ((await current())?.id !== before.id) throw new Error(label + ' rollback could not be confirmed; inspect the active deployment');
    }
    throw new Error(label + ' publish validation failed; previous deployment restored');
  }
  return { preview, published };
}

// A live radar release must carry a complete, reconciled per-fund snapshot.
export function verifyRadarSnapshot(seed) {
  const core = seed.core_fund_daily, symbols = seed.universe.filter(f => f.is_core_basket).map(f => f.symbol);
  if (!core || core.date !== seed.latest_flow_date || core.rows?.length !== 20 || symbols.length !== 20 || new Set(core.rows.map(r => r.symbol)).size !== 20 || !symbols.every(s => core.rows.some(r => r.symbol === s))) throw new Error('Radar requires all 20 core ETF flows at the latest published flow date');
  if (!core.rows.every(r => typeof r.flow === 'number' && Number.isFinite(r.flow))) throw new Error('Radar contains an incomplete fund flow');
  const index = seed.history.dates.indexOf(core.date), expected = seed.history.netflow[index], total = core.rows.reduce((sum, r) => sum + r.flow, 0);
  if (typeof expected !== 'number' || !Number.isFinite(expected) || Math.abs(total - expected) > 1e-6) throw new Error('Radar fund flows do not reconcile with the published core basket');
  const complete = Object.entries(seed.minutes || {}).filter(([date, r]) => date < seed.latest_market_date && !r.quality && r.bars?.length === seed.minute_slots.length && r.bars.every(v => typeof v === 'number' && Number.isFinite(v)));
  if (complete.length < 60) throw new Error('Radar requires 60 complete historical minute snapshots');
}
