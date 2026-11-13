<script lang="ts">
  import { onMount } from 'svelte';
  import Icon from '../components/Icon.svelte';
  import { getFirmware, listPackages, type FwInfo, type SoftwareList } from '../lib/software';
  import { toast } from '../lib/toast';
  import { go } from '../lib/stores';

  let fw: FwInfo | null = null;
  let list: SoftwareList = { available: false, managed: false, packages: [] };
  let loading = true;
  let q = '';

  async function load() {
    loading = true;
    try { [fw, list] = await Promise.all([getFirmware().catch(() => null), listPackages()]); }
    finally { loading = false; }
  }
  onMount(load);

  $: filtered = list.packages.filter((p) => !q || p.name.toLowerCase().includes(q.toLowerCase()));
  // Apps we have a dedicated screen for, de-duplicated by screen id.
  $: apps = (() => {
    const seen = new Set<string>();
    const out: { label: string; screen?: string; hint: string; name: string }[] = [];
    for (const p of list.packages) {
      const n = p.notable;
      if (!n) continue;
      const key = n.screen || n.id;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push({ label: n.label, screen: n.screen, hint: n.hint, name: p.name });
    }
    return out;
  })();

  function open(screen?: string) { if (screen) go(screen); }

</script>

<div class="page-head"><div><div class="breadcrumb">System</div><h1>Software</h1><p>Firmware and packages — all on the router, no cloud account.</p></div></div>

{#if loading}
  <div class="panel"><div class="panel-b" style="color:var(--muted);text-align:center;padding:44px">Reading…</div></div>
{:else}
  <div class="panel" style="margin-bottom:18px"><div class="panel-b" style="display:flex;align-items:center;gap:16px;flex-wrap:wrap">
    <div class="devicon" style="width:52px;height:52px"><Icon name="i-pkg" size={24} /></div>
    <div style="flex:1;min-width:200px">
      <div style="font-size:15px;font-weight:700">Firmware · {fw?.firmware ?? 'OpenWRT'}</div>
      <div class="hint mono">{fw?.target ?? ''} · {fw?.kernel ?? ''}</div>
    </div>
  </div></div>

  {#if apps.length}
    <div class="panel" style="margin-bottom:18px">
      <div class="panel-h"><h2>Installed apps</h2><span class="sub">{apps.length}</span></div>
      <div class="panel-b appgrid">
        {#each apps as a}
          <button class="appcard" class:link={!!a.screen} on:click={() => open(a.screen)} disabled={!a.screen} title={a.screen ? 'Open' : a.hint}>
            <div class="appname">{a.label}{#if a.screen}<span class="chev">›</span>{/if}</div>
            <div class="apphint">{a.hint}</div>
          </button>
        {/each}
      </div>
    </div>
  {/if}

  {#if !list.managed}
    <div class="panel"><div class="panel-b">
      <div class="caution"><Icon name="i-pkg" size={20} /><span>{list.message}</span></div>
    </div></div>
  {:else}
    <div class="panel">
      <div class="panel-h"><h2>Packages</h2><span class="sub">{list.available ? 'manageable' : `${list.packages.length} installed`}</span></div>
      {#if !list.available && list.message}
        <div class="panel-b" style="padding-bottom:0"><p class="hint" style="margin:0 0 10px">{list.message}</p></div>
      {/if}
      <div class="panel-b" style="padding-bottom:0"><input type="text" bind:value={q} placeholder="Search packages…" style="width:100%;margin-bottom:12px" /></div>
      <div style="overflow-x:auto"><table class="clients">
        <thead><tr><th>Package</th><th>Version</th><th style="text-align:right">Action</th></tr></thead>
        <tbody>
          {#each filtered as p}
            <tr style="cursor:default">
              <td>
                <b style="font-weight:600">{p.name}</b>
                {#if p.notable}<span class="appbadge" title={p.notable.hint}>app</span>{/if}
              </td>
              <td class="mono">{p.version}</td>
              <td style="text-align:right">
                {#if p.notable?.screen}
                  <button class="btn" style="padding:6px 13px" on:click={() => open(p.notable?.screen)}>Open</button>
                {:else}
                  <span class="hint">installed</span>
                {/if}
              </td>
            </tr>
          {/each}
          {#if !filtered.length}<tr><td colspan="3" style="color:var(--muted);padding:22px">No packages.</td></tr>{/if}
        </tbody>
      </table></div>
    </div>
  {/if}
{/if}

<style>
  .appgrid { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 12px; }
  .appcard { text-align: left; padding: 13px 14px; border: 1px solid var(--line-soft); border-radius: 12px; background: var(--panel-2); cursor: default; }
  .appcard.link { cursor: pointer; }
  .appcard.link:hover { border-color: var(--accent); }
  .appcard:disabled { opacity: 1; }
  .appname { font-weight: 700; font-size: 13.5px; display: flex; align-items: center; justify-content: space-between; gap: 6px; }
  .chev { color: var(--muted); font-size: 18px; line-height: 1; }
  .apphint { color: var(--muted); font-size: 12px; margin-top: 4px; }
  .appbadge { margin-left: 7px; font-size: 10px; font-weight: 700; letter-spacing: .3px; text-transform: uppercase; color: var(--accent-deep); background: rgba(15,181,196,.14); padding: 2px 7px; border-radius: 999px; vertical-align: middle; }
</style>
