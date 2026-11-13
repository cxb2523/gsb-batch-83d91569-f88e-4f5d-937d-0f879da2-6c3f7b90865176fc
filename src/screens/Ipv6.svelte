<script lang="ts">
  import { onMount } from 'svelte';
  import Help from '../components/Help.svelte';
  import { loadIpv6, saveIpv6, type Ipv6Cfg } from '../lib/ipv6';
  import { toast } from '../lib/toast';

  let cfg: Ipv6Cfg | null = null;
  let orig = '';
  let loading = true;
  let error = '';
  let busy = false;
  let newDns = '';
  let dnsErr = '';

  async function load() {
    loading = true;
    try { cfg = await loadIpv6(); orig = JSON.stringify(cfg); error = ''; }
    catch { error = 'Could not read the IPv6 configuration.'; }
    finally { loading = false; }
  }
  onMount(load);
  $: dirty = cfg ? JSON.stringify(cfg) !== orig : false;

  // Accepts a plain IPv6 address (no port/prefix). Keeps the check simple and
  // forgiving: hex groups + "::" compression, optionally a zone id.
  function isIpv6(s: string): boolean {
    const v = s.trim();
    if (!v || v.length > 45 || !v.includes(':')) return false;
    return /^[0-9a-fA-F:]+(%[0-9a-zA-Z]+)?$/.test(v) && (v.match(/::/g)?.length ?? 0) <= 1;
  }

  function addDns() {
    if (!cfg) return;
    const v = newDns.trim();
    if (!isIpv6(v)) { dnsErr = 'Enter a valid IPv6 address (e.g. 2606:4700:4700::1111).'; return; }
    if (cfg.dns.includes(v)) { dnsErr = 'That address is already in the list.'; return; }
    cfg.dns = [...cfg.dns, v];
    newDns = '';
    dnsErr = '';
  }
  function removeDns(i: number) {
    if (!cfg) return;
    cfg.dns = cfg.dns.filter((_, idx) => idx !== i);
  }

  async function apply() {
    if (!cfg) return; busy = true;
    try { await saveIpv6(cfg); orig = JSON.stringify(cfg); toast('IPv6 settings applied'); }
    catch { toast('Could not apply changes'); }
    finally { busy = false; }
  }
</script>

<div class="page-head"><div><div class="breadcrumb">Advanced Settings</div><h1>IPv6</h1><p>The newer internet addressing, alongside IPv4.</p></div></div>

{#if loading}
  <div class="panel"><div class="panel-b" style="color:var(--muted);text-align:center;padding:44px">Reading configuration…</div></div>
{:else if error || !cfg}
  <div class="panel"><div class="panel-b" style="text-align:center;padding:40px"><p style="color:var(--crit);margin:0 0 14px">{error}</p><button class="btn primary" on:click={load}>Retry</button></div></div>
{:else}
  <div class="panel" style="max-width:720px"><div class="panel-b">
    {#if cfg.hasWan6}
      <div class="form-row"><div class="lbl">IPv6 on the internet connection<Help text="Turn off only if your ISP has no IPv6 or it causes trouble." /></div><div class="ctl"><label class="toggle"><input type="checkbox" bind:checked={cfg.wanEnabled} /><span class="track"></span><span class="knob"></span></label></div></div>
    {:else}
      <p class="hint" style="margin:0 0 14px">No IPv6 WAN interface (<span class="mono">wan6</span>) is configured, so there's nothing to enable on the internet side here.</p>
    {/if}
    <div class="form-row"><div class="lbl">Hand out IPv6 to devices<Help text="Server: the router advertises IPv6 and runs DHCPv6. Relay: pass the ISP's IPv6 straight through. Off: no IPv6 on the LAN." /></div>
      <div class="ctl"><select bind:value={cfg.lanMode}><option value="server">Server (recommended)</option><option value="relay">Relay</option><option value="disabled">Off</option></select></div></div>

    {#if cfg.lanMode === 'server'}
      <div class="form-row" style="align-items:flex-start">
        <div class="lbl">IPv6 DNS servers<Help text="IPv6 DNS addresses the router announces to devices (via Router Advertisements and DHCPv6). Leave empty to announce the router itself as the DNS server." /></div>
        <div class="ctl" style="flex-direction:column;align-items:stretch;gap:8px;width:100%;max-width:360px">
          {#each cfg.dns as addr, i}
            <div style="display:flex;align-items:center;gap:8px">
              <span class="mono" style="flex:1;overflow:hidden;text-overflow:ellipsis">{addr}</span>
              <button class="btn" type="button" on:click={() => removeDns(i)} aria-label={`Remove ${addr}`}>Remove</button>
            </div>
          {/each}
          {#if !cfg.dns.length}
            <p class="hint" style="margin:0">None set — the router announces itself as the IPv6 DNS server.</p>
          {/if}
          <div style="display:flex;align-items:center;gap:8px">
            <input type="text" class="mono" placeholder="2606:4700:4700::1111" bind:value={newDns}
                   on:input={() => (dnsErr = '')}
                   on:keydown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addDns(); } }}
                   style="flex:1" />
            <button class="btn" type="button" on:click={addDns}>Add</button>
          </div>
          {#if dnsErr}<p class="hint" style="margin:0;color:var(--crit)">{dnsErr}</p>{/if}
        </div>
      </div>
    {/if}

    <div class="form-actions"><button class="btn primary" on:click={apply} disabled={!dirty || busy}>{busy ? 'Applying…' : 'Apply'}</button></div>
  </div></div>
{/if}
