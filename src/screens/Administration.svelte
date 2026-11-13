<script lang="ts">
  import { onMount } from 'svelte';
  import Help from '../components/Help.svelte';
  import {
    loadSystem, saveSystem, setPassword, reboot, TIMEZONES, type SysCfg,
    loadRebootSchedule, saveRebootSchedule, type RebootSchedule,
    loadDefaultPage, setDefaultPage
  } from '../lib/system';
  import { toast } from '../lib/toast';

  let cfg: SysCfg | null = null;
  let orig = '';
  let loading = true;
  let error = '';
  let busy = false;

  let pw1 = '';
  let pw2 = '';
  let confirmReboot = false;

  let sched: RebootSchedule = { enabled: false, hour: 4, minute: 0, day: '*' };
  let schedBusy = false;
  const DOW = [
    { v: '*', label: 'Every day' },
    { v: '1', label: 'Monday' }, { v: '2', label: 'Tuesday' }, { v: '3', label: 'Wednesday' },
    { v: '4', label: 'Thursday' }, { v: '5', label: 'Friday' }, { v: '6', label: 'Saturday' },
    { v: '0', label: 'Sunday' }
  ];
  // Bridge the schedule to an <input type="time"> value (HH:MM).
  $: schedTime =
    String(sched.hour).padStart(2, '0') + ':' + String(sched.minute).padStart(2, '0');
  function onSchedTime(e: Event) {
    const [h, m] = (e.target as HTMLInputElement).value.split(':');
    sched.hour = Math.min(23, Math.max(0, +h || 0));
    sched.minute = Math.min(59, Math.max(0, +m || 0));
  }

  async function load() {
    loading = true;
    try {
      cfg = await loadSystem();
      orig = JSON.stringify(cfg);
      sched = await loadRebootSchedule().catch(() => sched);
      home = await loadDefaultPage().catch(() => false);
      error = '';
    }
    catch { error = 'Could not read the system configuration.'; }
    finally { loading = false; }
  }
  onMount(load);

  // Default page: is "/" UnTangled? Also show an escape hatch to LuCI when it exists.
  let home = false;
  let homeBusy = false;
  let hasLuci = false;
  fetch('/cgi-bin/luci', { method: 'HEAD' }).then((r) => (hasLuci = r.ok)).catch(() => {});
  async function toggleHome(e: Event) {
    const el = e.target as HTMLInputElement;
    homeBusy = true;
    try { await setDefaultPage(el.checked); home = el.checked; toast(home ? 'UnTangled is now the default page' : 'Default page restored'); }
    catch { el.checked = home; toast('Could not change the default page'); }
    finally { homeBusy = false; }
  }

  async function applySchedule() {
    schedBusy = true;
    try {
      await saveRebootSchedule(sched);
      toast(sched.enabled ? 'Scheduled reboot saved' : 'Scheduled reboot turned off');
    } catch { toast('Could not save the schedule'); }
    finally { schedBusy = false; }
  }
  $: dirty = cfg ? JSON.stringify(cfg) !== orig : false;

  function onZone(e: Event) {
    const zn = (e.target as HTMLSelectElement).value;
    const tz = TIMEZONES.find((t) => t.zonename === zn);
    if (cfg && tz) { cfg.zonename = tz.zonename; cfg.timezone = tz.timezone; }
  }
  async function applySystem() {
    if (!cfg) return; busy = true;
    try { await saveSystem(cfg); orig = JSON.stringify(cfg); toast('System settings applied'); }
    catch { toast('Could not apply changes'); }
    finally { busy = false; }
  }
  async function changePassword() {
    if (pw1.length < 5) { toast('Choose a longer password'); return; }
    if (pw1 !== pw2) { toast('Passwords do not match'); return; }
    busy = true;
    try { await setPassword(pw1); pw1 = pw2 = ''; toast('Router password changed'); }
    catch { toast('Could not change password (needs rpcd-mod-luci)'); }
    finally { busy = false; }
  }
  async function doReboot() {
    confirmReboot = false; busy = true;
    try { await reboot(); toast('Rebooting…'); }
    catch { toast('Could not reboot'); }
    finally { busy = false; }
  }
</script>

<div class="page-head"><div><div class="breadcrumb">Advanced Settings</div><h1>Administration</h1><p>Router name, time, password, and power.</p></div></div>

