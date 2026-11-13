<script lang="ts">
  import { onMount } from 'svelte';
  import Help from '../components/Help.svelte';
  import { loadGuests, saveGuest, createGuest, type GuestNet } from '../lib/guest';
  import { toast } from '../lib/toast';

  let guests: GuestNet[] = [];
  let originals: GuestNet[] = [];
  let loading = true;
  let error = '';
  let busy = false;

  async function load() {
    loading = true;
    try {
      guests = await loadGuests();
      originals = guests.map((g) => ({ ...g }));
      error = '';
    } catch {
      error = 'Could not read the wireless configuration.';
    } finally {
      loading = false;
    }
  }
  onMount(load);

  function dirty(i: number) {
    return originals[i] && JSON.stringify(guests[i]) !== JSON.stringify(originals[i]);
  }
  async function apply(i: number) {
    busy = true;
    try {
      await saveGuest(guests[i]);
      originals[i] = { ...guests[i] };
      originals = originals;
      toast('Guest network applied');
    } catch {
      toast('Could not apply changes');
    } finally {
      busy = false;
    }
  }
  async function setup() {
    busy = true;
    try {
      await createGuest();
      toast('Guest network created');
      await load();
    } catch {
      toast('Could not create the guest network');
    } finally {
      busy = false;
    }
  }
</script>

<div class="page-head">
  <div><div class="breadcrumb">General</div><h1>Guest Network</h1><p>Give visitors internet access without sharing your main password or exposing your devices.</p></div>
</div>

{#if loading}
  <div class="panel"><div class="panel-b" style="color:var(--muted);text-align:center;padding:44px">Reading configuration…</div></div>
{:else if error}
  <div class="panel"><div class="panel-b" style="text-align:center;padding:40px"><p style="color:var(--crit);margin:0 0 14px">{error}</p><button class="btn primary" on:click={load}>Retry</button></div></div>
{:else if !guests.length}
  <div class="panel"><div class="panel-b" style="text-align:center;padding:40px">
    <p style="margin:0 0 6px;font-weight:600">No guest network yet</p>
    <p class="hint" style="max-width:440px;margin:0 auto 18px">Create an isolated guest Wi-Fi: visitors get internet, but can't reach your own devices or your main password.</p>
    <button class="btn primary" on:click={setup} disabled={busy}>{busy ? 'Creating…' : 'Create guest network'}</button>
  </div></div>
{:else}
  <div class="cardgrid">
    {#each guests as g, i}
      <div class="gcard" class:off={g.disabled}>
        <div class="gc-top"><b>{g.ssid || 'Guest'} · {g.bandLabel}</b>
          <label class="toggle"><input type="checkbox" checked={!g.disabled} on:change={(e) => (guests[i].disabled = !e.currentTarget.checked)} /><span class="track"></span><span class="knob"></span></label>
        </div>
        <div class="form-row" style="grid-template-columns:1fr;padding:6px 0;border:0;gap:6px">
          <div class="lbl">Network name (SSID)<Help text="The guest Wi-Fi name visitors see and join." /></div>
          <input type="text" bind:value={guests[i].ssid} />
        </div>
        <div class="form-row" style="grid-template-columns:1fr;padding:6px 0;border:0;gap:6px">
          <div class="lbl">Password<Help text="The key guests type to join. Keep it different from your main Wi-Fi." /></div>
          <input type="text" bind:value={guests[i].key} />
        </div>
        <div class="gc-meta">
          <label class="followlbl"><input type="checkbox" bind:checked={guests[i].isolate} /> Client isolation</label>
          <Help text="When on, guest devices can't see or talk to each other — only the internet." />
        </div>
        <div style="display:flex;justify-content:flex-end"><button class="btn primary" on:click={() => apply(i)} disabled={!dirty(i) || busy}>Apply</button></div>
      </div>
    {/each}
  </div>
  <details class="adv" style="max-width:720px;margin-top:18px"><summary>Advanced details</summary><div class="advb">Each guest SSID is a <span class="mono">wifi-iface</span> on a guest network with client isolation. The guest zone forwards only to <span class="mono">wan</span>, so guests reach the internet but not your LAN.</div></details>
{/if}

<style>.followlbl{display:flex;align-items:center;gap:7px;font-size:12.5px;color:var(--ink-dim)}</style>
