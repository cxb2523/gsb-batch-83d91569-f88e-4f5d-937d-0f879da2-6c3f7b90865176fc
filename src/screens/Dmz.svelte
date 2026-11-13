<script lang="ts">
  import { onMount } from 'svelte';
  import Help from '../components/Help.svelte';
  import Icon from '../components/Icon.svelte';
  import { loadDmz, setDmz, clearDmz, type DmzState } from '../lib/firewall';
  import { getClients, type Client } from '../lib/net';
  import { toast } from '../lib/toast';
  import { startRollbackConfirm } from '../lib/confirm';

  let state: DmzState = { enabled: false, host: '', redirectId: null };
  let clients: Client[] = [];
  let host = '';
  let loading = true;
  let error = '';
  let busy = false;

  async function load() {
    loading = true;
    try {
      [state, clients] = await Promise.all([loadDmz(), getClients().catch(() => [])]);
      host = state.host || '';
      error = '';
    } catch {
      error = 'Could not read the firewall configuration.';
    } finally {
      loading = false;
    }
  }
  onMount(load);

  async function enable() {
    if (!host) { toast('Choose a device or enter an IP first'); return; }
    busy = true;
    try {
      await setDmz(host);
      startRollbackConfirm('DMZ for ' + host, { onKeep: load, onRevert: load });
    } catch {
      toast('Could not enable DMZ');
    } finally {
      busy = false;
    }
  }
  async function disable() {
    busy = true;
    try {
      await clearDmz();
      toast('DMZ disabled');
      await load();
    } catch {
      toast('Could not disable DMZ');
    } finally {
      busy = false;
    }
  }
</script>

<div class="page-head">
  <div><div class="breadcrumb">Advanced Settings</div><h1>DMZ</h1><p>Expose a single device directly to the internet. Use only when you understand the risk.</p></div>
</div>

{#if loading}
  <div class="panel"><div class="panel-b" style="color:var(--muted);text-align:center;padding:44px">Reading configuration…</div></div>
{:else if error}
  <div class="panel"><div class="panel-b" style="text-align:center;padding:40px"><p style="color:var(--crit);margin:0 0 14px">{error}</p><button class="btn primary" on:click={load}>Retry</button></div></div>
{:else}
  <div class="panel" style="max-width:720px">
    <div class="panel-b">
      <div class="caution">
        <Icon name="i-shield" size={20} />
        <span><b>This removes the firewall's protection for one device.</b> Every port reaches it from the internet. Only use it for a device you intend to expose (a dedicated server), and prefer Port Forwarding for a single app.</span>
      </div>

      {#if state.enabled}
        <div class="form-row"><div class="lbl">Status</div><div class="ctl"><span class="pill"><span class="dot"></span> DMZ active → <span class="mono" style="margin-left:4px">{state.host}</span></span></div></div>
        <div class="form-actions" style="border:0"><button class="btn" on:click={disable} disabled={busy}>Turn off DMZ</button></div>
      {:else}
        <div class="form-row">
          <div class="lbl">Exposed device<Help text="All inbound internet traffic is forwarded to this device. It should have a fixed local address." /></div>
          <div class="ctl">
            <select bind:value={host}>
              <option value="">Choose a device…</option>
              {#each clients as c}<option value={c.ip}>{c.name} ({c.ip})</option>{/each}
            </select>
            <span class="hint">or</span>
            <input type="text" bind:value={host} placeholder="192.168.1.x" style="min-width:150px" />
          </div>
        </div>
        <div class="form-actions" style="border:0"><button class="btn primary" on:click={enable} disabled={busy}>{busy ? 'Applying…' : 'Enable DMZ'}</button></div>
      {/if}
    </div>
  </div>
  <details class="adv" style="max-width:720px"><summary>Advanced details</summary><div class="advb">DMZ is a <span class="mono">config redirect</span> named <span class="mono">DMZ</span> in <span class="mono">/etc/config/firewall</span>: a full DNAT from <span class="mono">src 'wan'</span>, <span class="mono">proto 'all'</span> to the chosen <span class="mono">dest_ip</span>. Disabling removes that redirect.</div></details>
{/if}
