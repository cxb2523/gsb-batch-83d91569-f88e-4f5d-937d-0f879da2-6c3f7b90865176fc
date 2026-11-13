<script lang="ts">
  import { onMount } from 'svelte';
  import Help from '../components/Help.svelte';
  import { firmwareInfo, uploadFirmware, testFirmware, flashFirmware, cleanFirmware, downloadBackup, restoreBackup, type FwInfo } from '../lib/firmware';
  import { formatBytes } from '../lib/net';
  import { toast } from '../lib/toast';

  let info: FwInfo | null = null;
  let loading = true;
  let error = '';

  let file: File | null = null;
  let stage: 'pick' | 'checking' | 'ready' | 'invalid' | 'flashing' = 'pick';
  let sizeStr = '';
  let validMsg = '';
  let keep = true;

  async function load() {
    loading = true;
    try { info = await firmwareInfo(); error = ''; }
    catch { error = 'Could not read the current firmware information.'; }
    finally { loading = false; }
  }
  onMount(load);

  function onFile(e: Event) {
    const f = (e.target as HTMLInputElement).files?.[0] ?? null;
    file = f;
    stage = 'pick'; validMsg = ''; sizeStr = f ? formatBytes(f.size) : '';
  }

  async function uploadAndCheck() {
    if (!file) return;
    stage = 'checking';
    try {
      const up = await uploadFirmware(file);
      sizeStr = formatBytes(up.size || file.size);
      const t = await testFirmware();
      if (t.code === 0) { stage = 'ready'; validMsg = 'Image looks valid for this device.'; }
      else { stage = 'invalid'; validMsg = (t.stderr || t.stdout || 'The router rejected this image.').trim(); }
    } catch (e: any) {
      stage = 'invalid';
      validMsg = e?.message === 'cgi-io missing'
        ? 'Upload endpoint missing — install the "cgi-io" package to flash from the browser.'
        : 'Upload failed. Check the file and try again.';
    }
  }

  async function doFlash() {
    if (stage !== 'ready') return;
    stage = 'flashing';
    try {
      await flashFirmware(keep);
      toast('Flashing started — the router will reboot. Do not power off.');
    } catch {
      toast('Could not start the flash');
      stage = 'ready';
    }
  }
  async function cancel() {
    await cleanFirmware();
    file = null; stage = 'pick'; validMsg = ''; sizeStr = '';
  }

  let backupBusy = false;
  let restoreBusy = false;
  async function doBackup() {
    backupBusy = true;
    try { await downloadBackup(); toast('Backup downloaded'); }
    catch (e: any) { toast(e?.message === 'cgi-io missing' ? 'Needs the "cgi-io" package' : 'Could not create the backup'); }
    finally { backupBusy = false; }
  }
  async function onRestore(e: Event) {
    const f = (e.target as HTMLInputElement).files?.[0];
    (e.target as HTMLInputElement).value = '';
    if (!f) return;
    if (!confirm('Restore this backup? The router will reboot and replace its current settings.')) return;
    restoreBusy = true;
    try { await restoreBackup(f); toast('Restoring — the router will reboot.'); }
    catch (e: any) { toast(e?.message === 'cgi-io missing' ? 'Needs the "cgi-io" package' : 'Could not restore the backup'); }
    finally { restoreBusy = false; }
  }
</script>

<div class="page-head"><div><div class="breadcrumb">Advanced Settings</div><h1>Firmware</h1><p>Install a new OpenWRT image on your router.</p></div></div>

