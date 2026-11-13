<script lang="ts">
  import { onMount } from 'svelte';
  import Help from '../components/Help.svelte';
  import { loadLan, saveLan, type LanCfg } from '../lib/lan';
  import { toast } from '../lib/toast';
  import { startRollbackConfirm } from '../lib/confirm';

  let cfg: LanCfg | null = null;
  let orig = '';
  let loading = true;
  let error = '';
  let busy = false;

  async function load() {
    loading = true;
    try { cfg = await loadLan(); orig = JSON.stringify(cfg); error = ''; }
    catch { error = 'Could not read the LAN configuration.'; }
    finally { loading = false; }
  }
  onMount(load);
  $: dirty = cfg ? JSON.stringify(cfg) !== orig : false;

  async function apply() {
    if (!cfg) return; busy = true;
    try {
      await saveLan(cfg);
      const snap = JSON.stringify(cfg);
      startRollbackConfirm('LAN settings', {
        onKeep: () => (orig = snap),
        onRevert: load
      });
    } catch { toast('Could not apply changes'); }
    finally { busy = false; }
  }
</script>

<div class="page-head"><div><div class="breadcrumb">Advanced Settings</div><h1>LAN</h1><p>Your home network address and the range of addresses handed out to devices.</p></div></div>

{#if loading}
  <div class="panel"><div class="panel-b" style="color:var(--muted);text-align:center;padding:44px">Reading configuration…</div></div>
{:else if error || !cfg}
  <div class="panel"><div class="panel-b" style="text-align:center;padding:40px"><p style="color:var(--crit);margin:0 0 14px">{error}</p><button class="btn primary" on:click={load}>Retry</button></div></div>
{:else}
  <div class="panel" style="max-width:720px"><div class="panel-b">
    <div class="form-row"><div class="lbl">Router address<Help text="The router's own address on your network, and the one you type to reach this page. Changing it disconnects you briefly." /></div><div class="ctl"><input type="text" bind:value={cfg.ipaddr} /></div></div>
    <div class="form-row"><div class="lbl">Subnet mask</div><div class="ctl"><input type="text" bind:value={cfg.netmask} /></div></div>
    <div class="form-row"><div class="lbl">Hand out addresses (DHCP)<Help text="When on, the router automatically gives each device an address. Turn off only if another device does this." /></div><div class="ctl"><label class="toggle"><input type="checkbox" bind:checked={cfg.dhcp} /><span class="track"></span><span class="knob"></span></label></div></div>
    {#if cfg.dhcp}
      <div class="form-row"><div class="lbl">First address<Help text="Offset from the router address where the pool starts (e.g. 100 → .100)." /></div><div class="ctl"><input type="text" bind:value={cfg.start} style="min-width:120px" /></div></div>
      <div class="form-row"><div class="lbl">Pool size<Help text="How many addresses can be handed out." /></div><div class="ctl"><input type="text" bind:value={cfg.limit} style="min-width:120px" /></div></div>
      <div class="form-row"><div class="lbl">Lease time<Help text="How long a device keeps its address before renewing (e.g. 12h, 1d)." /></div><div class="ctl"><input type="text" bind:value={cfg.leasetime} style="min-width:120px" /></div></div>
    {/if}
    <div class="form-actions"><button class="btn primary" on:click={apply} disabled={!dirty || busy}>{busy ? 'Applying…' : 'Apply'}</button></div>
  </div></div>
{/if}
