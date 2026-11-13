<script lang="ts">
  import { onMount } from 'svelte';
  import Help from '../components/Help.svelte';
  import { loadUpnp, saveUpnp, type UpnpState } from '../lib/upnp';
  import { toast } from '../lib/toast';

  let state: UpnpState | null = null;
  let loading = true;
  let error = '';
  let busy = false;

  async function load() {
    loading = true;
    try { state = await loadUpnp(); error = ''; }
    catch { error = 'Could not read the UPnP configuration.'; }
    finally { loading = false; }
  }
  onMount(load);

  async function apply() {
    if (!state) return;
    busy = true;
    try { await saveUpnp(state); toast(state.enabled ? 'UPnP turned on' : 'UPnP turned off'); await load(); }
    catch { toast('Could not apply UPnP settings'); }
    finally { busy = false; }
  }
</script>

<div class="page-head"><div><div class="breadcrumb">Advanced Settings</div><h1>UPnP</h1><p>Let games and apps open the ports they need automatically — no manual port forwarding.</p></div></div>

{#if loading}
  <div class="panel"><div class="panel-b" style="color:var(--muted);text-align:center;padding:44px">Reading configuration…</div></div>
{:else if error || !state}
  <div class="panel"><div class="panel-b" style="text-align:center;padding:40px"><p style="color:var(--crit);margin:0 0 14px">{error}</p><button class="btn primary" on:click={load}>Retry</button></div></div>
{:else if !state.installed}
  <div class="panel" style="max-width:720px"><div class="panel-b">
    <p style="margin:0 0 6px"><b>UPnP isn't installed yet.</b></p>
    <p class="hint" style="margin:0">Install the <span class="mono">miniupnpd-nftables</span> package (Software screen or <span class="mono">opkg/apk</span>) — the nftables build is the one that works on OpenWRT 22.03+ — then enable it here.</p>
  </div></div>
{:else}
  <div class="panel" style="max-width:720px"><div class="panel-b">
    <div class="form-row"><div class="lbl">Allow automatic port opening<Help text="Lets consoles and apps (game chat, some video calls, torrents) request inbound ports on demand. Convenient, but any app on your network can open a port — leave off if you don't need it." /></div>
      <div class="ctl"><label class="toggle"><input type="checkbox" bind:checked={state.enabled} /><span class="track"></span><span class="knob"></span></label></div></div>
    {#if state.enabled}
      <div class="form-row"><div class="lbl">Secure mode<Help text="A device may only open ports to itself, not redirect traffic to other devices. Recommended — keep this on." /></div>
        <div class="ctl"><label class="toggle"><input type="checkbox" bind:checked={state.secure} /><span class="track"></span><span class="knob"></span></label></div></div>
    {/if}
    <div class="form-actions"><button class="btn primary" on:click={apply} disabled={busy}>{busy ? 'Applying…' : 'Apply'}</button></div>
  </div></div>
  <details class="adv" style="max-width:720px"><summary>Advanced details</summary><div class="advb">Toggles <span class="mono">miniupnpd-nftables</span> (UPnP IGD + NAT-PMP) via <span class="mono">/etc/config/upnpd</span>, listening on <span class="mono">lan</span> and mapping to <span class="mono">wan</span>. Active mappings appear as temporary entries in the firewall. <b>This is the modern replacement for old-style “port triggering,”</b> which current OpenWRT (nftables) doesn't support — for a fixed service, use Port Forwarding instead.</div></details>
{/if}
