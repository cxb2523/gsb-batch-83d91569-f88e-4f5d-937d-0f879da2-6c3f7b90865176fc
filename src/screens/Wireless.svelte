<script lang="ts">
  import { onMount } from 'svelte';
  import Help from '../components/Help.svelte';
  import {
    loadWireless, saveWireless, ENC_OPTIONS, channelOptions, htmodeOptions, pwStrength,
    type WifiRadio
  } from '../lib/wireless';
  import { toast } from '../lib/toast';
  import { startRollbackConfirm } from '../lib/confirm';

  let radios: WifiRadio[] = [];
  let originals: WifiRadio[] = [];
  let sel = 0;
  let loading = true;
  let error = '';
  let busy = false;
  let showKey = false;

  async function load() {
    loading = true;
    try {
      radios = await loadWireless();
      originals = radios.map((r) => ({ ...r }));
      error = radios.length ? '' : 'No Wi-Fi radios found on this device.';
    } catch {
      error = 'Could not read the wireless configuration.';
    } finally {
      loading = false;
    }
  }
  onMount(load);

  $: r = radios[sel];
  $: dirty = originals[sel] ? JSON.stringify(radios[sel]) !== JSON.stringify(originals[sel]) : false;
  $: strength = r ? pwStrength(r.key) : { label: '', color: '' };

  async function apply() {
    if (!r) return;
    busy = true;
    try {
      await saveWireless(r);
      const i = sel, snap = { ...r };
      startRollbackConfirm('Wireless settings for ' + r.bandLabel, {
        onKeep: () => { originals[i] = snap; originals = originals; },
        onRevert: load
      });
    } catch {
      toast('Could not apply changes');
    } finally {
      busy = false;
    }
  }
  function revert() {
    radios[sel] = { ...originals[sel] };
    radios = radios;
    showKey = false;
    toast('Changes reverted');
  }
</script>

<div class="page-head">
  <div><div class="breadcrumb">Advanced Settings</div><h1>Wireless</h1><p>Configure your Wi-Fi networks. Changes apply when you press Apply.</p></div>
</div>