{#if loading}
  <div class="panel"><div class="panel-b" style="color:var(--muted);text-align:center;padding:44px">Reading firmware information…</div></div>
{:else if error}
  <div class="panel"><div class="panel-b" style="text-align:center;padding:40px"><p style="color:var(--crit);margin:0 0 14px">{error}</p><button class="btn primary" on:click={load}>Retry</button></div></div>
{:else}
  <div class="panel" style="max-width:720px;margin-bottom:16px">
    <div class="panel-h"><h2>Current</h2></div>
    <div class="panel-b">
      <div class="kv"><span class="l">Model</span><span class="r">{info?.model}</span></div>
      <div class="kv"><span class="l">Firmware</span><span class="r">{info?.firmware}</span></div>
    </div>
  </div>

  <div class="panel" style="max-width:720px;margin-bottom:16px">
    <div class="panel-h"><h2>Backup &amp; restore</h2></div>
    <div class="panel-b">
      <div class="form-row"><div class="lbl">Backup settings<Help text="Downloads a .tar.gz of your router's configuration (/etc). Keep it safe — you can restore it after a reset or on a replacement router of the same model." /></div>
        <div class="ctl"><button class="btn" on:click={doBackup} disabled={backupBusy}>{backupBusy ? 'Preparing…' : 'Download backup'}</button></div></div>
      <div class="form-row" style="border-bottom:0"><div class="lbl">Restore settings<Help text="Uploads a backup archive and applies it, then reboots. Restore only a backup from this same model." /></div>
        <div class="ctl"><label class="btn" style="cursor:pointer">{restoreBusy ? 'Restoring…' : 'Choose backup…'}<input type="file" accept=".tar.gz,.tgz,.tar" on:change={onRestore} disabled={restoreBusy} style="display:none" /></label></div></div>
    </div>
  </div>

  <div class="panel" style="max-width:720px"><div class="panel-b">
    <div class="caution" style="margin-bottom:16px">
      <span><b>Flashing replaces the router's software.</b> Use only an image built for <span class="mono">{info?.model}</span>. A wrong image can brick the device. The network drops while it reboots — do not power off.</span>
    </div>

    {#if stage === 'flashing'}
      <p style="margin:0"><b>Flashing in progress…</b></p>
      <p class="hint" style="margin:6px 0 0">The router is writing the image and will reboot. This page will stop responding for a few minutes. Reconnect when the lights settle.</p>
    {:else}
      <div class="form-row"><div class="lbl">Firmware image<Help text="The sysupgrade image for your exact model (a .bin, often named *-sysupgrade.bin). Download it from the OpenWRT firmware selector for this device." /></div>
        <div class="ctl"><label class="btn" style="cursor:pointer">Choose file<input type="file" accept=".bin,.img,.gz,.itb" on:change={onFile} style="display:none" /></label>
          <span class="hint">{file ? file.name + (sizeStr ? ` · ${sizeStr}` : '') : 'No file chosen'}</span></div></div>

      {#if validMsg}
        <div class="form-row" style="border:0"><div class="lbl"></div><div class="ctl">
          <span style="color:{stage === 'ready' ? 'var(--good)' : 'var(--crit)'}">{validMsg}</span>
        </div></div>
      {/if}

      {#if stage === 'ready' || stage === 'invalid'}
        <div class="form-row"><div class="lbl">Keep settings<Help text="On: your configuration is preserved across the upgrade (recommended for a normal update). Off: a clean factory install." /></div>
          <div class="ctl"><label class="toggle"><input type="checkbox" bind:checked={keep} /><span class="track"></span><span class="knob"></span></label></div></div>
      {/if}

      <div class="form-actions">
        {#if stage === 'ready'}
          <button class="btn" on:click={cancel}>Cancel</button>
          <button class="btn primary" on:click={doFlash}>Flash now</button>
        {:else if stage === 'invalid'}
          <button class="btn" on:click={cancel}>Choose another file</button>
        {:else}
          <button class="btn primary" on:click={uploadAndCheck} disabled={!file || stage === 'checking'}>
            {stage === 'checking' ? 'Uploading & checking…' : 'Upload & verify'}
          </button>
        {/if}
      </div>
    {/if}
  </div></div>
  <details class="adv" style="max-width:720px"><summary>Advanced details</summary><div class="advb">Uploads to <span class="mono">/tmp/firmware.img</span> via <span class="mono">cgi-io</span>, validates with <span class="mono">rpc-sys upgrade_test</span>, then runs <span class="mono">rpc-sys upgrade_start</span> (<span class="mono">sysupgrade</span>). Needs the <span class="mono">rpcd-mod-rpcsys</span> and <span class="mono">cgi-io</span> packages.</div></details>
{/if}
