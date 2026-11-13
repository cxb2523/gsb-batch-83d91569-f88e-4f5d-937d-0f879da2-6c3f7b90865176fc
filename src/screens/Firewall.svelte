<script lang="ts">
  import { onMount } from 'svelte';
  import Help from '../components/Help.svelte';
  import { loadFirewall, saveZone, loadRules, addRule, saveRule, deleteRule, type FwZone, type FwForward, type FwRule, type Policy } from '../lib/firewall';
  import { toast } from '../lib/toast';
  import { startRollbackConfirm } from '../lib/confirm';

  let zones: FwZone[] = [];
  let originals: FwZone[] = [];
  let forwards: FwForward[] = [];
  let rules: FwRule[] = [];
  let loading = true;
  let error = '';
  let busy = false;
  const POLICIES: Policy[] = ['ACCEPT', 'REJECT', 'DROP'];
  const PROTOS = ['any', 'tcp', 'udp', 'tcp udp'];

  let draft: Omit<FwRule, 'id'> | null = null;
  function newRule() {
    draft = { name: '', src: zones[0]?.name ?? 'lan', dest: 'wan', proto: 'any', destPort: '', target: 'ACCEPT', enabled: true, srcMac: '', srcIp: '', srcPort: '' };
  }

  async function load() {
    loading = true;
    try {
      const r = await loadFirewall();
      zones = r.zones;
      forwards = r.forwards;
      rules = await loadRules();
      originals = zones.map((z) => ({ ...z }));
      error = '';
    } catch {
      error = 'Could not read the firewall configuration.';
    } finally {
      loading = false;
    }
  }
  onMount(load);

  function dirty(i: number) {
    return originals[i] && JSON.stringify(zones[i]) !== JSON.stringify(originals[i]);
  }
  async function apply(i: number) {
    busy = true;
    try {
      await saveZone(zones[i]);
      const snap = { ...zones[i] };
      startRollbackConfirm('Firewall zone "' + zones[i].name + '"', {
        onKeep: () => { originals[i] = snap; originals = originals; },
        onRevert: load
      });
    } catch {
      toast('Could not apply changes');
    } finally {
      busy = false;
    }
  }

  async function saveDraft() {
    if (!draft || !draft.name.trim()) { toast('Give the rule a name'); return; }
    busy = true;
    try { await addRule(draft); draft = null; toast('Rule added'); await load(); }
    catch { toast('Could not add the rule'); }
    finally { busy = false; }
  }
  async function toggleRule(r: FwRule) {
    busy = true;
    try { await saveRule({ ...r, enabled: !r.enabled }); await load(); }
    catch { toast('Could not update the rule'); }
    finally { busy = false; }
  }
  async function removeRule(r: FwRule) {
    busy = true;
    try { await deleteRule(r.id); toast('Rule removed'); await load(); }
    catch { toast('Could not remove the rule'); }
    finally { busy = false; }
  }
</script>

<div class="page-head">
  <div><div class="breadcrumb">Advanced Settings</div><h1>Firewall</h1><p>Control how traffic is allowed between your networks and the internet.</p></div>
</div>

