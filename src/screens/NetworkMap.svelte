<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import Icon from '../components/Icon.svelte';
  import {
    getBoard, getSysInfo, getWan, getClients, formatUptime, isPrivateIp, getPublicIp, wifiDiag,
    bandName, bandStroke, bandClass,
    type BoardInfo, type SysInfo, type WanStatus, type Client, type Band
  } from '../lib/net';

  let loading = true;
  let error = '';
  let board: BoardInfo | null = null;
  let sys: SysInfo | null = null;
  let wan: WanStatus | null = null;
  let clients: Client[] = [];
  let publicIp: string | null = null; // only looked up when the WAN address is private/CGNAT
  let diag = ''; // why Wi-Fi classification failed, if it did
  let selected: string = 'router'; // 'router' | 'internet' | client id
  let expandedBand: Band | null = null; // which band hub is expanded on the map
  let query = ''; // table search filter
  let timer: ReturnType<typeof setInterval> | undefined;

  async function loadAll() {
    try {
      const [b, s, w, c] = await Promise.all([getBoard(), getSysInfo(), getWan(), getClients()]);
      board = b; sys = s; wan = w; clients = c; diag = wifiDiag;
      error = '';
      if (isPrivateIp(w.ipv4)) publicIp = await getPublicIp();
    } catch (e) {
      error = 'Could not read status from the router. Check the connection and try again.';
    } finally {
      loading = false;
    }
  }
  async function refreshLight() {
    try {
      const [s, w, c] = await Promise.all([getSysInfo(), getWan(), getClients()]);
      sys = s; wan = w; clients = c; diag = wifiDiag;
    } catch { /* keep last good values */ }
  }

  onMount(() => {
    loadAll();
    timer = setInterval(refreshLight, 5000);
  });
  onDestroy(() => clearInterval(timer));

  // ---- topology geometry ----
  // The map groups devices by band into "hubs" so it stays readable no matter
  // how many clients there are. A hub can be expanded to reveal its devices.
  const VW = 800, RX = 400, Y = 360;
  const BAND_ORDER: Band[] = ['5', '24', '6', 'wired', '?'];
  const HUB_SPREAD = 660, DEV_SPREAD = 720, DEV_PER_ROW = 8, ROW_GAP = 92;

  // Build the list of non-empty band groups, in a stable display order.
  $: groups = BAND_ORDER
    .map((band) => ({ band, items: clients.filter((c) => c.band === band) }))
    .filter((g) => g.items.length > 0);

  // Devices revealed under the currently expanded hub.
  $: expandedItems = expandedBand ? clients.filter((c) => c.band === expandedBand) : [];
  $: expandedRows = Math.ceil(expandedItems.length / DEV_PER_ROW) || 0;
  // Taller canvas only when a hub is expanded and spills onto extra rows.
  $: svgH = 470 + (expandedBand ? 70 + Math.max(0, expandedRows - 1) * ROW_GAP : 0);

  function spreadX(i: number, n: number, spread: number) {
    return n <= 1 ? RX : RX - spread / 2 + (spread / (n - 1)) * i;
  }
  function hubX(i: number, n: number) {
    return spreadX(i, n, HUB_SPREAD);
  }
  function devX(i: number) {
    const col = i % DEV_PER_ROW;
    const row = Math.floor(i / DEV_PER_ROW);
    const len = Math.min(DEV_PER_ROW, expandedItems.length - row * DEV_PER_ROW);
    return spreadX(col, len, DEV_SPREAD);
  }
  function devY(i: number) {
    return Y + 150 + Math.floor(i / DEV_PER_ROW) * ROW_GAP;
  }
  function toggleBand(b: Band) {
    expandedBand = expandedBand === b ? null : b;
  }

  function bars(sig: number) {
    return [1, 2, 3, 4].map((n) => n <= sig);
  }
  const selectedClient = () => clients.find((c) => c.id === selected) || null;

  // ---- table search ----
  $: filtered = query.trim()
    ? clients.filter((c) => {
        const q = query.toLowerCase();
        return (
          c.name.toLowerCase().includes(q) ||
          c.ip.toLowerCase().includes(q) ||
          c.mac.toLowerCase().includes(q)
        );
      })
    : clients;
