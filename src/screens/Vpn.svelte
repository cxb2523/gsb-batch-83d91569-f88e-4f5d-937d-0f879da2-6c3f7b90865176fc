<script lang="ts">
  import { onMount } from 'svelte';
  import Help from '../components/Help.svelte';
  import Icon from '../components/Icon.svelte';
  import {
    loadVpn, setWgEnabled, addPeer, deletePeer,
    setOvpnEnabled, deleteOvpn, addOvpnClient, addWgClient,
    type VpnState, type WgIface
  } from '../lib/vpn';
  import { toast } from '../lib/toast';

  let state: VpnState = { wg: [], ovpn: [] };
  let loading = true;
  let error = '';
  let busy = false;

  let section: 'server' | 'client' = 'server';
  let serverProto: 'wireguard' | 'openvpn' = 'wireguard';

  // add WireGuard peer (server)
  let addingFor = '';
  let pName = '', pKey = '', pIp = '';

  // add client connection
  let cName = '';
  let cType: 'ovpn' | 'wg' = 'ovpn';
  let cConfig = '';

  async function load() {
    loading = true;
    try { state = await loadVpn(); error = ''; }
    catch { error = 'Could not read the VPN configuration.'; }
    finally { loading = false; }
  }
  onMount(load);

  $: serverWg = state.wg.filter((w) => w.role !== 'client');
  $: serverOvpn = state.ovpn.filter((o) => o.role !== 'client');
  $: clientWg = state.wg.filter((w) => w.role === 'client');
  $: clientOvpn = state.ovpn.filter((o) => o.role === 'client');

  async function wrap(fn: () => Promise<void>, ok: string) {
    busy = true;
    try { await fn(); toast(ok); await load(); }
    catch { toast('Something went wrong'); }
    finally { busy = false; }
  }

  async function addWgPeer(w: WgIface) {
    if (!pKey) { toast('Paste the device public key'); return; }
    await wrap(() => addPeer(w.name, pName || 'Device', pKey, pIp || '10.0.0.2/32'), 'Device added');
    addingFor = ''; pName = pKey = pIp = '';
  }
  async function addClient() {
    if (!cConfig.trim()) { toast('Paste or import a config'); return; }
    const name = cName || 'VPN connection';
    await wrap(
      () => (cType === 'ovpn' ? addOvpnClient(name, cConfig) : addWgClient(name, cConfig)),
      'Connection added'
    );
    cName = ''; cConfig = '';
  }
  function onFile(e: Event) {
    const f = (e.target as HTMLInputElement).files?.[0];
    if (!f) return;
    const r = new FileReader();
    r.onload = () => { cConfig = String(r.result ?? ''); if (!cName) cName = f.name.replace(/\.(ovpn|conf)$/i, ''); };
    r.readAsText(f);
  }
</script>

<div class="page-head"><div><div class="breadcrumb">Advanced Settings</div><h1>VPN</h1><p>Let devices reach home (server), or route this router out through a provider (client).</p></div></div>