{#if loading}
  <div class="panel"><div class="panel-b" style="color:var(--muted);text-align:center;padding:44px">Reading configuration…</div></div>
{:else if error || !cfg}
  <div class="panel"><div class="panel-b" style="text-align:center;padding:40px"><p style="color:var(--crit);margin:0 0 14px">{error}</p><button class="btn primary" on:click={load}>Retry</button></div></div>
{:else}
  <div class="panel" style="max-width:720px;margin-bottom:18px">
    <div class="panel-h"><h2>General</h2></div>
    <div class="panel-b">
      <div class="form-row"><div class="lbl">Router name<Help text="The hostname shown on your network and in the title bar." /></div><div class="ctl"><input type="text" bind:value={cfg.hostname} /></div></div>
      <div class="form-row"><div class="lbl">Time zone<Help text="Sets the clock used for logs and schedules (like parental controls)." /></div>
        <div class="ctl"><select value={cfg.zonename} on:change={onZone}>{#each TIMEZONES as t}<option value={t.zonename}>{t.zonename}</option>{/each}</select></div></div>
      <div class="form-actions"><button class="btn primary" on:click={applySystem} disabled={!dirty || busy}>Apply</button></div>
    </div>
  </div>

  <div class="panel" style="max-width:720px;margin-bottom:18px">
    <div class="panel-h"><h2>Default page</h2></div>
    <div class="panel-b">
      <div class="form-row"><div class="lbl">Open UnTangled at http://router/<Help text="Makes UnTangled the page you land on when you type the router's address. LuCI, if installed, keeps working at /cgi-bin/luci — nothing is removed, and you can switch back any time." /></div>
        <div class="ctl"><label class="toggle"><input type="checkbox" checked={home} disabled={homeBusy} on:change={toggleHome} /><span class="track"></span><span class="knob"></span></label>
          {#if hasLuci}<a class="hint" href="/cgi-bin/luci" target="_blank" rel="noopener">Open LuCI</a>{/if}</div></div>
    </div>
  </div>

  <div class="panel" style="max-width:720px;margin-bottom:18px">
    <div class="panel-h"><h2>Router password</h2></div>
    <div class="panel-b">
      <div class="form-row"><div class="lbl">New password</div><div class="ctl"><input type="password" bind:value={pw1} /></div></div>
      <div class="form-row"><div class="lbl">Confirm</div><div class="ctl"><input type="password" bind:value={pw2} /></div></div>
      <div class="form-actions"><button class="btn primary" on:click={changePassword} disabled={busy || !pw1}>Change password</button></div>
    </div>
  </div>

  <div class="panel" style="max-width:720px;margin-bottom:18px">
    <div class="panel-h"><h2>Scheduled reboot</h2><span class="sub">optional</span></div>
    <div class="panel-b">
      <div class="form-row"><div class="lbl">Reboot automatically<Help text="Restart the router on a regular schedule — a simple way to keep it fresh. The network drops for about a minute when it runs." /></div>
        <div class="ctl"><label class="toggle"><input type="checkbox" bind:checked={sched.enabled} /><span class="track"></span><span class="knob"></span></label></div></div>
      {#if sched.enabled}
        <div class="form-row"><div class="lbl">When</div>
          <div class="ctl">
            <select bind:value={sched.day}>{#each DOW as d}<option value={d.v}>{d.label}</option>{/each}</select>
            <span class="hint">at</span>
            <input type="time" value={schedTime} on:change={onSchedTime} />
          </div></div>
      {/if}
      <div class="form-actions"><button class="btn primary" on:click={applySchedule} disabled={schedBusy}>{schedBusy ? 'Saving…' : 'Save schedule'}</button></div>
    </div>
  </div>

  <div class="panel" style="max-width:720px">
    <div class="panel-h"><h2>Power</h2></div>
    <div class="panel-b">
      {#if confirmReboot}
        <p style="margin:0 0 14px">The router will restart and the network will drop for about a minute.</p>
        <div style="display:flex;gap:10px"><button class="btn" on:click={() => (confirmReboot = false)}>Cancel</button><button class="btn primary" on:click={doReboot} disabled={busy}>Reboot now</button></div>
      {:else}
        <button class="btn" on:click={() => (confirmReboot = true)}>Reboot router</button>
      {/if}
    </div>
  </div>
{/if}
