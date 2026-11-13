<script lang="ts">
  import { onMount } from 'svelte';
  import Help from '../components/Help.svelte';
  import { loadWan, saveWan, type WanCfg } from '../lib/wan';
  import { toast } from '../lib/toast';
  import { startRollbackConfirm } from '../lib/confirm';

  let cfg: WanCfg | null = null;
  let orig = '';
  let loading = true;
  let error = '';
  let busy = false;

  async function load() {
    loading = true;
    try { cfg = await loadWan(); orig = JSON.stringify(cfg); error = ''; }
    catch { error = 'Could not read the internet configuration.'; }
    finally { loading = false; }
  }
  onMount(load);
  $: dirty = cfg ? JSON.stringify(cfg) !== orig : false;

  async function apply() {
    if (!cfg) return; busy = true;
    try {
      await saveWan(cfg);
      const snap = JSON.stringify(cfg);
      startRollbackConfirm('Internet settings', { onKeep: () => (orig = snap), onRevert: load });
    } catch { toast('Could not apply changes'); }
    finally { busy = false; }
  }
</script>

<div class="page-head"><div><div class="breadcrumb">Advanced Settings</div><h1>Internet (WAN)</h1><p>How the router connects to your internet provider.</p></div></div>

{#if loading}
  <div class="panel"><div class="panel-b" style="color:var(--muted);text-align:center;padding:44px">Reading configuration…</div></div>
{:else if error || !cfg}
  <div class="panel"><div class="panel-b" style="text-align:center;padding:40px"><p style="color:var(--crit);margin:0 0 14px">{error}</p><button class="btn primary" on:click={load}>Retry</button></div></div>
{:else}
  <div class="panel" style="max-width:720px"><div class="panel-b">
    <div class="form-row"><div class="lbl">Connection type<Help text="DHCP = your ISP assigns everything automatically (most common). PPPoE = DSL/fibre with a login. Static = a fixed address your ISP gave you." /></div>
      <div class="ctl"><select bind:value={cfg.proto}><option value="dhcp">Automatic (DHCP)</option><option value="pppoe">PPPoE</option><option value="static">Static IP</option></select></div></div>

    {#if cfg.proto === 'pppoe'}
      <div class="form-row"><div class="lbl">Username<Help text="The PPPoE sign-in name from your ISP." /></div><div class="ctl"><input type="text" bind:value={cfg.username} style="min-width:240px" /></div></div>
      <div class="form-row"><div class="lbl">Password</div><div class="ctl"><input type="password" bind:value={cfg.password} style="min-width:240px" /></div></div>
    {:else if cfg.proto === 'static'}
      <div class="form-row"><div class="lbl">IP address</div><div class="ctl"><input type="text" bind:value={cfg.ipaddr} placeholder="203.0.113.42" /></div></div>
      <div class="form-row"><div class="lbl">Subnet mask</div><div class="ctl"><input type="text" bind:value={cfg.netmask} /></div></div>
      <div class="form-row"><div class="lbl">Gateway</div><div class="ctl"><input type="text" bind:value={cfg.gateway} placeholder="203.0.113.1" /></div></div>
    {/if}

    <div class="form-row"><div class="lbl">Use ISP's DNS<Help text="On: use the DNS servers your ISP provides. Off: set your own below (e.g. 1.1.1.1)." /></div>
      <div class="ctl"><label class="toggle"><input type="checkbox" bind:checked={cfg.peerdns} /><span class="track"></span><span class="knob"></span></label></div></div>
    {#if !cfg.peerdns}
      <div class="form-row"><div class="lbl">DNS servers<Help text="Space-separated. Example: 1.1.1.1 9.9.9.9" /></div><div class="ctl"><input type="text" bind:value={cfg.dns} placeholder="1.1.1.1 9.9.9.9" style="min-width:240px" /></div></div>
    {/if}

    <div class="form-actions"><button class="btn primary" on:click={apply} disabled={!dirty || busy}>{busy ? 'Applying…' : 'Apply'}</button></div>
  </div></div>
{/if}
