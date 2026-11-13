<script lang="ts">
  import { onMount } from 'svelte';
  import Help from '../components/Help.svelte';
  import Icon from '../components/Icon.svelte';
  import { loadTailscale, tailscaleUp, tailscaleDown, type TsStatus } from '../lib/tailscale';
  import { toast } from '../lib/toast';

  let st: TsStatus = { installed: false, reason: '', state: 'unknown', selfIp: '', selfName: '', tailnet: '', peers: [], authUrl: null };
  let loading = true;
  let busy = false;
  let authUrl = '';

  async function load() {
    loading = true;
    try { st = await loadTailscale(); authUrl = st.authUrl ?? ''; }
    finally { loading = false; }
  }
  onMount(load);

  async function connect() {
    busy = true;
    try {
      const r = await tailscaleUp();
      if (r.authUrl) { authUrl = r.authUrl; toast('Open the login link to finish connecting'); }
      else { toast('Tailscale connecting…'); }
      await load();
    } catch { toast('Could not start Tailscale'); }
    finally { busy = false; }
  }
  async function disconnect() {
    busy = true;
    try { await tailscaleDown(); toast('Tailscale disconnected'); await load(); }
    catch { toast('Could not stop Tailscale'); }
    finally { busy = false; }
  }
  function copy(text: string) {
    navigator.clipboard?.writeText(text).then(() => toast('Copied'), () => {});
  }

  const stateLabel: Record<TsStatus['state'], string> = {
    running: 'Connected', stopped: 'Disconnected', needslogin: 'Needs login', unknown: 'Unknown'
  };
  const stateClass: Record<TsStatus['state'], string> = {
    running: 'ok', stopped: 'off', needslogin: 'warn', unknown: 'off'
  };
</script>

<div class="page-head"><div>
  <div class="breadcrumb">Advanced Settings</div>
  <h1>Tailscale</h1>
  <p>A private mesh VPN. Reach the devices on this network from your phone or laptop anywhere, with no port forwarding.</p>
</div></div>

{#if loading}
  <div class="panel"><div class="panel-b" style="color:var(--muted);text-align:center;padding:44px">Reading…</div></div>
{:else if !st.installed}
  <div class="panel"><div class="panel-b">
    <div class="caution"><Icon name="i-vpn" size={20} /><span>Tailscale isn't available on this router. Install the <span class="mono">tailscale</span> package from the Software screen (or <span class="mono">opkg install tailscale</span> / <span class="mono">apk add tailscale</span>) and make sure the <span class="mono">tailscale</span> service is started.</span></div>
    {#if st.reason}<div class="hint mono" style="margin-top:10px;white-space:pre-wrap">{st.reason}</div>{/if}
  </div></div>
{:else}
  <div class="panel" style="margin-bottom:18px"><div class="panel-b" style="display:flex;align-items:center;gap:16px;flex-wrap:wrap">
    <div class="devicon" style="width:52px;height:52px"><Icon name="i-vpn" size={24} /></div>
    <div style="flex:1;min-width:200px">
      <div style="font-size:15px;font-weight:700;display:flex;align-items:center;gap:10px">
        Tailscale <span class="statechip {stateClass[st.state]}">{stateLabel[st.state]}</span>
      </div>
      <div class="hint mono">{st.selfIp || '—'}{#if st.tailnet} · {st.tailnet}{/if}</div>
    </div>
    {#if st.state === 'running'}
      <button class="btn" on:click={disconnect} disabled={busy}>Disconnect</button>
    {:else}
      <button class="btn primary" on:click={connect} disabled={busy}>Connect</button>
    {/if}
  </div></div>

  {#if authUrl}
    <div class="panel" style="margin-bottom:18px"><div class="panel-b">
      <div class="form-row"><div class="lbl">Finish login<Help text="Open this link in any browser and sign in to add this router to your Tailscale network. The router can't open a browser itself." /></div>
        <div class="ctl" style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
          <a href={authUrl} target="_blank" rel="noopener" class="mono" style="word-break:break-all">{authUrl}</a>
          <button class="btn sm" on:click={() => copy(authUrl)}>Copy</button>
        </div>
      </div>
    </div></div>
  {/if}

  <div class="panel">
    <div class="panel-h"><h2>Machines</h2><span class="sub">{st.peers.length}</span></div>
    <div style="overflow-x:auto"><table class="clients">
      <thead><tr><th>Machine</th><th>Tailscale IP</th><th>OS</th><th style="text-align:right">Status</th></tr></thead>
      <tbody>
        {#each st.peers as p}
          <tr style="cursor:default">
            <td><b style="font-weight:600">{p.name}</b>{#if p.self}<span class="appbadge">this router</span>{/if}</td>
            <td class="mono">{p.ip || '—'}</td>
            <td>{p.os || '—'}</td>
            <td style="text-align:right"><span class="statechip {p.online ? 'ok' : 'off'}">{p.online ? 'online' : 'offline'}</span></td>
          </tr>
        {/each}
        {#if !st.peers.length}<tr><td colspan="4" style="color:var(--muted);padding:22px">No machines yet. Connect this router, then add your other devices to the same Tailscale account.</td></tr>{/if}
      </tbody>
    </table></div>
  </div>

  <details class="adv" style="margin-top:18px"><summary>Advanced details</summary><div class="advb">
    Runs the <span class="mono">tailscale</span> CLI on the router. <b>Connect</b> runs <span class="mono">tailscale up --accept-routes</span>; first time it returns a <span class="mono">login.tailscale.com</span> URL to authorise this node. <b>Disconnect</b> runs <span class="mono">tailscale down</span>. Status comes from <span class="mono">tailscale status --json</span>. To advertise this LAN as a subnet route, run <span class="mono">tailscale up --advertise-routes=…</span> on the router and approve it in the Tailscale admin console.
  </div></details>
{/if}

<style>
  .statechip { font-size: 11px; font-weight: 700; padding: 3px 10px; border-radius: 999px; }
  .statechip.ok { background: rgba(23,178,106,.15); color: #0f7a4a; }
  .statechip.warn { background: rgba(247,144,9,.16); color: #b45309; }
  .statechip.off { background: var(--panel-2); color: var(--muted); }
  .appbadge { margin-left: 7px; font-size: 10px; font-weight: 700; letter-spacing: .3px; text-transform: uppercase; color: var(--accent-deep); background: rgba(15,181,196,.14); padding: 2px 7px; border-radius: 999px; }
  :root[data-theme="dark"] .statechip.ok { color: #36d67a; }
  :root[data-theme="dark"] .statechip.warn { color: #ffb02e; }
  .btn.sm { padding: 6px 10px; font-size: 12px; }
</style>
