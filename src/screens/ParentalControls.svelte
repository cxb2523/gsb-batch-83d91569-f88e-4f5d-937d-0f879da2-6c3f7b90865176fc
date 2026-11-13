<script lang="ts">
  import { onMount } from 'svelte';
  import Help from '../components/Help.svelte';
  import Icon from '../components/Icon.svelte';
  import { getClients, type Client } from '../lib/net';
  import { loadParental, pauseDevice, scheduleDevice, clearDevice, WEEKDAYS, type ParentalRule } from '../lib/parental';
  import { toast } from '../lib/toast';

  let clients: Client[] = [];
  let rules: Record<string, ParentalRule> = {};
  let loading = true;
  let error = '';
  let busy = false;
  let selId = '';
  let days: string[] = [...WEEKDAYS];
  let from = '20:00';
  let to = '22:00';

  async function loadAll() {
    loading = true;
    try {
      [clients, rules] = await Promise.all([getClients().catch(() => []), loadParental()]);
      if (!selId && clients[0]) select(clients[0]);
      error = '';
    } catch {
      error = 'Could not read configuration.';
    } finally {
      loading = false;
    }
  }
  async function refresh() { rules = await loadParental(); }
  onMount(loadAll);

  function select(c: Client) {
    selId = c.id;
    const r = rules[c.mac];
    if (r && r.mode === 'scheduled') { days = r.days.length ? [...r.days] : [...WEEKDAYS]; from = r.from; to = r.to; }
    else { days = [...WEEKDAYS]; from = '20:00'; to = '22:00'; }
  }
  $: sel = clients.find((c) => c.id === selId) || null;
  $: selRule = sel ? rules[sel.mac] : undefined;

  // Show devices you've acted on first: paused/scheduled jump to the top of the
  // list so an applied limit is immediately visible.
  function ruleRank(c: Client): number {
    const r = rules[c.mac];
    if (!r || r.mode === 'off') return 2;
    if (r.mode === 'paused') return 0;
    return 1; // scheduled
  }
  $: sortedClients = [...clients].sort(
    (a, b) => ruleRank(a) - ruleRank(b) || a.name.localeCompare(b.name)
  );

  function status(c: Client): [string, string] {
    const r = rules[c.mac];
    if (!r || r.mode === 'off') return ['Allowed', 'st-ok'];
    if (r.mode === 'paused') return ['Paused', 'st-paused'];
    return ['Scheduled', 'st-sched'];
  }
  function toggleDay(d: string) { days = days.includes(d) ? days.filter((x) => x !== d) : [...days, d]; }

  async function pause() {
    if (!sel) return; busy = true;
    try { await pauseDevice(sel.mac, sel.name, selRule?.id ?? null); toast('Paused ' + sel.name); await refresh(); }
    catch { toast('Could not pause'); } finally { busy = false; }
  }
  async function resume() {
    if (!selRule) return; busy = true;
    try { await clearDevice(selRule.id); toast('Resumed'); await refresh(); }
    catch { toast('Failed'); } finally { busy = false; }
  }
  async function saveSchedule() {
    if (!sel) return; busy = true;
    try { await scheduleDevice(sel.mac, sel.name, days, from, to, selRule?.id ?? null); toast('Schedule saved'); await refresh(); }
    catch { toast('Failed'); } finally { busy = false; }
  }
  async function removeLimits() {
    if (!selRule) return; busy = true;
    try { await clearDevice(selRule.id); toast('Limits removed'); await refresh(); }
    catch { toast('Failed'); } finally { busy = false; }
  }
</script>

<div class="page-head">
  <div><div class="breadcrumb">General</div><h1>Parental Controls</h1><p>Pause the internet or set allowed hours for a device. Changes take effect immediately.</p></div>
</div>

{#if loading}
  <div class="panel"><div class="panel-b" style="color:var(--muted);text-align:center;padding:44px">Reading configuration…</div></div>
{:else if error}
  <div class="panel"><div class="panel-b" style="text-align:center;padding:40px"><p style="color:var(--crit);margin:0 0 14px">{error}</p><button class="btn primary" on:click={loadAll}>Retry</button></div></div>
{:else}
  <div class="pc-grid">
    <div class="panel">
      <div class="panel-h"><h2>Devices</h2><span class="sub">{clients.length}</span></div>
      <div class="panel-b devlist">
        {#each sortedClients as c}
          {@const st = status(c)}
          <button class="devrow2" class:sel={c.id === selId} on:click={() => select(c)}>
            <span class="ic"><Icon name={c.kind} size={18} /></span>
            <span class="dn"><b>{c.name}</b><small>{c.ip}</small></span>
            <span class="statechip {st[1]}">{st[0]}</span>
          </button>
        {/each}
        {#if !clients.length}<p class="hint">No devices seen yet.</p>{/if}
      </div>
    </div>

    <div class="panel">
      <div class="panel-b">
        {#if sel}
          <div class="detail big" style="display:flex;gap:13px;align-items:center;padding-bottom:16px;border-bottom:1px solid var(--line-soft);margin-bottom:6px">
            <div class="devicon"><Icon name={sel.kind} size={24} /></div>
            <div><b style="font-size:15px">{sel.name}</b><div class="hint mono">{sel.mac} · {sel.ip}</div></div>
            {#if selRule && selRule.mode === 'paused'}
              <button class="btn" style="margin-left:auto" on:click={resume} disabled={busy}>Resume internet</button>
            {:else}
              <button class="btn primary" style="margin-left:auto" on:click={pause} disabled={busy}>Pause internet now</button>
            {/if}
          </div>

          <div class="form-row"><div class="lbl">Blocked days<Help text="Days the block applies. All selected = every day." /></div>
            <div class="ctl"><div class="days">{#each WEEKDAYS as d}<button class="day" class:on={days.includes(d)} on:click={() => toggleDay(d)}>{d}</button>{/each}</div></div>
          </div>
          <div class="form-row"><div class="lbl">Blocked hours<Help text="The device can't reach the internet between these times, on the selected days. Use a same-day window (start before end)." /></div>
            <div class="ctl"><input type="time" bind:value={from} /> <span class="hint">to</span> <input type="time" bind:value={to} /></div>
          </div>
          {#if days.length === 0}<p class="hint" style="color:var(--warn);margin:4px 0 0">Select at least one day for the schedule to apply.</p>{/if}
          <div class="form-actions">
            {#if selRule}<button class="btn" on:click={removeLimits} disabled={busy}>Remove all limits</button>{/if}
            <button class="btn primary" on:click={saveSchedule} disabled={busy || days.length === 0}>Save schedule</button>
          </div>
        {:else}
          <p class="hint">Select a device.</p>
        {/if}
      </div>
    </div>
  </div>
  <details class="adv" style="margin-top:18px"><summary>Advanced details</summary><div class="advb">Each limit is a firewall <span class="mono">rule</span> (<span class="mono">src lan → dest wan</span>, matched by the device's MAC, target REJECT). "Pause" is an always-on rule; a schedule adds <span class="mono">weekdays</span> + <span class="mono">start_time</span>/<span class="mono">stop_time</span>. Per-site content filtering needs a DNS filter (adblock) and is separate.</div></details>
{/if}