{#if loading}
  <div class="panel"><div class="panel-b" style="color:var(--muted);text-align:center;padding:44px">Reading wireless configuration…</div></div>
{:else if error}
  <div class="panel"><div class="panel-b" style="text-align:center;padding:40px"><p style="color:var(--crit);margin:0 0 14px">{error}</p><button class="btn primary" on:click={load}>Retry</button></div></div>
{:else}
  <div class="seg" role="tablist">
    {#each radios as rr, i}
      <button class:active={i === sel} on:click={() => { sel = i; showKey = false; }}>{rr.bandLabel}</button>
    {/each}
  </div>

  <div class="panel">
    <div class="panel-h">
      <h2>{r.bandLabel} — Wireless Settings</h2>
      <span class="sub">{r.disabled ? 'radio off' : 'radio on'} · {r.id}</span>
    </div>
    <div class="panel-b">
      <div class="form-row">
        <div class="lbl">Enable radio<Help text="Switches this Wi-Fi band on or off. Turning it off disconnects every device using it." /><small>Turn this band on or off</small></div>
        <div class="ctl"><label class="toggle"><input type="checkbox" checked={!r.disabled} on:change={(e) => (radios[sel].disabled = !e.currentTarget.checked)} /><span class="track"></span><span class="knob"></span></label></div>
      </div>

      <div class="form-row">
        <div class="lbl">Network name (SSID)<Help text="The Wi-Fi name devices see when they scan. 1–32 characters." /></div>
        <div class="ctl"><input type="text" bind:value={radios[sel].ssid} style="min-width:240px" /></div>
      </div>

      <div class="form-row">
        <div class="lbl">Hide SSID<Help text="Stops the name being broadcast, so devices must type it to join. Minor privacy only — not real security." /><small>Make network invisible</small></div>
        <div class="ctl"><label class="toggle"><input type="checkbox" bind:checked={radios[sel].hidden} /><span class="track"></span><span class="knob"></span></label></div>
      </div>

      <div class="form-row">
        <div class="lbl">Security<Help text="How the Wi-Fi is encrypted. WPA3 is strongest; WPA2/WPA3 keeps older devices working. Avoid Open except for a captive guest network." /></div>
        <div class="ctl"><select bind:value={radios[sel].encryption}>{#each ENC_OPTIONS as o}<option value={o.v}>{o.label}</option>{/each}</select></div>
      </div>

      {#if r.encryption !== 'none'}
        <div class="form-row">
          <div class="lbl">Password<Help text="The key devices need to join. Use at least 12 characters for a strong network." /></div>
          <div class="ctl">
            {#if showKey}
              <input type="text" bind:value={radios[sel].key} style="min-width:240px" />
            {:else}
              <input type="password" bind:value={radios[sel].key} style="min-width:240px" />
            {/if}
            <button class="btn" type="button" on:click={() => (showKey = !showKey)}>{showKey ? 'Hide' : 'Show'}</button>
            <span class="strength" style="color:{strength.color}">{strength.label}</span>
          </div>
        </div>
      {/if}

      <div class="form-row">
        <div class="lbl">Channel<Help text="The radio channel. Auto picks the clearest one; set it manually only to dodge a known busy channel." /></div>
        <div class="ctl">
          <select bind:value={radios[sel].channel}>{#each channelOptions(r.band, r.channel) as c}<option value={c}>{c === 'auto' ? 'Auto' : c}</option>{/each}</select>
          <select bind:value={radios[sel].htmode}>{#each htmodeOptions(r.htmode) as h}<option value={h}>{h}</option>{/each}</select>
          <Help text="Channel width (htmode). Wider is faster but less robust; leave as the default unless you know your driver supports a specific mode." />
        </div>
      </div>

      <details class="adv" style="margin-top:4px">
        <summary>Advanced radio settings</summary>
        <div class="advb">
          <div class="form-row">
            <div class="lbl">Country / region<Help text="Regulatory domain (e.g. US, DE, IN). Sets legal channels and power. Wrong codes can hide channels or break Wi-Fi — match where the router actually is." /></div>
            <div class="ctl"><input type="text" maxlength="2" bind:value={radios[sel].country} placeholder="US" style="min-width:80px;text-transform:uppercase" /></div>
          </div>
          <div class="form-row">
            <div class="lbl">Transmit power<Help text="Radio power in dBm. Leave blank for the driver maximum. Lower it only to reduce range/overlap between APs." /></div>
            <div class="ctl"><input type="text" bind:value={radios[sel].txpower} placeholder="max" style="min-width:100px" /><span class="hint">dBm</span></div>
          </div>
          <div class="form-row">
            <div class="lbl">Fast roaming (802.11r)<Help text="Lets devices hand off between access points with the same SSID almost instantly. Useful with more than one AP; harmless on a single router. A few old devices dislike it." /><small>smoother multi-AP handoff</small></div>
            <div class="ctl"><label class="toggle"><input type="checkbox" bind:checked={radios[sel].roaming} /><span class="track"></span><span class="knob"></span></label></div>
          </div>
          <div class="form-row">
            <div class="lbl">WMM / Wi-Fi QoS<Help text="Prioritises voice and video over bulk traffic on the air. Keep on — it's required for 802.11n/ac/ax speeds." /></div>
            <div class="ctl"><label class="toggle"><input type="checkbox" bind:checked={radios[sel].wmm} /><span class="track"></span><span class="knob"></span></label></div>
          </div>
          <div class="form-row" style="border:0">
            <div class="lbl">Client isolation<Help text="Stops devices on this network from talking to each other — only the internet is reachable. Good for a public/guest band; leave off at home." /></div>
            <div class="ctl"><label class="toggle"><input type="checkbox" bind:checked={radios[sel].isolate} /><span class="track"></span><span class="knob"></span></label></div>
          </div>
        </div>
      </details>

      <div class="form-actions">
        <button class="btn" type="button" on:click={revert} disabled={!dirty || busy}>Revert</button>
        <button class="btn primary" type="button" on:click={apply} disabled={!dirty || busy}>
          {busy ? 'Applying…' : 'Apply'}
        </button>
      </div>
    </div>
  </div>
{/if}
