<script lang="ts">
  import { onMount, onDestroy, tick } from 'svelte';
  import { getLog, LOG_LEVELS, logLevelClass, logTimeMs, formatClock, type LogEntry } from '../lib/net';

  let entries: LogEntry[] = [];
  let loading = true;
  let error = '';
  let query = '';
  let maxLevel = 7; // 7=all, 4=warnings+, 3=errors only
  let follow = true;
  let copied = false;
  let listEl: HTMLDivElement;
  let timer: ReturnType<typeof setInterval> | undefined;

  async function load() {
    try {
      entries = await getLog(300);
      error = '';
      if (follow) { await tick(); listEl?.scrollTo({ top: listEl.scrollHeight }); }
    } catch {
      error = 'Could not read the system log from the router.';
    } finally {
      loading = false;
    }
  }

  $: filtered = entries.filter(
    (e) => e.priority <= maxLevel && (!query || e.msg.toLowerCase().includes(query.toLowerCase()))
  );

  async function copyVisible() {
    const text = filtered.map((e) => `${formatClock(logTimeMs(e.time))} ${LOG_LEVELS[e.priority] ?? ''} ${e.msg}`).join('\n');
    try {
      await navigator.clipboard.writeText(text);
      copied = true;
      setTimeout(() => (copied = false), 1500);
    } catch { /* clipboard blocked */ }
  }

  onMount(() => {
    load();
    timer = setInterval(() => { if (follow) load(); }, 3000);
  });
  onDestroy(() => clearInterval(timer));
</script>

<div class="page-head">
  <div>
    <div class="breadcrumb">Advanced Settings</div>
    <h1>System Log</h1>
    <p>Live kernel and system messages from the router (<code>logread</code> over ubus).</p>
  </div>
</div>

<div class="panel">
  <div class="panel-h" style="flex-wrap:wrap;gap:12px">
    <h2>Log</h2>
    <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-left:auto">
      <input type="text" bind:value={query} placeholder="Filter messages…" style="min-width:180px" />
      <select bind:value={maxLevel}>
        <option value={7}>All levels</option>
        <option value={4}>Warnings &amp; errors</option>
        <option value={3}>Errors only</option>
      </select>
      <label class="followlbl"><input type="checkbox" bind:checked={follow} /> Follow</label>
      <button class="btn" on:click={load}>Refresh</button>
      <button class="btn" on:click={copyVisible}>{copied ? 'Copied' : 'Copy'}</button>
    </div>
  </div>

  {#if loading}
    <div class="panel-b" style="color:var(--muted);text-align:center;padding:40px">Reading log…</div>
  {:else if error}
    <div class="panel-b" style="color:var(--crit)">{error}</div>
  {:else}
    <div class="logbox" bind:this={listEl}>
      {#each filtered as e}
        <div class="logrow">
          <span class="lt mono">{formatClock(logTimeMs(e.time))}</span>
          <span class="lvchip {logLevelClass(e.priority)}">{LOG_LEVELS[e.priority] ?? '—'}</span>
          <span class="lm mono">{e.msg}</span>
        </div>
      {/each}
      {#if !filtered.length}
        <div class="logrow" style="color:var(--muted)">No messages match.</div>
      {/if}
    </div>
    <div class="panel-b" style="padding:10px 16px;border-top:1px solid var(--line-soft)">
      <span class="hint">{filtered.length} of {entries.length} lines{follow ? ' · following' : ''}</span>
    </div>
  {/if}
</div>

<style>
  .followlbl { display:flex; align-items:center; gap:6px; font-size:12.5px; color:var(--ink-dim); }
</style>
