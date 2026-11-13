<script lang="ts">
  import { onMount } from 'svelte';
  import Help from '../components/Help.svelte';
  import { loadQos, saveQos, type QosState } from '../lib/qos';
  import { toast } from '../lib/toast';

  let state: QosState | null = null;
  let loading = true;
  let error = '';
  let busy = false;

  async function load() {
    loading = true;
    try { state = await loadQos(); error = ''; }
    catch { error = 'Could not read the QoS configuration.'; }
    finally { loading = false; }
  }
  onMount(load);

  async function apply() {
    if (!state) return;
    const q = state.queue;
    if (q.enabled && (q.downMbps <= 0 || q.upMbps <= 0)) {
      toast('Enter your download and upload speeds first');
      return;
    }
    busy = true;
    try { await saveQos(q); toast(q.enabled ? 'Smart Queue applied' : 'Smart Queue turned off'); await load(); }
    catch { toast('Could not apply QoS settings'); }
    finally { busy = false; }
  }
</script>

<div class="page-head"><div><div class="breadcrumb">Advanced Settings</div><h1>QoS (Smart Queue)</h1><p>Keep video calls, gaming and browsing smooth when the connection is busy, by taming bufferbloat.</p></div></div>

{#if loading}
  <div class="panel"><div class="panel-b" style="color:var(--muted);text-align:center;padding:44px">Reading configuration…</div></div>
{:else if error || !state}
  <div class="panel"><div class="panel-b" style="text-align:center;padding:40px"><p style="color:var(--crit);margin:0 0 14px">{error}</p><button class="btn primary" on:click={load}>Retry</button></div></div>
{:else if !state.installed}
  <div class="panel" style="max-width:720px"><div class="panel-b">
    <p style="margin:0 0 6px"><b>Smart Queue isn't installed yet.</b></p>
    <p class="hint" style="margin:0">Install the <span class="mono">sqm-scripts</span> package (Software screen or <span class="mono">opkg/apk</span>), then come back to set your speeds.</p>
  </div></div>
{:else}
  <div class="panel" style="max-width:720px"><div class="panel-b">
    <div class="form-row"><div class="lbl">Turn on Smart Queue<Help text="Shapes your traffic just below your real line speed so no single download can hog the link. Greatly reduces lag during heavy use." /></div>
      <div class="ctl"><label class="toggle"><input type="checkbox" bind:checked={state.queue.enabled} /><span class="track"></span><span class="knob"></span></label></div></div>

    {#if state.queue.enabled}
      <div class="form-row"><div class="lbl">Measured download speed<Help text="Your real, tested download speed in Mbps — from a speed test, NOT your plan's advertised number. Set it to about 90–95% of the tested result." /></div>
        <div class="ctl"><input type="number" min="0" bind:value={state.queue.downMbps} style="min-width:120px" /><span class="hint">Mbps</span></div></div>
      <div class="form-row"><div class="lbl">Measured upload speed<Help text="Your real, tested upload speed in Mbps — from a speed test, NOT your plan's number. Set it to about 85–90% of the tested result. Correct upload is the biggest factor for call/gaming lag." /></div>
        <div class="ctl"><input type="number" min="0" bind:value={state.queue.upMbps} style="min-width:120px" /><span class="hint">Mbps</span></div></div>
      <p class="hint" style="margin:-4px 0 10px">Use speeds from a real speed test, not the plan you pay for. Set them a bit below your tested result so Smart Queue stays in control of the queue.</p>
      <div class="form-row"><div class="lbl">Mode<Help text="Simple shares the link fairly between devices. Prioritised also gives interactive traffic (calls, games, DNS) a head start." /></div>
        <div class="ctl"><select bind:value={state.queue.script}>
          <option value="piece_of_cake.qos">Simple (fair sharing)</option>
          <option value="layer_cake.qos">Prioritised (calls &amp; games first)</option>
        </select></div></div>
      <details class="adv"><summary>Advanced details</summary><div class="advb">
        <div class="form-row" style="border:0;padding-top:4px"><div class="lbl">WAN interface<Help text="The network device the shaper attaches to — normally your WAN/internet port." /></div>
          <div class="ctl"><input type="text" bind:value={state.queue.interface} spellcheck="false" style="min-width:160px" /></div></div>
        <p style="margin:6px 0 0">Shaper <span class="mono">cake</span> via <span class="mono">sqm-scripts</span>, stored as a <span class="mono">config queue</span> in <span class="mono">/etc/config/sqm</span>. Detected WAN device: <span class="mono">{state.wanDevice}</span>.</p>
      </div></details>
    {/if}

    <div class="form-actions"><button class="btn primary" on:click={apply} disabled={busy}>{busy ? 'Applying…' : 'Apply'}</button></div>
  </div></div>
{/if}
