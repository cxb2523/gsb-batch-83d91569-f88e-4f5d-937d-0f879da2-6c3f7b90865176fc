<script lang="ts">
  import { onMount } from 'svelte';
  import { loadProtection, setFeature, type Feature } from '../lib/protection';
  import { toast } from '../lib/toast';

  let features: Feature[] = [];
  let loading = true;
  let error = '';
  let busy = false;

  async function load() {
    loading = true;
    try { features = await loadProtection(); error = ''; }
    catch { error = 'Could not read the configuration.'; }
    finally { loading = false; }
  }
  onMount(load);

  async function toggle(f: Feature, on: boolean) {
    if (!f.installed) return;
    busy = true;
    const prev = f.enabled;
    f.enabled = on; features = features;
    try { await setFeature(f, on); toast((on ? 'Turned on: ' : 'Turned off: ') + f.label); }
    catch { f.enabled = prev; features = features; toast('Could not change setting'); }
    finally { busy = false; }
  }
</script>

<div class="page-head"><div><div class="breadcrumb">General</div><h1>Network Protection</h1><p>Simple safety switches for everyone on your network.</p></div></div>

{#if loading}
  <div class="panel"><div class="panel-b" style="color:var(--muted);text-align:center;padding:44px">Reading configuration…</div></div>
{:else if error}
  <div class="panel"><div class="panel-b" style="text-align:center;padding:40px"><p style="color:var(--crit);margin:0 0 14px">{error}</p><button class="btn primary" on:click={load}>Retry</button></div></div>
{:else}
  <div class="cardgrid">
    {#each features as f}
      <div class="gcard" class:off={!f.enabled || !f.installed}>
        <div class="gc-top"><b>{f.label}</b>
          {#if f.link}
            {#if f.installed}
              <a class="btn sm" href={f.link} target="_blank" rel="noopener">Open ›</a>
            {:else}
              <span class="statechip st-sched">not installed</span>
            {/if}
          {:else if f.installed}
            <label class="toggle"><input type="checkbox" checked={f.enabled} on:change={(e) => toggle(f, e.currentTarget.checked)} disabled={busy} /><span class="track"></span><span class="knob"></span></label>
          {:else}
            <span class="statechip st-sched">not installed</span>
          {/if}
        </div>
        <div class="hint">{f.desc}</div>
        {#if !f.installed}<div class="gc-meta"><span>Install the <span class="mono">{f.pkg}</span> package to use this.</span></div>{/if}
      </div>
    {/each}
  </div>
  <details class="adv" style="max-width:720px;margin-top:18px"><summary>Advanced details</summary><div class="advb">These switches toggle on-device services via their uci config: ad/tracker blocking (<span class="mono">adblock</span>) and malicious-IP blocking with threat feeds (<span class="mono">banip</span>). Changes are applied and the service reloads. No traffic goes to a cloud filter.</div></details>
{/if}