</script>

<div class="page-head">
  <div>
    <div class="breadcrumb">General</div>
    <h1>Network Map</h1>
    <p>Live view of your router, the internet connection, and every connected device.</p>
  </div>
</div>

{#if loading}
  <div class="panel"><div class="panel-b" style="text-align:center;color:var(--muted);padding:48px">Reading status from the router…</div></div>
{:else if error}
  <div class="panel"><div class="panel-b" style="text-align:center;padding:40px">
    <p style="color:var(--crit);margin:0 0 14px">{error}</p>
    <button class="btn primary" on:click={() => { loading = true; loadAll(); }}>Retry</button>
  </div></div>
{:else}
  <div class="tiles">
    <div class="tile">
      <div class="k"><Icon name="i-wan" size={15} /> Internet</div>
      <div class="v" style="font-size:16px;margin-top:11px;color:{wan?.up ? 'var(--good)' : 'var(--crit)'}">{wan?.up ? 'Connected' : 'Offline'}</div>
      {#if isPrivateIp(wan?.ipv4)}
        <div class="hint mono" style="margin-top:4px">{publicIp ?? wan?.ipv4}</div>
        <div class="hint" style="margin-top:2px">behind carrier NAT</div>
      {:else}
        <div class="hint mono" style="margin-top:4px">{wan?.ipv4 ?? '—'}</div>
      {/if}
    </div>
    <div class="tile">
      <div class="k"><Icon name="i-clients" size={15} /> Clients</div>
      <div class="v">{clients.length} <small>online</small></div>
      {#if diag && clients.length && clients.every((c) => c.band === '?')}
        <div class="hint" style="margin-top:4px" title={diag}>Wi-Fi status unavailable: {diag}</div>
      {/if}
    </div>
    <div class="tile">
      <div class="k"><Icon name="i-cpu" size={15} /> Load (1m)</div>
      <div class="v">{sys?.load1 ?? 0}</div>
    </div>
    <div class="tile">
      <div class="k"><Icon name="i-mem" size={15} /> Memory</div>
      <div class="v">{sys?.memUsedPct ?? 0}<small>%</small></div>
      <div class="meter"><i style="width:{sys?.memUsedPct ?? 0}%"></i></div>
    </div>
    <div class="tile">
      <div class="k"><Icon name="i-clock" size={15} /> Uptime</div>
      <div class="v" style="font-size:16px;margin-top:11px">{formatUptime(sys?.uptimeSec ?? 0)}</div>
    </div>
  </div>

  <div class="grid map-grid">
    <div class="panel">
      <div class="panel-h"><h2>Topology</h2><span class="sub">{wan?.device || 'wan'}</span></div>
      <div class="mapwrap">
        <svg class="topo" viewBox="0 0 {VW} {svgH}" role="img" aria-label="Network topology">
          <!-- internet → router link -->
          <line class="link ilink" x1="400" y1="82" x2="400" y2="165" stroke-width="2.5" />
          <!-- router → band hub links -->
          {#each groups as g, i}
            <path class="link" d={`M400,245 C400,300 ${hubX(i, groups.length)},300 ${hubX(i, groups.length)},${Y - 34}`} stroke={bandStroke[g.band]} stroke-width="2.5" />
          {/each}
          <!-- expanded hub → device links -->
          {#each expandedItems as c, i}
            <path class="link" d={`M${hubX(groups.findIndex((g) => g.band === expandedBand), groups.length)},${Y + 34} C${hubX(groups.findIndex((g) => g.band === expandedBand), groups.length)},${Y + 110} ${devX(i)},${devY(i) - 70} ${devX(i)},${devY(i) - 26}`} stroke={bandStroke[c.band]} stroke-width="2" opacity="0.8" />
          {/each}

          <!-- internet -->
          <g class="node" class:sel={selected === 'internet'} role="button" tabindex="0"
             on:click={() => (selected = 'internet')} on:keydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selected = 'internet'; } }}>
            <circle class="nbg" cx="400" cy="52" r="30" />
            <use class="inet-ic" href="#d-cloud" x="384" y="36" width="32" height="32" />
            <text x="400" y="100" text-anchor="middle" font-size="12">Internet</text>
          </g>
          <!-- router -->
          <g class="node" class:sel={selected === 'router'} role="button" tabindex="0"
             on:click={() => (selected = 'router')} on:keydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selected = 'router'; } }}>
            <circle class="nbg-router" cx="400" cy="205" r="40" />
            <use class="router-ic" href="#d-router" x="378" y="183" width="44" height="44" />
            <text x="400" y="268" text-anchor="middle" font-size="12.5" font-weight="700">{board?.model ?? 'Router'}</text>
          </g>
          <!-- band hubs -->
          {#each groups as g, i}
            <g class="node" class:sel={expandedBand === g.band} role="button" tabindex="0"
               aria-label={`${bandName[g.band]} — ${g.items.length} devices`} aria-pressed={expandedBand === g.band}
               on:click={() => toggleBand(g.band)}
               on:keydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleBand(g.band); } }}>
              <circle class="nbg hub" cx={hubX(i, groups.length)} cy={Y} r="30" style="--band:{bandStroke[g.band]}" />
              <text x={hubX(i, groups.length)} y={Y + 6} text-anchor="middle" font-size="18" font-weight="700" fill={bandStroke[g.band]}>{g.items.length}</text>
              <text class="nlabel" x={hubX(i, groups.length)} y={Y + 50} text-anchor="middle" font-size="11">{bandName[g.band]}</text>
            </g>
          {/each}
          <!-- expanded devices -->
          {#each expandedItems as c, i}
            <g class="node" class:sel={selected === c.id} role="button" tabindex="0" aria-label={c.name}
               on:click={() => (selected = c.id)} on:keydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selected = c.id; } }}>
              <circle class="nbg" cx={devX(i)} cy={devY(i)} r="24" />
              <use href={'#' + c.kind} x={devX(i) - 13} y={devY(i) - 13} width="26" height="26" color={bandStroke[c.band]} />
              <text class="nlabel" x={devX(i)} y={devY(i) + 40} text-anchor="middle" font-size="10.5">{c.name.split(' ')[0]}</text>
            </g>
          {/each}
        </svg>
        <div class="legend">
          <span><i class="lg" style="background:var(--band5,#0fb5c4)"></i> 5 GHz</span>
          <span><i class="lg" style="background:#f79009"></i> 2.4 GHz</span>
          <span><i class="lg" style="background:#17b26a"></i> Wired</span>
          <span style="opacity:.8">{expandedBand ? 'Tap a hub to collapse' : 'Tap a hub to expand'}</span>
        </div>
      </div>
    </div>

    <div class="panel detail">
      <div class="panel-h"><h2>{selected === 'router' ? 'This Router' : selected === 'internet' ? 'Internet' : 'Device'}</h2></div>
      <div class="panel-b">
        {#if selected === 'router'}
          <div class="big"><div class="devicon"><Icon name="d-router" size={24} /></div><div><b>{board?.model}</b><div class="m">{board?.hostname}</div></div></div>
          <div class="kv"><span class="l">Firmware</span><span class="r">{board?.firmware}</span></div>
          <div class="kv"><span class="l">WAN IP</span><span class="r">{wan?.ipv4 ?? '—'}</span></div>
          <div class="kv"><span class="l">Gateway</span><span class="r">{wan?.gateway ?? '—'}</span></div>
          <div class="kv"><span class="l">Uptime</span><span class="r">{formatUptime(sys?.uptimeSec ?? 0)}</span></div>
          <div class="kv"><span class="l">Clients</span><span class="r">{clients.length} online</span></div>
        {:else if selected === 'internet'}
          <div class="big"><div class="devicon"><Icon name="d-cloud" size={24} /></div><div><b>WAN · {wan?.up ? 'Connected' : 'Offline'}</b><div class="m">{wan?.proto}</div></div></div>
          {#if isPrivateIp(wan?.ipv4)}
            <div class="kv"><span class="l">Public IP</span><span class="r">{publicIp ?? '—'}</span></div>
            <div class="kv"><span class="l">Router WAN IP</span><span class="r">{wan?.ipv4}</span></div>
            <div class="hint" style="margin:6px 0 10px">Your internet provider puts this router behind carrier-grade NAT (the WAN address is private). Port forwarding, DMZ and Dynamic DNS can't be reached from the internet on this connection; a VPN such as Tailscale or WireGuard with an outside peer still works.</div>
          {:else}
            <div class="kv"><span class="l">Public IP</span><span class="r">{wan?.ipv4 ?? '—'}</span></div>
          {/if}
          <div class="kv"><span class="l">Gateway</span><span class="r">{wan?.gateway ?? '—'}</span></div>
          <div class="kv"><span class="l">DNS</span><span class="r">{wan?.dns?.join(' · ') || '—'}</span></div>
          <div class="kv"><span class="l">Uptime</span><span class="r">{formatUptime(wan?.uptimeSec ?? 0)}</span></div>
        {:else if selectedClient()}
          {@const c = selectedClient()}
          <div class="big"><div class="devicon"><Icon name={c!.kind} size={24} /></div><div><b>{c!.name}</b><div class="m mono">{c!.mac}</div></div></div>
          <div class="kv"><span class="l">Connection</span><span class="r"><span class="bandchip {bandClass[c!.band]}">{bandName[c!.band]}</span></span></div>
          <div class="kv"><span class="l">IP address</span><span class="r">{c!.ip}</span></div>
          <div class="kv"><span class="l">Signal</span><span class="r"><span class="sig">{#each bars(c!.signal) as on, bi}<i class:on style="height:{(bi + 1) * 3 + 2}px"></i>{/each}</span></span></div>
        {:else}
          <p class="hint">Select a device on the map.</p>
        {/if}
      </div>
    </div>
  </div>

  <div class="panel" style="margin-top:18px">
    <div class="panel-h">
      <h2>Connected Clients</h2>
      <input
        class="tsearch"
        type="search"
        placeholder="Search name, IP, or MAC…"
        bind:value={query}
        aria-label="Search connected clients" />
      <span class="sub">{filtered.length} of {clients.length} devices</span>
    </div>
    <div style="overflow-x:auto">
      <table class="clients">
        <thead><tr><th>Device</th><th>IP Address</th><th>Connection</th><th>Signal</th></tr></thead>
        <tbody>
          {#each filtered as c}
            <tr class:sel={selected === c.id} on:click={() => (selected = c.id)}>
              <td><div class="cname"><span class="mi"><Icon name={c.kind} size={17} /></span><span><b>{c.name}</b><small>{c.mac}</small></span></div></td>
              <td class="mono">{c.ip}</td>
              <td><span class="bandchip {bandClass[c.band]}">{bandName[c.band]}</span></td>
              <td><span class="sig">{#each bars(c.signal) as on, bi}<i class:on style="height:{(bi + 1) * 3 + 2}px"></i>{/each}</span></td>
            </tr>
          {/each}
          {#if !clients.length}
            <tr><td colspan="4" style="color:var(--muted);padding:22px">No clients seen yet.</td></tr>
          {:else if !filtered.length}
            <tr><td colspan="4" style="color:var(--muted);padding:22px">No devices match “{query}”.</td></tr>
          {/if}
        </tbody>
      </table>
    </div>
  </div>
{/if}
