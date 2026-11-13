<script lang="ts">
  import { onMount } from 'svelte';
  import Help from '../components/Help.svelte';
  import Icon from '../components/Icon.svelte';
  import { bandName, bandClass } from '../lib/net';
  import {
    loadDevices, reserveIp, removeReservation, renameDevice, setBlocked, wake, type DeviceRow
  } from '../lib/devices';
  import { toast } from '../lib/toast';

  let rows: DeviceRow[] = [];
  let loading = true;
  let error = '';
  let busy = ''; // mac currently being acted on
  let editing = ''; // mac whose name is being edited
  let draftName = '';

  async function load() {
    loading = true;
    try { rows = await loadDevices(); error = ''; }
    catch { error = 'Could not read the device list from the router.'; }
    finally { loading = false; }
  }
  onMount(load);

  const IP_RE = /^((25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(25[0-5]|2[0-4]\d|1?\d?\d)$/;

  async function doReserve(r: DeviceRow) {
    const ip = (r.reservedIp ? r.draftIp : r.ip).trim();
    if (!IP_RE.test(ip)) { toast('Enter a valid IP address (e.g. 192.168.1.50)'); return; }
    busy = r.mac;
    try { await reserveIp(r.mac, ip, r.name, r.reserveId); toast(`Fixed IP ${ip} set for ${r.name}`); await load(); }
    catch { toast('Could not set the fixed IP'); }
    finally { busy = ''; }
  }
  async function doUnreserve(r: DeviceRow) {
    if (!r.reserveId) return;
    busy = r.mac;
    try { await removeReservation(r.reserveId); toast(`Fixed IP removed for ${r.name}`); await load(); }
    catch { toast('Could not remove the fixed IP'); }
    finally { busy = ''; }
  }
  async function toggleBlock(r: DeviceRow) {
    busy = r.mac;
    const next = !r.blocked;
    try {
      await setBlocked(r.mac, r.name, next, r.blockId);
      toast(next ? `${r.name} blocked from the internet` : `${r.name} unblocked`);
      await load();
    } catch { toast('Could not change the block setting'); }
    finally { busy = ''; }
  }
  async function doWake(r: DeviceRow) {
    busy = r.mac;
    try { await wake(r.mac); toast(`Wake signal sent to ${r.name}`); }
    catch { toast('Could not wake device — install the "etherwake" package'); }
    finally { busy = ''; }
  }
  function startRename(r: DeviceRow) { editing = r.mac; draftName = r.name === r.mac ? '' : r.name; }
  async function saveRename(r: DeviceRow) {
    busy = r.mac;
    try { await renameDevice(r.mac, draftName, r.reserveId); editing = ''; toast('Device renamed'); await load(); }
    catch { toast('Could not rename the device'); }
    finally { busy = ''; }
  }
</script>

<div class="page-head">
  <div>
    <div class="breadcrumb">General</div>
    <h1>Devices</h1>
    <p>Everything on your network. Give a device a fixed address, block its internet, or wake it up.</p>
  </div>
</div>

{#if loading}
  <div class="panel"><div class="panel-b" style="color:var(--muted);text-align:center;padding:44px">Reading devices…</div></div>
{:else if error}
  <div class="panel"><div class="panel-b" style="text-align:center;padding:40px"><p style="color:var(--crit);margin:0 0 14px">{error}</p><button class="btn primary" on:click={load}>Retry</button></div></div>
{:else}
  <div class="panel">
    <div class="panel-h"><h2>Connected &amp; known devices</h2><span class="sub">{rows.length} total</span></div>
    <div style="overflow-x:auto">
      <table class="clients devtable">
        <thead>
          <tr>
            <th>Device</th>
            <th>Connection</th>
            <th>Fixed IP<Help text="Always give this device the same local address. Useful for port forwarding, printers, servers and NAS." /></th>
            <th style="text-align:center">Block internet<Help text="Cuts this device off from the internet (it can still reach the router). Toggle back any time." /></th>
            <th style="text-align:right">Wake<Help text="Sends a Wake-on-LAN signal to power on a sleeping device. The device must support it and be wired or recently seen." /></th>
          </tr>
        </thead>
        <tbody>
          {#each rows as r (r.mac)}
            <tr class:offline={!r.online}>
              <td>
                <div class="cname">
                  <span class="mi"><Icon name={r.kind} size={17} /></span>
                  <span>
                    {#if editing === r.mac}
                      <span class="renamebox">
                        <input class="nameden" type="text" bind:value={draftName} placeholder="Device name" spellcheck="false" />
                        <button class="btn sm" on:click={() => saveRename(r)} disabled={busy === r.mac}>Save</button>
                        <button class="btn sm ghost" title="Cancel" on:click={() => (editing = '')} disabled={busy === r.mac}>✕</button>
                      </span>
                    {:else}
                      <b>{r.name}</b>
                      <button class="renamebtn" title="Rename device" on:click={() => startRename(r)}>✎</button>
                    {/if}
                    <small class="mono">{r.mac}{#if !r.online} · offline{/if}</small>
                  </span>
                </div>
              </td>
              <td>
                {#if r.online}
                  <span class="bandchip {bandClass[r.band]}">{bandName[r.band]}</span>
                  <div class="hint mono" style="margin-top:3px">{r.ip}</div>
                {:else}
                  <span class="hint">—</span>
                {/if}
              </td>
              <td>
                {#if r.reservedIp}
                  <div class="fixip">
                    <input class="ipin" type="text" bind:value={r.draftIp} spellcheck="false" />
                    <button class="btn sm" on:click={() => doReserve(r)} disabled={busy === r.mac}>Save</button>
                    <button class="btn sm ghost" title="Remove fixed IP" on:click={() => doUnreserve(r)} disabled={busy === r.mac}>✕</button>
                  </div>
                {:else}
                  <button class="btn sm" on:click={() => doReserve(r)} disabled={busy === r.mac || !r.ip}>
                    {r.ip ? `Reserve ${r.ip}` : 'No address yet'}
                  </button>
                {/if}
              </td>
              <td style="text-align:center">
                <label class="toggle">
                  <input type="checkbox" checked={r.blocked} on:change={() => toggleBlock(r)} disabled={busy === r.mac} />
                  <span class="track"></span><span class="knob"></span>
                </label>
              </td>
              <td style="text-align:right">
                <button class="btn sm" on:click={() => doWake(r)} disabled={busy === r.mac} title="Wake-on-LAN">
                  <Icon name="i-power" size={14} /> Wake
                </button>
              </td>
            </tr>
          {/each}
          {#if !rows.length}
            <tr><td colspan="5" style="color:var(--muted);padding:22px">No devices seen yet.</td></tr>
          {/if}
        </tbody>
      </table>
    </div>
  </div>

  <details class="adv" style="max-width:900px"><summary>Advanced details</summary><div class="advb">
    <b>Fixed IP</b> is a <span class="mono">config host</span> entry in <span class="mono">/etc/config/dhcp</span> (static DHCP lease by MAC).
    <b>Block internet</b> is a <span class="mono">config rule</span> in <span class="mono">/etc/config/firewall</span> (<span class="mono">src lan → dest wan</span>, <span class="mono">src_mac</span>, target <span class="mono">REJECT</span>), named <span class="mono">Block: …</span>.
    <b>Wake</b> runs <span class="mono">etherwake</span> on the router, so that package must be installed.
  </div></details>
{/if}

<style>
  .devtable td { vertical-align: middle; }
  .devtable tr.offline .cname b { color: var(--muted); }
  .fixip { display: flex; gap: 6px; align-items: center; }
  .ipin { min-width: 128px; width: 128px; padding: 6px 8px; font-family: var(--font-mono); font-size: 12px; }
  .btn.sm { padding: 6px 10px; font-size: 12px; display: inline-flex; align-items: center; gap: 5px; }
  .btn.sm.ghost { padding: 6px 9px; color: var(--muted); }
  .renamebtn { background: none; border: 0; color: var(--muted); cursor: pointer; padding: 0 4px; font-size: 12px; opacity: 0; }
  .cname:hover .renamebtn { opacity: 1; }
  .renamebox { display: inline-flex; gap: 6px; align-items: center; }
  .nameden { min-width: 150px; padding: 5px 8px; font-size: 13px; }
</style>