{#if loading}
  <div class="panel"><div class="panel-b" style="color:var(--muted);text-align:center;padding:44px">Reading configuration…</div></div>
{:else if error}
  <div class="panel"><div class="panel-b" style="text-align:center;padding:40px"><p style="color:var(--crit);margin:0 0 14px">{error}</p><button class="btn primary" on:click={load}>Retry</button></div></div>
{:else}
  <div class="seg">
    <button class:active={section === 'server'} on:click={() => (section = 'server')}>Server · let devices in</button>
    <button class:active={section === 'client'} on:click={() => (section = 'client')}>Client · connect out</button>
  </div>

  {#if section === 'server'}
    <div class="seg" style="margin-bottom:16px">
      <button class:active={serverProto === 'wireguard'} on:click={() => (serverProto = 'wireguard')}>WireGuard</button>
      <button class:active={serverProto === 'openvpn'} on:click={() => (serverProto = 'openvpn')}>OpenVPN</button>
    </div>

    {#if serverProto === 'wireguard'}
      {#if !serverWg.length}
        <div class="panel"><div class="panel-b"><p class="hint" style="margin:0">No WireGuard server yet. To set one up: on the router create an interface with <span class="mono">proto 'wireguard'</span> and a listen port (needs <span class="mono">wireguard-tools</span>) — then your devices appear here to add by public key. A guided "create server" step is coming soon.</p></div></div>
      {/if}
      {#each serverWg as w}
        <div class="panel" style="max-width:780px;margin-bottom:16px">
          <div class="panel-h"><h2>{w.name}</h2><span class="sub">{w.addresses.join(', ') || 'no address'} · udp/{w.listenPort || '?'}</span></div>
          <div class="panel-b">
            <div class="form-row"><div class="lbl">Enabled</div><div class="ctl"><label class="toggle"><input type="checkbox" checked={!w.disabled} on:change={(e) => wrap(() => setWgEnabled(w.id, e.currentTarget.checked), 'Saved')} disabled={busy} /><span class="track"></span><span class="knob"></span></label></div></div>
            {#each w.peers as p}
              <div class="devrow2" style="cursor:default"><span class="ic"><Icon name="d-phone" size={18} /></span><span class="dn"><b>{p.description || 'Device'}</b><small>{p.allowedIps.join(', ')} · {p.publicKey.slice(0, 16)}…</small></span><button class="btn" style="padding:6px 12px" on:click={() => wrap(() => deletePeer(p.id), 'Removed')} disabled={busy}>Remove</button></div>
            {/each}
            {#if !w.peers.length}<p class="hint" style="padding:4px 0">No devices yet.</p>{/if}
            {#if addingFor === w.id}
              <div style="border-top:1px solid var(--line-soft);margin-top:12px;padding-top:14px">
                <div class="form-row"><div class="lbl">Device name</div><div class="ctl"><input type="text" bind:value={pName} placeholder="My phone" /></div></div>
                <div class="form-row"><div class="lbl">Public key<Help text="Generate a key pair in the WireGuard app on the device, then paste its PUBLIC key here." /></div><div class="ctl"><input type="text" bind:value={pKey} placeholder="base64 public key" style="min-width:260px" /></div></div>
                <div class="form-row"><div class="lbl">Allowed address<Help text="The VPN address this device uses, e.g. 10.0.0.2/32." /></div><div class="ctl"><input type="text" bind:value={pIp} placeholder="10.0.0.2/32" /></div></div>
                <div class="form-actions"><button class="btn" on:click={() => (addingFor = '')}>Cancel</button><button class="btn primary" on:click={() => addWgPeer(w)} disabled={busy}>Add device</button></div>
              </div>
            {:else}
              <div class="form-actions"><button class="btn primary" on:click={() => (addingFor = w.id)}>Add a device</button></div>
            {/if}
          </div>
        </div>
      {/each}
    {:else}
      {#if !serverOvpn.length}
        <div class="panel"><div class="panel-b"><p class="hint" style="margin:0">No OpenVPN server instance found. OpenVPN servers need certificates (PKI) to set up; once an instance exists in <span class="mono">/etc/config/openvpn</span> it appears here to enable/disable.</p></div></div>
      {/if}
      {#each serverOvpn as o}
        <div class="panel" style="max-width:780px;margin-bottom:16px"><div class="panel-b" style="display:flex;align-items:center;gap:14px">
          <div class="devicon"><Icon name="i-vpn" size={22} /></div>
          <div style="flex:1"><b>{o.name}</b><div class="hint">OpenVPN · {o.role}</div></div>
          <label class="toggle"><input type="checkbox" checked={o.enabled} on:change={(e) => wrap(() => setOvpnEnabled(o.id, e.currentTarget.checked), 'Saved')} disabled={busy} /><span class="track"></span><span class="knob"></span></label>
          <button class="btn" style="padding:6px 12px" on:click={() => wrap(() => deleteOvpn(o.id), 'Removed')} disabled={busy}>Remove</button>
        </div></div>
      {/each}
    {/if}
  {:else}
    <!-- CLIENT -->
    {#each [...clientWg.map((w) => ({ kind: 'wg', id: w.id, name: w.name, sub: 'WireGuard · ' + (w.disabled ? 'off' : 'on'), enabled: !w.disabled })), ...clientOvpn.map((o) => ({ kind: 'ovpn', id: o.id, name: o.name, sub: 'OpenVPN · ' + (o.enabled ? 'on' : 'off'), enabled: o.enabled }))] as c}
      <div class="devrow2" style="cursor:default;max-width:780px">
        <span class="ic"><Icon name="i-vpn" size={18} /></span>
        <span class="dn"><b>{c.name}</b><small>{c.sub}</small></span>
        <label class="toggle"><input type="checkbox" checked={c.enabled}
          on:change={(e) => wrap(() => c.kind === 'wg' ? setWgEnabled(c.id, e.currentTarget.checked) : setOvpnEnabled(c.id, e.currentTarget.checked), e.currentTarget.checked ? 'Connected' : 'Disconnected')} disabled={busy} /><span class="track"></span><span class="knob"></span></label>
        <button class="btn" style="padding:6px 12px;margin-left:8px" on:click={() => wrap(() => c.kind === 'wg' ? deletePeer(c.id) : deleteOvpn(c.id), 'Removed')} disabled={busy}>Remove</button>
      </div>
    {/each}
    {#if !clientWg.length && !clientOvpn.length}
      <p class="hint" style="max-width:780px">No outbound VPN connections yet. Add one below to route this router's traffic through a provider.</p>
    {/if}

    <div class="panel" style="max-width:780px;margin-top:16px">
      <div class="panel-h"><h2>Add a connection</h2></div>
      <div class="panel-b">
        <div class="form-row"><div class="lbl">Name</div><div class="ctl"><input type="text" bind:value={cName} placeholder="e.g. Office VPN" /></div></div>
        <div class="form-row"><div class="lbl">Type</div><div class="ctl"><select bind:value={cType}><option value="ovpn">OpenVPN (.ovpn)</option><option value="wg">WireGuard config</option></select></div></div>
        <div class="form-row"><div class="lbl">Config<Help text="Import the file your provider gave you (.ovpn), or paste a WireGuard config. The private key stays on the router." /></div>
          <div class="ctl"><label class="btn" style="cursor:pointer">Import file<input type="file" accept=".ovpn,.conf,.txt" on:change={onFile} style="display:none" /></label><span class="hint">or paste below</span></div></div>
        <textarea bind:value={cConfig} rows="5" placeholder={cType === 'ovpn' ? 'client\\ndev tun\\nremote vpn.example.com 1194\\n…' : '[Interface]\\nPrivateKey = …\\nAddress = 10.0.0.2/32\\n[Peer]\\nPublicKey = …\\nEndpoint = vpn.example.com:51820\\nAllowedIPs = 0.0.0.0/0'} style="width:100%;font-family:var(--font-mono);font-size:12px;background:var(--panel-2);border:1px solid var(--line);border-radius:10px;padding:12px;color:var(--ink);resize:vertical"></textarea>
        <div class="form-actions"><button class="btn primary" on:click={addClient} disabled={busy}>Add connection</button></div>
      </div>
    </div>
  {/if}

  <details class="adv" style="max-width:780px;margin-top:4px"><summary>Advanced details</summary><div class="advb">WireGuard interfaces/peers live in <span class="mono">/etc/config/network</span>; a peer with an <span class="mono">endpoint</span> is a client (dials out). OpenVPN instances live in <span class="mono">/etc/config/openvpn</span>; importing a client writes the <span class="mono">.ovpn</span> to <span class="mono">/etc/openvpn/</span> and points an instance at it.</div></details>
{/if}
