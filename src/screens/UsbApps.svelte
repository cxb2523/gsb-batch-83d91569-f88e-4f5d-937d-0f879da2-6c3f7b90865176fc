<script lang="ts">
  import { onMount } from 'svelte';
  import Help from '../components/Help.svelte';
  import { loadUsb, setSmb, setDlna, type UsbState } from '../lib/usb';
  import { toast } from '../lib/toast';

  let state: UsbState | null = null;
  let loading = true;
  let error = '';
  let busy = false;

  async function load() {
    loading = true;
    try { state = await loadUsb(); error = ''; }
    catch { error = 'Could not read the storage configuration.'; }
    finally { loading = false; }
  }
  onMount(load);

  // Default a share path to the first attached mount when empty.
  $: defPath = state?.mounts[0]?.mountpoint ?? '/mnt';

  async function applySmb() {
    if (!state) return;
    busy = true;
    const path = state.smb.path || defPath;
    try { await setSmb(state.smb.enabled, path, state.smb.id); toast(state.smb.enabled ? 'File sharing on' : 'File sharing off'); await load(); }
    catch { toast('Could not update file sharing'); }
    finally { busy = false; }
  }
  async function applyDlna() {
    if (!state) return;
    busy = true;
    const path = state.dlna.path || defPath;
    try { await setDlna(state.dlna.enabled, path, state.dlna.id); toast(state.dlna.enabled ? 'Media server on' : 'Media server off'); await load(); }
    catch { toast('Could not update the media server'); }
    finally { busy = false; }
  }
</script>

<div class="page-head"><div><div class="breadcrumb">Advanced Settings</div><h1>USB Storage</h1><p>Share a USB drive with your devices and stream media from it.</p></div></div>

{#if loading}
  <div class="panel"><div class="panel-b" style="color:var(--muted);text-align:center;padding:44px">Reading configuration…</div></div>
{:else if error || !state}
  <div class="panel"><div class="panel-b" style="text-align:center;padding:40px"><p style="color:var(--crit);margin:0 0 14px">{error}</p><button class="btn primary" on:click={load}>Retry</button></div></div>
{:else}
  <div class="panel" style="max-width:720px;margin-bottom:16px">
    <div class="panel-h"><h2>Attached storage</h2><span class="sub">{state.mounts.length} mounted</span></div>
    <div class="panel-b">
      {#if state.mounts.length}
        {#each state.mounts as m}
          <div class="kv"><span class="l mono">{m.mountpoint}</span><span class="r mono">{m.device} · {m.fstype}</span></div>
        {/each}
      {:else}
        <p class="hint" style="margin:0">No USB storage detected. Plug in a drive (and install <span class="mono">block-mount</span> + a filesystem package like <span class="mono">kmod-fs-ext4</span> if it doesn't mount automatically).</p>
      {/if}
    </div>
  </div>

  <div class="panel" style="max-width:720px;margin-bottom:16px">
    <div class="panel-h"><h2>Network file sharing (SMB)</h2></div>
    <div class="panel-b">
      {#if !state.smb.installed}
        <p class="hint" style="margin:0">Install <span class="mono">ksmbd</span> (or <span class="mono">samba4</span>) to share files with Windows, macOS and phones.</p>
      {:else}
        <div class="form-row"><div class="lbl">Share over the network<Help text="Makes the folder below reachable at \\\\router (SMB) from your computers and phones. Guest access is allowed; set a user in advanced config for private shares." /></div>
          <div class="ctl"><label class="toggle"><input type="checkbox" bind:checked={state.smb.enabled} /><span class="track"></span><span class="knob"></span></label></div></div>
        <div class="form-row"><div class="lbl">Folder<Help text="The folder on the attached drive to share. Defaults to the first mounted drive." /></div>
          <div class="ctl"><input type="text" bind:value={state.smb.path} placeholder={defPath} spellcheck="false" style="min-width:240px" /></div></div>
        <div class="form-actions"><button class="btn primary" on:click={applySmb} disabled={busy}>Apply</button></div>
      {/if}
    </div>
  </div>

  <div class="panel" style="max-width:720px">
    <div class="panel-h"><h2>Media server (DLNA)</h2></div>
    <div class="panel-b">
      {#if !state.dlna.installed}
        <p class="hint" style="margin:0">Install <span class="mono">minidlna</span> to stream photos, music and video to TVs and media players.</p>
      {:else}
        <div class="form-row"><div class="lbl">Stream media<Help text="Shares media from the folder below to DLNA-capable TVs, consoles and apps on your network." /></div>
          <div class="ctl"><label class="toggle"><input type="checkbox" bind:checked={state.dlna.enabled} /><span class="track"></span><span class="knob"></span></label></div></div>
        <div class="form-row"><div class="lbl">Media folder<Help text="Where your media lives on the attached drive." /></div>
          <div class="ctl"><input type="text" bind:value={state.dlna.path} placeholder={defPath} spellcheck="false" style="min-width:240px" /></div></div>
        <div class="form-actions"><button class="btn primary" on:click={applyDlna} disabled={busy}>Apply</button></div>
      {/if}
    </div>
  </div>
{/if}
