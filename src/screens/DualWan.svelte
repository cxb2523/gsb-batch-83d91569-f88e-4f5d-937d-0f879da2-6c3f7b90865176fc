<script lang="ts">
  import { onMount } from 'svelte';
  import Help from '../components/Help.svelte';
  import { loadDualWan, saveDualWan, type DualWanState, type DualMode } from '../lib/dualwan';
  import { toast } from '../lib/toast';

  let state: DualWanState | null = null;
  let loading = true;
  let error = '';
  let busy = false;

  async function load() {
    loading = true;
    try { state = await loadDualWan(); error = ''; }
    catch { error = 'Could not read the network configuration.'; }
    finally { loading = false; }
  }
  onMount(load);

  async function apply() {
    if (!state) return;
    if (state.mode !== 'off') {
      if (!state.primary || !state.backup) { toast('Pick both a primary and a backup connection'); return; }
      if (state.primary === state.backup) { toast('Primary and backup must be different'); return; }
    }
    busy = true;
    try {
      await saveDualWan(state.mode, state.primary, state.backup);
      toast(state.mode === 'off' ? 'Dual WAN turned off' : 'Dual WAN applied');
      await load();
    } catch { toast('Could not apply Dual WAN settings'); }
    finally { busy = false; }
  }
</script>

<div class="page-head"><div><div class="breadcrumb">Advanced Settings</div><h1>Dual WAN</h1><p>Use a second internet connection for automatic backup, or share the load across both.</p></div></div>

{#if loading}
  <div class="panel"><div class="panel-b" style="color:var(--muted);text-align:center;padding:44px">Reading configuration…</div></div>
{:else if error || !state}
  <div class="panel"><div class="panel-b" style="text-align:center;padding:40px"><p style="color:var(--crit);margin:0 0 14px">{error}</p><button class="btn primary" on:click={load}>Retry</button></div></div>
{:else if !state.installed}
  <div class="panel" style="max-width:720px"><div class="panel-b">
    <p style="margin:0 0 6px"><b>Dual WAN isn't installed yet.</b></p>
    <p class="hint" style="margin:0">Install the <span class="mono">mwan3</span> package (Software screen or <span class="mono">opkg/apk</span>), then set it up here.</p>
  </div></div>
{:else}
  <div class="panel" style="max-width:720px"><div class="panel-b">
    <div class="form-row"><div class="lbl">Mode<Help text="Failover: use the backup only when the primary goes down. Load balance: use both at once, spreading connections across them. Off: single connection as normal." /></div>
      <div class="ctl"><select bind:value={state.mode}>
        <option value="off">Off (single connection)</option>
        <option value="failover">Failover (backup kicks in)</option>
        <option value="balance">Load balance (use both)</option>
      </select></div></div>

    {#if state.mode !== 'off'}
      <div class="form-row"><div class="lbl">{state.mode === 'balance' ? 'First connection' : 'Primary'}<Help text="The connection used first. Health is checked by pinging 8.8.8.8 and 1.1.1.1." /></div>
        <div class="ctl"><select bind:value={state.primary}>{#each state.candidates as c}<option value={c.name}>{c.name} ({c.proto})</option>{/each}</select></div></div>
      <div class="form-row"><div class="lbl">{state.mode === 'balance' ? 'Second connection' : 'Backup'}<Help text="The other connection. In failover it's used only when the primary fails; in load balance it carries traffic too." /></div>
        <div class="ctl"><select bind:value={state.backup}>{#each state.candidates as c}<option value={c.name}>{c.name} ({c.proto})</option>{/each}</select></div></div>
    {/if}

    {#if state.candidates.length < 2}
      <p class="hint" style="margin:0 0 4px">Only one internet-type interface is configured. Add a second WAN (for example a USB modem or a second port) on the Internet screen first.</p>
    {/if}

    <div class="form-actions"><button class="btn primary" on:click={apply} disabled={busy}>{busy ? 'Applying…' : 'Apply'}</button></div>
  </div></div>
  <details class="adv" style="max-width:720px"><summary>Advanced details</summary><div class="advb">Writes a clean <span class="mono">mwan3</span> config in <span class="mono">/etc/config/mwan3</span>: two tracked <span class="mono">interface</span>s (ping health check), two <span class="mono">member</span>s (equal metric = balance, stepped = failover), one <span class="mono">policy</span> and a catch-all <span class="mono">rule</span>. Applying rewrites these sections.</div></details>
{/if}
