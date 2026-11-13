<script lang="ts">
  import { onMount } from 'svelte';
  import Help from '../components/Help.svelte';
  import Icon from '../components/Icon.svelte';
  import {
    loadPortForwards, addPortForward, savePortForward, deletePortForward, type PortFwd
  } from '../lib/firewall';
  import { getWan, getClients, type Client } from '../lib/net';
  import { toast } from '../lib/toast';

  let rules: PortFwd[] = [];
  let wanIp = '';
  let clients: Client[] = [];
  let loading = true;
  let error = '';
  let busy = false;
  let adding = false;

  const PRESETS = [
    { id: 'game', label: 'Game console', port: '3074', proto: 'tcp udp' },
    { id: 'camera', label: 'Security camera', port: '8080', proto: 'tcp' },
    { id: 'web', label: 'Web server', port: '443', proto: 'tcp' },
    { id: 'remote', label: 'Remote desktop', port: '3389', proto: 'tcp' },
    { id: 'custom', label: 'Custom', port: '', proto: 'tcp' }
  ];
  let preset = 'game';
  let name = 'Game console';
  let proto = 'tcp udp';
  let port = '3074';
  let destIp = '';

  async function load() {
    loading = true;
    try {
      const [r, w, c] = await Promise.all([
        loadPortForwards(),
        getWan().catch(() => ({ ipv4: null }) as any),
        getClients().catch(() => [])
      ]);
      rules = r; wanIp = w?.ipv4 ?? ''; clients = c; error = '';
    } catch {
      error = 'Could not read the firewall configuration.';
    } finally {
      loading = false;
    }
  }
  onMount(load);

  function pickPreset(p: (typeof PRESETS)[number]) {
    preset = p.id;
    if (p.id !== 'custom') { name = p.label; proto = p.proto; port = p.port; }
  }
  const protoLabel = (p: string) => (p === 'tcp udp' ? 'TCP/UDP' : p.toUpperCase());
  const deviceName = (ip: string) => clients.find((c) => c.ip === ip)?.name ?? ip;

  async function add() {
    if (!destIp) { toast('Choose a device'); return; }
    if (!port) { toast('Enter a port'); return; }
    busy = true;
    try {
      await addPortForward({ name: name || 'Service', proto, port, destIp });
      toast('Opened access to ' + deviceName(destIp));
      adding = false; destIp = '';
      await load();
    } catch { toast('Could not open access'); }
    finally { busy = false; }
  }
  async function toggle(r: PortFwd) {
    busy = true;
    const want = !r.enabled;
    try { r.enabled = want; await savePortForward(r); rules = rules; toast(want ? 'Access opened' : 'Access paused'); }
    catch { r.enabled = !want; rules = rules; toast('Could not change access'); }
    finally { busy = false; }
  }
  async function remove(r: PortFwd) {
    busy = true;
    try { await deletePortForward(r.id); toast('Access removed'); await load(); }
    catch { toast('Could not remove'); }
    finally { busy = false; }
  }
</script>

<div class="page-head">
  <div><div class="breadcrumb">Advanced Settings</div><h1>Open access to a device</h1><p>Let people on the internet reach something in your home, like a game console, camera or server.</p></div>
  <button class="btn primary" on:click={() => (adding = !adding)}>+ Open access</button>
</div>

{#if loading}
  <div class="panel"><div class="panel-b" style="color:var(--muted);text-align:center;padding:44px">Reading configuration…</div></div>
{:else if error}
  <div class="panel"><div class="panel-b" style="text-align:center;padding:40px"><p style="color:var(--crit);margin:0 0 14px">{error}</p><button class="btn primary" on:click={load}>Retry</button></div></div>
{:else}
  {#if adding}
    <div class="panel" style="max-width:720px;margin-bottom:18px">
      <div class="panel-h"><h2>Open access</h2></div>
      <div class="panel-b">
        <p style="margin:0 0 10px;color:var(--ink-dim);font-size:13px">What do you want to open access to?</p>
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">
          {#each PRESETS as p}
            <button class="btn" style={preset === p.id ? 'border-color:var(--accent);background:var(--accent-soft);color:var(--accent-deep)' : ''} on:click={() => pickPreset(p)}>{p.label}</button>
          {/each}
        </div>
        <div class="form-row"><div class="lbl">Which device?<Help text="The device that receives the incoming connections. It should keep a fixed local address." /></div>
          <div class="ctl"><select bind:value={destIp}><option value="">Choose a device…</option>{#each clients as c}<option value={c.ip}>{c.name} ({c.ip})</option>{/each}</select>
            <span class="hint">or</span><input type="text" bind:value={destIp} placeholder="192.168.1.x" style="min-width:140px" /></div>
        </div>
        {#if preset === 'custom'}
          <div class="form-row"><div class="lbl">Port<Help text="The external port number people connect to (1–65535)." /></div><div class="ctl"><input type="text" bind:value={port} style="min-width:120px" /></div></div>
          <div class="form-row"><div class="lbl">Protocol<Help text="TCP suits most apps; UDP for some games/VoIP; TCP/UDP covers both." /></div>
            <div class="ctl"><select bind:value={proto}><option value="tcp">TCP</option><option value="udp">UDP</option><option value="tcp udp">TCP/UDP</option></select></div></div>
        {:else}
          <p class="hint" style="padding:4px 0 0">People will reach it at <b class="mono">{wanIp || 'your-wan-ip'}:{port}</b> ({protoLabel(proto)}).</p>
        {/if}
        <div class="form-actions"><button class="btn" on:click={() => (adding = false)}>Cancel</button><button class="btn primary" on:click={add} disabled={busy}>Open access</button></div>
      </div>
    </div>
  {/if}

  <div class="panel" style="max-width:840px">
    <div class="panel-b" style="padding:12px">
      {#each rules as r}
        <div class="devrow2" style="cursor:default">
          <span class="ic"><Icon name="i-port" size={20} /></span>
          <span class="dn"><b>{r.name || deviceName(r.destIp)}</b><small>reachable at {wanIp || 'your-wan-ip'}:{r.port} · {protoLabel(r.proto)} → {deviceName(r.destIp)}</small></span>
          <label class="toggle"><input type="checkbox" checked={r.enabled} on:change={() => toggle(r)} /><span class="track"></span><span class="knob"></span></label>
          <button class="btn" style="padding:6px 12px;margin-left:8px" on:click={() => remove(r)} disabled={busy}>Remove</button>
        </div>
      {/each}
      {#if !rules.length}
        <p class="hint" style="padding:16px;text-align:center">Nothing is open yet. Press “Open access” to let a device be reached from the internet.</p>
      {/if}
    </div>
  </div>
  <details class="adv" style="max-width:840px"><summary>Advanced details</summary><div class="advb">Each entry is a <span class="mono">config redirect</span> (DNAT) in <span class="mono">/etc/config/firewall</span>: <span class="mono">src 'wan'</span>, an external <span class="mono">src_dport</span>, forwarded to the device's <span class="mono">dest_ip</span>/<span class="mono">dest_port</span>. Presets fill the usual port and protocol; Custom sets them by hand.</div></details>
{/if}
