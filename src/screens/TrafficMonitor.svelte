<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { getDevices, getWan, formatBytes, type DevStat } from '../lib/net';

  const N = 60;
  let down: number[] = Array(N).fill(0); // Mbps
  let up: number[] = Array(N).fill(0);
  let curDown = 0, curUp = 0, peak = 0;
  let wanDev = '';
  let rows: { name: string; down: number; up: number; total: number }[] = [];
  let error = '';

  let prev = new Map<string, { rx: number; tx: number }>();
  let prevTs = 0;
  let canvas: HTMLCanvasElement;
  let timer: ReturnType<typeof setInterval> | undefined;

  function css(v: string) {
    return getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  }

  async function sample() {
    try {
      if (!wanDev) wanDev = (await getWan()).device || '';
      const devs = await getDevices();
      const now = performance.now();
      const dt = prevTs ? (now - prevTs) / 1000 : 0;

      const next = new Map<string, { rx: number; tx: number }>();
      const table: typeof rows = [];
      let wd = 0, wu = 0;

      for (const d of devs) {
        next.set(d.name, { rx: d.rxBytes, tx: d.txBytes });
        const p = prev.get(d.name);
        let dMbps = 0, uMbps = 0;
        if (p && dt > 0) {
          dMbps = Math.max(0, ((d.rxBytes - p.rx) * 8) / dt / 1e6);
          uMbps = Math.max(0, ((d.txBytes - p.tx) * 8) / dt / 1e6);
        }
        table.push({ name: d.name, down: dMbps, up: uMbps, total: d.rxBytes + d.txBytes });
        if (d.name === wanDev) { wd = dMbps; wu = uMbps; }
      }
      prev = next; prevTs = now;

      curDown = wd; curUp = wu; peak = Math.max(peak, wd);
      down = [...down.slice(1), wd];
      up = [...up.slice(1), wu];
      rows = table.filter((r) => r.total > 0).sort((a, b) => b.total - a.total).slice(0, 10);
      error = '';
      draw();
    } catch {
      error = 'Could not read traffic counters from the router.';
    }
  }

  function draw() {
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const W = canvas.width, H = canvas.height, padL = 46, padB = 22, padT = 12, padR = 10;
    const gw = W - padL - padR, gh = H - padT - padB;
    ctx.clearRect(0, 0, W, H);
    const maxV = Math.max(10, Math.ceil(Math.max(...down, ...up) / 10) * 10);
    ctx.font = "12px ui-monospace,Menlo,Consolas,monospace";
    ctx.textBaseline = 'middle';
    const line = css('--line'), muted = css('--muted');
    for (let i = 0; i <= 4; i++) {
      const y = padT + gh * (i / 4);
      ctx.strokeStyle = line; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(W - padR, y); ctx.stroke();
      ctx.fillStyle = muted; ctx.textAlign = 'right';
      ctx.fillText(String(Math.round(maxV * (1 - i / 4))), padL - 8, y);
    }
    ctx.textAlign = 'center'; ctx.fillStyle = muted;
    ctx.fillText('Mbps · now', W - padR - 34, H - 8);
    ctx.fillText('-60s', padL + 14, H - 8);
    const X = (i: number) => padL + gw * (i / (N - 1));
    const Y = (v: number) => padT + gh * (1 - v / maxV);
    const series = (arr: number[], stroke: string, fill: string) => {
      ctx.beginPath(); ctx.moveTo(X(0), Y(arr[0]));
      for (let i = 1; i < N; i++) ctx.lineTo(X(i), Y(arr[i]));
      ctx.lineTo(X(N - 1), padT + gh); ctx.lineTo(X(0), padT + gh); ctx.closePath();
      const g = ctx.createLinearGradient(0, padT, 0, padT + gh);
      g.addColorStop(0, fill); g.addColorStop(1, 'transparent');
      ctx.fillStyle = g; ctx.fill();
      ctx.beginPath(); ctx.moveTo(X(0), Y(arr[0]));
      for (let i = 1; i < N; i++) ctx.lineTo(X(i), Y(arr[i]));
      ctx.strokeStyle = stroke; ctx.lineWidth = 2; ctx.lineJoin = 'round'; ctx.stroke();
      ctx.beginPath(); ctx.arc(X(N - 1), Y(arr[N - 1]), 3.5, 0, 7); ctx.fillStyle = stroke; ctx.fill();
    };
    series(down, css('--accent') || '#0fb5c4', 'rgba(15,181,196,.26)');
    series(up, css('--good') || '#17b26a', 'rgba(23,178,106,.20)');
  }

  onMount(() => {
    sample();
    timer = setInterval(sample, 1000);
    const ro = () => draw();
    window.addEventListener('resize', ro);
    return () => window.removeEventListener('resize', ro);
  });
  onDestroy(() => clearInterval(timer));
</script>

<div class="page-head">
  <div>
    <div class="breadcrumb">General</div>
    <h1>Traffic Monitor</h1>
    <p>Live throughput on your internet connection, read from the interface counters every second.</p>
  </div>
</div>

{#if error}
  <div class="panel"><div class="panel-b" style="color:var(--crit)">{error}</div></div>
{:else}
  <div class="traffic-big">
    <div class="tbox"><div class="k"><i style="background:var(--accent)"></i> Download</div><div class="v">{curDown.toFixed(1)}<small> Mbps</small></div></div>
    <div class="tbox"><div class="k"><i style="background:var(--good)"></i> Upload</div><div class="v">{curUp.toFixed(1)}<small> Mbps</small></div></div>
    <div class="tbox"><div class="k">Peak download</div><div class="v">{peak.toFixed(1)}<small> Mbps</small></div></div>
    <div class="tbox"><div class="k">WAN device</div><div class="v" style="font-size:18px">{wanDev || '—'}</div></div>
  </div>

  <div class="panel">
    <div class="panel-h"><h2>Throughput</h2><span class="sub">last 60 s · Mbps</span></div>
    <div class="chartwrap"><canvas bind:this={canvas} width="1000" height="260"></canvas></div>
  </div>

  <div class="panel" style="margin-top:18px">
    <div class="panel-h"><h2>Interfaces</h2><span class="sub">totals since boot</span></div>
    <div style="overflow-x:auto">
      <table class="clients">
        <thead><tr><th>Interface</th><th>Download</th><th>Upload</th><th>Total transferred</th></tr></thead>
        <tbody>
          {#each rows as r}
            <tr style="cursor:default">
              <td class="mono"><b style="font-weight:600">{r.name}</b></td>
              <td class="mono">{r.down.toFixed(1)} Mbps</td>
              <td class="mono">{r.up.toFixed(1)} Mbps</td>
              <td class="mono">{formatBytes(r.total)}</td>
            </tr>
          {/each}
          {#if !rows.length}
            <tr><td colspan="4" style="color:var(--muted);padding:22px">Collecting counters…</td></tr>
          {/if}
        </tbody>
      </table>
    </div>
  </div>
  <p class="hint" style="margin-top:12px">Per-client usage history needs an accounting package (nlbwmon or collectd); this view uses live interface counters, which every build has.</p>
{/if}
