<script lang="ts">
  import { onMount } from 'svelte';
  import Help from '../components/Help.svelte';
  import {
    loadDdns, setDdnsEnabled, addDdns, deleteDdns,
    DDNS_PROVIDERS, type DdnsState
  } from '../lib/ddns';
  import { toast } from '../lib/toast';

  let state: DdnsState = { installed: false, services: [] };
  let loading = true;
  let error = '';
  let busy = false;

  let showAdd = false;
  let nProvider = DDNS_PROVIDERS[0].value;
  let nHost = '';
  let nUser = '';
  let nPass = '';

  async function load() {
    loading = true;
    try { state = await loadDdns(); error = ''; }
    catch { error = 'Could not read the DDNS configuration.'; }
    finally { loading = false; }
  }
  onMount(load);

  async function toggle(id: string, on: boolean) {
    busy = true;
    try { await setDdnsEnabled(id, on); toast(on ? 'DDNS enabled' : 'DDNS disabled'); await load(); }
    catch { toast('Could not change the DDNS entry'); await load(); }
    finally { busy = false; }
  }
  async function add() {
    if (!nHost.trim()) { toast('Enter the hostname to keep updated'); return; }
    busy = true;
    try {
      await addDdns({ name: nHost, provider: nProvider, hostname: nHost.trim(), username: nUser.trim(), password: nPass });
      toast('DDNS entry added');
      nHost = nUser = nPass = ''; showAdd = false;
      await load();
    } catch { toast('Could not add the DDNS entry'); }
    finally { busy = false; }
  }
  async function remove(id: string) {
    busy = true;
    try { await deleteDdns(id); toast('DDNS entry removed'); await load(); }
    catch { toast('Could not remove the entry'); }
    finally { busy = false; }
  }
  const providerLabel = (v: string) => DDNS_PROVIDERS.find((p) => p.value === v)?.label || v;
</script>

<div class="page-head"><div><div class="breadcrumb">Advanced Settings</div><h1>Dynamic DNS</h1><p>Reach your router by name even when your internet provider changes its IP address.</p></div></div>

{#if loading}
  <div class="panel"><div class="panel-b" style="color:var(--muted);text-align:center;padding:44px">Reading configuration…</div></div>
{:else if error}
  <div class="panel"><div class="panel-b" style="text-align:center;padding:40px"><p style="color:var(--crit);margin:0 0 14px">{error}</p><button class="btn primary" on:click={load}>Retry</button></div></div>
{:else if !state.installed}
  <div class="panel" style="max-width:720px"><div class="panel-b">
    <p style="margin:0 0 6px"><b>Dynamic DNS isn't installed yet.</b></p>
    <p class="hint" style="margin:0">Install the <span class="mono">ddns-scripts</span> package (Software screen or <span class="mono">opkg/apk</span>), then add a hostname here.</p>
  </div></div>
{:else}
  <div class="panel" style="max-width:720px;margin-bottom:16px">
    <div class="panel-h"><h2>Hostnames</h2><span class="sub">{state.services.length} configured</span></div>
    <div class="panel-b">
      {#each state.services as s (s.id)}
        <div class="form-row">
          <div class="lbl"><b>{s.hostname || s.name}</b><small style="display:block;color:var(--muted)">{providerLabel(s.provider)}{s.username ? ' · ' + s.username : ''}</small></div>
          <div class="ctl" style="gap:12px">
            <label class="toggle"><input type="checkbox" checked={s.enabled} on:change={(e) => toggle(s.id, e.currentTarget.checked)} disabled={busy} /><span class="track"></span><span class="knob"></span></label>
            <button class="btn" on:click={() => remove(s.id)} disabled={busy}>Remove</button>
          </div>
        </div>
      {/each}
      {#if !state.services.length}
        <p class="hint" style="margin:0 0 4px">No hostnames yet. Add one below.</p>
      {/if}
    </div>
  </div>

  {#if showAdd}
    <div class="panel" style="max-width:720px"><div class="panel-h"><h2>Add a hostname</h2></div><div class="panel-b">
      <div class="form-row"><div class="lbl">Provider<Help text="The DDNS service you have an account with. Create the free account on their site first." /></div>
        <div class="ctl"><select bind:value={nProvider}>{#each DDNS_PROVIDERS as p}<option value={p.value}>{p.label}</option>{/each}</select></div></div>
      <div class="form-row"><div class="lbl">Hostname<Help text="The full name you'll use to reach your network, e.g. myhome.duckdns.org." /></div>
        <div class="ctl"><input type="text" bind:value={nHost} placeholder="myhome.duckdns.org" spellcheck="false" style="min-width:240px" /></div></div>
      <div class="form-row"><div class="lbl">Username<Help text="For most providers this is your account name; some (like DuckDNS) leave it blank and use only a token." /></div>
        <div class="ctl"><input type="text" bind:value={nUser} spellcheck="false" style="min-width:200px" /></div></div>
      <div class="form-row"><div class="lbl">Password / token<Help text="The account password or API token from the provider. It's stored on the router only." /></div>
        <div class="ctl"><input type="password" bind:value={nPass} style="min-width:200px" /></div></div>
      <div class="form-actions"><button class="btn" on:click={() => (showAdd = false)}>Cancel</button><button class="btn primary" on:click={add} disabled={busy}>{busy ? 'Adding…' : 'Add hostname'}</button></div>
    </div></div>
  {:else}
    <button class="btn primary" on:click={() => (showAdd = true)}>Add a hostname</button>
  {/if}

  <details class="adv" style="max-width:720px;margin-top:16px"><summary>Advanced details</summary><div class="advb">Each hostname is a <span class="mono">config service</span> in <span class="mono">/etc/config/ddns</span> (ddns-scripts), checking the <span class="mono">wan</span> address every 10 minutes over HTTPS and updating the provider when it changes.</div></details>
{/if}
