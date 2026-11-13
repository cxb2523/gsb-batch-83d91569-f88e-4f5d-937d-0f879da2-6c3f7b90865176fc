<script lang="ts">
  import Help from '../components/Help.svelte';
  import Icon from '../components/Icon.svelte';
  import { scan, joinNetwork, type ScanResult } from '../lib/repeater';
  import { toast } from '../lib/toast';

  type Step = 'scan' | 'pass' | 'done';
  let step: Step = 'scan';
  let results: ScanResult[] = [];
  let scanning = false;
  let busy = false;
  let scanned = false;
  let chosen: ScanResult | null = null;
  let password = '';
  let scanError = '';

  async function doScan() {
    scanning = true; scanError = '';
    try { results = await scan(); scanned = true; }
    catch { scanError = 'Could not scan. Your radio may not support scanning while hosting Wi-Fi.'; }
    finally { scanning = false; }
  }
  function pick(n: ScanResult) { chosen = n; password = ''; if (n.locked) step = 'pass'; else join(); }
  async function join() {
    if (!chosen) return;
    busy = true;
    try { await joinNetwork(chosen.ssid, chosen.locked ? password : ''); step = 'done'; toast('Connecting to ' + chosen.ssid); }
    catch { toast('Could not join the network'); }
    finally { busy = false; }
  }
  function bars(n: number) { return [1, 2, 3, 4].map((i) => i <= n); }
</script>

<div class="page-head"><div><div class="breadcrumb">General</div><h1>Extend Wi-Fi</h1><p>Connect this router to a Wi-Fi network you already have, to extend its reach.</p></div></div>

<div class="panel" style="max-width:660px"><div class="panel-b">
  {#if step === 'scan'}
    <div class="ext-head" style="display:flex;align-items:center;gap:13px;margin-bottom:16px">
      <div class="devicon"><Icon name="i-ext" size={22} /></div>
      <div><b style="font-size:15px">Choose a network to extend</b><div class="hint">Scan for nearby Wi-Fi the router can see.</div></div>
      <button class="btn" style="margin-left:auto" on:click={doScan} disabled={scanning}>{scanning ? 'Scanning…' : scanned ? 'Rescan' : 'Scan'}</button>
    </div>
    {#if scanError}<p class="hint" style="color:var(--crit)">{scanError}</p>{/if}
    {#each results as n}
      <button class="devrow2 devlist-row" style="width:100%;text-align:left;cursor:pointer" on:click={() => pick(n)}>
        <span class="sig" style="color:var(--accent)">{#each bars(n.signal) as on, i}<i class:on style="height:{(i + 1) * 3 + 2}px"></i>{/each}</span>
        <span class="dn" style="margin-left:8px"><b>{n.ssid}</b></span>
        {#if n.locked}<Icon name="i-vpn" size={15} />{:else}<span class="hint">open</span>{/if}
      </button>
    {/each}
    {#if scanned && !results.length && !scanError}<p class="hint">No networks found.</p>{/if}
  {:else if step === 'pass'}
    <div class="ext-head" style="display:flex;align-items:center;gap:13px;margin-bottom:16px">
      <div class="devicon"><Icon name="i-wifi" size={22} /></div>
      <div><b style="font-size:15px">Connect to {chosen?.ssid}</b><div class="hint">Enter the password for this network.</div></div>
    </div>
    <div class="ctl"><input type="text" bind:value={password} placeholder="Wi-Fi password" style="min-width:260px" /></div>
    <div class="form-actions"><button class="btn" on:click={() => (step = 'scan')}>Back</button><button class="btn primary" on:click={join} disabled={busy}>Connect</button></div>
  {:else}
    <div style="text-align:center;padding:10px 0">
      <div class="big-ic" style="margin:0 auto 12px"><Icon name="i-check" size={30} /></div>
      <h3 style="margin:0 0 4px;font-size:18px">Connecting to {chosen?.ssid}</h3>
      <p class="hint">The router is joining the network as a client.</p>
      <p class="hint" style="max-width:420px;margin:8px auto 0">This extends Wi-Fi for devices connected to <b>this</b> router. Sharing the connection with your wired/LAN devices needs an extra relay step (coming soon).</p>
      <div style="margin-top:16px"><button class="btn" on:click={() => { step = 'scan'; }}>Extend another network</button></div>
    </div>
  {/if}
</div></div>

<details class="adv" style="max-width:660px"><summary>Advanced details</summary><div class="advb">This adds a client (<span class="mono">mode 'sta'</span>) Wi-Fi interface on a <span class="mono">wwan</span> network (DHCP). To also share that connection with your wired/LAN devices, a <span class="mono">relayd</span> relay bridge between <span class="mono">lan</span> and <span class="mono">wwan</span> is needed — a follow-up step on this screen.</div></details>

<style>.big-ic{width:70px;height:70px;border-radius:50%;background:rgba(23,178,106,.14);display:grid;place-items:center}</style>
