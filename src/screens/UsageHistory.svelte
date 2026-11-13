<script lang="ts">
  import { onMount } from 'svelte';
  import Help from '../components/Help.svelte';
  import { loadVnstat, loadPerDevice, type VnstatData, type PerDeviceData, type UsagePoint } from '../lib/history';
  import { formatBytes } from '../lib/net';

  let vnstat: VnstatData | null = null;
  let perdev: PerDeviceData | null = null;
  let loading = true;
  let error = '';
  let span: 'days' | 'months' = 'days';

  async function load() {
    loading = true;
    try {
      [vnstat, perdev] = await Promise.all([
        loadVnstat().catch(() => ({ installed: false, iface: '', today: { rx: 0, tx: 0 }, month: { rx: 0, tx: 0 }, days: [], months: [] } as VnstatData)),
        loadPerDevice().catch(() => ({ installed: false, rows: [] } as PerDeviceData))
      ]);
      error = '';
    } catch { error = 'Could not read usage history.'; }
    finally { loading = false; }
  }
  onMount(load);

  $: series = (span === 'days' ? vnstat?.days : vnstat?.months) ?? [];
  $: peak = series.reduce((m: number, p: UsagePoint) => Math.max(m, p.rx + p.tx), 0) || 1;
  const pct = (v: number) => Math.max(1, Math.round((v / peak) * 100));
</script>

<div class="page-head"><div><div class="breadcrumb">General</div><h1>Usage History</h1><p>How much data your internet and your devices have used over time.</p></div></div>

{#if loading}
  <div class="panel"><div class="panel-b" style="color:var(--muted);text-align:center;padding:44px">Reading usage history…</div></div>
{:else if error}
  <div class="panel"><div class="panel-b" style="text-align:center;padding:40px"><p style="color:var(--crit);margin:0 0 14px">{error}</p><button class="btn primary" on:click={load}>Retry</button></div></div>
{:else}
  <!-- Internet usage over time (vnstat) -->
  <div class="panel" style="margin-bottom:16px">
    <div class="panel-h"><h2>Internet usage</h2><span class="sub">{vnstat?.installed ? (vnstat.iface || 'wan') : 'vnstat'}</span></div>
    <div class="panel-b">
      {#if !vnstat?.installed}
        <p class="hint" style="margin:0">Install the <span class="mono">vnstat</span> package to keep a history of internet data use (it survives reboots). Usage before it's installed isn't counted.</p>
      {:else}
        <div class="tiles" style="grid-template-columns:repeat(2,1fr);max-width:460px;margin-bottom:18px">
          <div class="tile"><div class="k">Today</div><div class="v" style="font-size:17px;margin-top:10px">{formatBytes(vnstat.today.rx + vnstat.today.tx)}</div><div class="hint mono" style="margin-top:4px">↓ {formatBytes(vnstat.today.rx)} · ↑ {formatBytes(vnstat.today.tx)}</div></div>
          <div class="tile"><div class="k">This month</div><div class="v" style="font-size:17px;margin-top:10px">{formatBytes(vnstat.month.rx + vnstat.month.tx)}</div><div class="hint mono" style="margin-top:4px">↓ {formatBytes(vnstat.month.rx)} · ↑ {formatBytes(vnstat.month.tx)}</div></div>
        </div>

        <div class="seg" role="tablist" style="margin-bottom:14px">
          <button class:active={span === 'days'} on:click={() => (span = 'days')}>Daily</button>
          <button class:active={span === 'months'} on:click={() => (span = 'months')}>Monthly</button>
        </div>

        {#if series.length}
          <div class="chart" role="img" aria-label="Usage bar chart">
            {#each series as p}
              <div class="bar-wrap" title={`${p.label}: ${formatBytes(p.rx + p.tx)} (↓${formatBytes(p.rx)} ↑${formatBytes(p.tx)})`}>
                <div class="bar"><i style="height:{pct(p.rx + p.tx)}%"></i></div>
                <span class="bl">{p.label}</span>
              </div>
            {/each}
          </div>
        {:else}
          <p class="hint" style="margin:0">No data recorded yet — check back after some traffic has flowed.</p>
        {/if}
      {/if}
    </div>
  </div>

  <!-- Per-device usage (nlbwmon) -->
  <div class="panel">
    <div class="panel-h"><h2>By device<Help text="Data used per device for the current accounting period. Needs the nlbwmon package, which records per-device totals on the router." /></h2><span class="sub">{perdev?.installed ? 'nlbwmon' : 'nlbwmon'}</span></div>
    {#if !perdev?.installed}
      <div class="panel-b"><p class="hint" style="margin:0">Install the <span class="mono">nlbwmon</span> package to see how much each device has used.</p></div>
    {:else if !perdev.rows.length}
      <div class="panel-b"><p class="hint" style="margin:0">No per-device usage recorded yet.</p></div>
    {:else}
      <div style="overflow-x:auto"><table class="clients">
        <thead><tr><th>Device</th><th>Download</th><th>Upload</th><th>Total</th></tr></thead>
        <tbody>
          {#each perdev.rows as r}
            <tr>
              <td><div class="cname"><span><b>{r.name}</b><small class="mono">{r.ip || r.mac}</small></span></div></td>
              <td class="mono">{formatBytes(r.rx)}</td>
              <td class="mono">{formatBytes(r.tx)}</td>
              <td class="mono"><b>{formatBytes(r.rx + r.tx)}</b></td>
            </tr>
          {/each}
        </tbody>
      </table></div>
    {/if}
  </div>

  <details class="adv" style="max-width:860px"><summary>Advanced details</summary><div class="advb">Internet totals come from <span class="mono">vnstat --json</span> (per-interface, persistent). Per-device figures come from <span class="mono">nlbw -c json</span> (nlbwmon, per-host accounting). Both are read-only; UnTangled stores nothing itself.</div></details>
{/if}

<style>
  .chart { display: flex; align-items: flex-end; gap: 4px; height: 160px; padding: 8px 2px 0; overflow-x: auto; }
  .bar-wrap { display: flex; flex-direction: column; align-items: center; gap: 6px; min-width: 20px; flex: 1; }
  .bar { width: 100%; height: 130px; display: flex; align-items: flex-end; }
  .bar i { width: 100%; border-radius: 4px 4px 0 0; background: linear-gradient(180deg, var(--accent), var(--accent-deep)); transition: height .3s; display: block; }
  .bl { font-size: 10px; color: var(--muted); white-space: nowrap; transform: rotate(-35deg); transform-origin: center; height: 14px; }
</style>