{#if loading}
  <div class="panel"><div class="panel-b" style="color:var(--muted);text-align:center;padding:44px">Reading firewall configuration…</div></div>
{:else if error}
  <div class="panel"><div class="panel-b" style="text-align:center;padding:40px"><p style="color:var(--crit);margin:0 0 14px">{error}</p><button class="btn primary" on:click={load}>Retry</button></div></div>
{:else}
  {#each zones as z, i}
    <div class="panel" style="margin-bottom:16px">
      <div class="panel-h"><h2><span class="chip">{z.name}</span></h2>
        <span class="sub">{z.networks.join(', ') || 'no networks'}</span>
      </div>
      <div class="panel-b">
        <div class="form-row">
          <div class="lbl">Incoming<Help text="Traffic from this zone to the router itself. REJECT is safe for wan; ACCEPT is usual for lan." /></div>
          <div class="ctl"><select bind:value={zones[i].input}>{#each POLICIES as p}<option value={p}>{p}</option>{/each}</select></div>
        </div>
        <div class="form-row">
          <div class="lbl">Outgoing<Help text="Traffic from the router out to this zone. Normally ACCEPT." /></div>
          <div class="ctl"><select bind:value={zones[i].output}>{#each POLICIES as p}<option value={p}>{p}</option>{/each}</select></div>
        </div>
        <div class="form-row">
          <div class="lbl">Forward<Help text="Traffic between devices within this zone. REJECT by default unless the zone needs internal routing." /></div>
          <div class="ctl"><select bind:value={zones[i].forward}>{#each POLICIES as p}<option value={p}>{p}</option>{/each}</select></div>
        </div>
        <div class="form-row">
          <div class="lbl">Masquerade (NAT)<Help text="Rewrites source addresses leaving this zone. On for wan so your LAN shares one public address; off for internal zones." /></div>
          <div class="ctl"><label class="toggle"><input type="checkbox" bind:checked={zones[i].masq} /><span class="track"></span><span class="knob"></span></label></div>
        </div>
        <div class="form-actions"><button class="btn primary" on:click={() => apply(i)} disabled={!dirty(i) || busy}>Apply</button></div>
      </div>
    </div>
  {/each}

  <div class="panel" style="margin-bottom:16px">
    <div class="panel-h"><h2>Traffic rules</h2>
      <button class="btn sm" on:click={newRule} disabled={busy || !!draft}>+ Add rule</button>
    </div>
    <div class="panel-b" style="padding-top:0">
      <div style="overflow-x:auto"><table class="clients">
        <thead><tr><th>Name</th><th>From → To</th><th>Match</th><th>Action</th><th style="text-align:right"></th></tr></thead>
        <tbody>
          {#if draft}
            <tr>
              <td><input type="text" bind:value={draft.name} placeholder="e.g. Allow SSH" style="min-width:130px" /></td>
              <td>
                <select bind:value={draft.src}>{#each zones as z}<option value={z.name}>{z.name}</option>{/each}</select>
                →
                <select bind:value={draft.dest}>{#each zones as z}<option value={z.name}>{z.name}</option>{/each}</select>
              </td>
              <td>
                <select bind:value={draft.proto}>{#each PROTOS as p}<option value={p}>{p}</option>{/each}</select>
                <input type="text" bind:value={draft.destPort} placeholder="port" style="width:70px" />
              </td>
              <td><select bind:value={draft.target}>{#each POLICIES as p}<option value={p}>{p}</option>{/each}</select></td>
              <td style="text-align:right;white-space:nowrap">
                <button class="btn sm primary" on:click={saveDraft} disabled={busy}>Save</button>
                <button class="btn sm ghost" on:click={() => (draft = null)} disabled={busy}>✕</button>
              </td>
            </tr>
            <tr class="srcrow">
              <td class="hint">Limit source <span class="opt">(optional)</span></td>
              <td colspan="4">
                <input type="text" bind:value={draft.srcMac} placeholder="MAC" style="width:150px" spellcheck="false" />
                <input type="text" bind:value={draft.srcIp} placeholder="IP" style="width:130px" spellcheck="false" />
                <input type="text" bind:value={draft.srcPort} placeholder="src port" style="width:80px" spellcheck="false" />
              </td>
            </tr>
          {/if}
          {#each rules as r (r.id)}
            <tr class:offline={!r.enabled}>
              <td><b>{r.name || '(unnamed)'}</b></td>
              <td>
                {r.src || 'any'} → {r.dest || 'any'}
                {#if r.srcMac || r.srcIp || r.srcPort}<div class="hint mono">from {[r.srcMac, r.srcIp, r.srcPort && ':' + r.srcPort].filter(Boolean).join(' ')}</div>{/if}
              </td>
              <td class="mono">{r.proto}{#if r.destPort} :{r.destPort}{/if}</td>
              <td><span class="chip">{r.target}</span></td>
              <td style="text-align:right;white-space:nowrap">
                <button class="btn sm" on:click={() => toggleRule(r)} disabled={busy}>{r.enabled ? 'Disable' : 'Enable'}</button>
                <button class="btn sm ghost" title="Delete rule" on:click={() => removeRule(r)} disabled={busy}>✕</button>
              </td>
            </tr>
          {/each}
          {#if !rules.length && !draft}
            <tr><td colspan="5" style="color:var(--muted);padding:18px">No custom rules yet. Device blocks and parental schedules are managed on their own screens.</td></tr>
          {/if}
        </tbody>
      </table></div>
    </div>
  </div>

  <div class="panel">
    <div class="panel-h"><h2>Zone forwarding</h2><span class="sub">who can reach whom</span></div>
    <div class="panel-b">
      {#if forwards.length}
        {#each forwards as f}<span class="chip">{f.src} → {f.dest}</span>{/each}
      {:else}<span class="hint">No forwarding rules.</span>{/if}
    </div>
  </div>
  <details class="adv" style="max-width:860px"><summary>Advanced details</summary><div class="advb">Zones and policies map to <span class="mono">config zone</span> / <span class="mono">forwarding</span> in <span class="mono">/etc/config/firewall</span>, compiled to nftables by fw4. Traffic rules above are <span class="mono">config rule</span> entries; port forwards live on their own screen.</div></details>
{/if}

<style>
  .btn.sm { padding: 6px 10px; font-size: 12px; }
  .btn.sm.ghost { color: var(--muted); }
  tr.offline b { color: var(--muted); }
  tr.srcrow td { border-top: 0; padding-top: 0; }
  tr.srcrow input { margin-right: 6px; }
  .opt { color: var(--muted); font-weight: 400; }
</style>
