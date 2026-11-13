"use strict";
/* MeshAtlas UI: flat map + node list + details + event log + latency timeline. All data comes from api/ on the same origin. */

const $ = (id) => document.getElementById(id);
const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ESC[c]);
// store and prefs live in prefs.js, t() in i18n.js

let S = null;                       // latest api/state
let view = "map";                   // map: overview; node: detail page (#/node/<id>)
let upt = null;                     // api/uptime (24 h)
let logFilter = store.get("ma.logf", "all");   // all | alert | sel
const bootAt = Date.now() / 1000;
let sel = store.get("ma.sel", null);
let tab = store.get("ma.tab", "overview");
const ctrUi = { q: "", mode: "all", open: new Map() };
let showSysSvc = false;
let mapMode = store.get("ma.mode", "node");     // node: links of the selected node; mesh: all; matrix: table
let openLoc = null;                 // location whose card is open on the map (all collapsed by default)
let rangeH = store.get("ma.range", 24);
const openCtr = new Set();
const openSvc = new Set();
let hist = { node: null, data: null, at: 0, hours: 0 };
let land = null;
const M = { W: 0, H: 0, proj: null, sig: "" };
let lastEventId = 0;
let detailSig = "";
let apiOk = true;

/* ---------- formatting ---------- */
const fmtMs = (ms) => (ms == null ? "—" : ms < 10 ? ms.toFixed(1) + "ms" : Math.round(ms) + "ms");
const tier = (ms) => (ms == null ? 3 : ms < 60 ? 0 : ms < 150 ? 1 : 2);
function fmtDur(sec) {
  if (sec == null) return "—";
  const d = Math.floor(sec / 86400), h = Math.floor((sec % 86400) / 3600), m = Math.floor((sec % 3600) / 60);
  if (d) return t("{d}d {h}h", { d, h });
  if (h) return t("{h}h {m}m", { h, m });
  return t("{m}m", { m });
}
function fmtAgo(ts) {
  if (!ts) return "—";
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return t("{n}s ago", { n: Math.round(s) });
  if (s < 3600) return t("{n} min ago", { n: Math.round(s / 60) });
  if (s < 86400) return t("{n}h ago", { n: Math.round(s / 3600) });
  return t("{n}d ago", { n: Math.round(s / 86400) });
}
const gib = (b) => (b / 2 ** 30).toFixed(b >= 100 * 2 ** 30 ? 0 : 1);
const pct = (u, t) => (t ? (100 * u) / t : null);
const hhmmss = (ts) => new Date(ts * 1000).toLocaleTimeString("en-GB", { hour12: false });
const meter3 = (ms) => {
  const t = tier(ms);
  const f = t === 0 ? 3 : t === 1 ? 2 : t === 2 ? 1 : 0;
  return `<span class="meter3" aria-hidden="true">${[0, 1, 2].map((i) => `<i class="${i < f ? "f" : ""}"></i>`).join("")}</span>`;
};
function spark(points, w = 64, h = 16, stroke = "#9a9a9a") {
  const pts = (points || []).filter((p) => p[1] != null);
  if (pts.length < 2) return `<svg width="${w}" height="${h}"></svg>`;
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const sx = (x) => ((x - x0) / Math.max(1, x1 - x0)) * (w - 2) + 1;
  const sy = (y) => h - 2 - ((y - y0) / Math.max(1e-6, y1 - y0)) * (h - 4);
  const d = pts.map((p, i) => `${i ? "L" : "M"}${sx(p[0]).toFixed(1)},${sy(p[1]).toFixed(1)}`).join("");
  return `<svg width="${w}" height="${h}" aria-hidden="true"><path d="${d}" fill="none" stroke="${stroke}" stroke-width="1.2"/></svg>`;
}

/* ---------- data access ---------- */
const allNodes = () => (S ? S.config.nodes : []);
const isVis = (id) => !prefs.hidden.includes(id);
/** Visible nodes (settings can hide some). The list, the map and the top bar only use these. */
const cfgNodes = () => allNodes().filter((n) => isVis(n.id));
const cfgNode = (id) => allNodes().find((n) => n.id === id);
const locOf = (id) => S.config.locations[cfgNode(id)?.loc] || null;
const hub = () => S.config.hub;

function edge(src, dst) {
  return (S.latency.edges || []).find((e) => e.src === src && e.dst === dst) || null;
}
/** Latency a→b: prefer what a measured, else what b measured to a. */
function link(a, b) {
  return edge(a, b) || edge(b, a);
}
function edgesFrom(id) {
  const out = (S.latency.edges || []).filter((e) => e.src === id);
  if (out.length) return { list: out, reversed: false };
  const inc = (S.latency.edges || []).filter((e) => e.dst === id).map((e) => ({ ...e, src: e.dst, dst: e.src }));
  return { list: inc, reversed: true };
}

const pingsTo = (id) => (S.latency.edges || []).filter((e) => e.route === "icmp" && e.dst === id);

function nodeStatus(id) {
  const cfg = cfgNode(id), n = S.nodes[id] || {};
  const ts = n.tailscale;
  let online = null;
  if (cfg.inTailnet) online = !!(ts && ts.online);
  else if (cfg.collected) online = n.collect ? (!!n.collect.ok || (n.collect.fails || 0) < 2) : null;
  else {
    // outside the tailnet and not collected: online if any public ping got through
    const probes = pingsTo(id);
    if (probes.length) online = probes.some((e) => e.ms != null);
  }
  const issues = [];
  if (cfg.inTailnet && online === false && cfg.kind === "linux") issues.push(t("{id} is offline (Tailscale)", { id }));
  if (!cfg.inTailnet && !cfg.collected && online === false) issues.push(t("{id}: public ping unreachable (from {src})", { id, src: pingsTo(id).map((e) => e.src).join(", ") }));
  if (n.collect && n.collect.ok === false && (n.collect.fails || 1) >= 2) issues.push(t("{id}: collection failed {n} times in a row: {err}", { id, n: n.collect.fails, err: n.collect.error }));
  const failed = (n.services || []).filter((u) => u.active === "failed");
  if (failed.length) issues.push(t("{id}: {n} systemd unit(s) failed", { id, n: failed.length }));
  const cs = (n.docker && n.docker.containers) || [];
  const bad = cs.filter((c) => c.health === "unhealthy" || c.state === "restarting" || c.state === "dead");
  if (bad.length) issues.push(t("{id}: {n} unhealthy container(s)", { id, n: bad.length }));
  const kdown = (n.kuma || []).filter((m) => m.status === "down");
  if (kdown.length) issues.push(t("{id}: {n} Kuma monitor(s) DOWN: {names}", { id, n: kdown.length, names: kdown.map((m) => m.name).slice(0, 3).join(", ") }));
  const level = online === false ? "off" : issues.length ? "warn" : online === null && !n.collect ? "idle" : "on";
  return { online, issues, level, failed, badCtr: bad };
}
const sqClass = (level) => ({ on: "on", off: "off", warn: "warn", bad: "bad", idle: "idle" }[level] || "idle");

/* ---------- top bar ---------- */
/** All current issues: {node, text, level}. node is null for problems of the collector itself. */
function computeIssues() {
  const out = [];
  for (const n of cfgNodes()) {
    const st = nodeStatus(n.id);
    for (const t of st.issues) out.push({ node: n.id, text: t, level: st.online === false ? "bad" : "warn" });
  }
  if (S.latency.error) out.push({ node: null, text: S.latency.error, level: "warn" });
  if (S.tailscale.error) out.push({ node: null, text: "Tailscale：" + S.tailscale.error, level: "warn" });
  if (S.kuma?.error) out.push({ node: null, text: "Kuma：" + S.kuma.error, level: "warn" });
  return out;
}

const pad2 = (n) => String(n).padStart(2, "0");
/** Top-bar metrics: [label, () => [value, small text]]. Which ones show is a setting. */
const KPI_DEFS = {
  nodes: ["NODES", () => [pad2(cfgNodes().length), prefs.hidden.length ? t("+{n} hidden", { n: prefs.hidden.length }) : ""]],
  online: ["ONLINE", () => [pad2(cfgNodes().filter((n) => nodeStatus(n.id).online).length), ""]],
  ctr: ["CONTAINERS", () => {
    let run = 0, total = 0;
    for (const n of cfgNodes()) {
      const cs = S.nodes[n.id]?.docker?.containers || [];
      total += cs.length;
      run += cs.filter((c) => c.state === "running").length;
    }
    return total ? [run, `/${total}`] : ["--", ""];
  }],
  p50: ["P50 RTT", () => {
    const ms = (S.latency.edges || []).filter((e) => e.src === hub() && e.ms != null && isVis(e.dst)).map((e) => e.ms);
    return [ms.length ? fmtMs(d3.median(ms)) : "--", ""];
  }],
  issues: ["ISSUES", () => [pad2(computeIssues().length), ""]],
  cpu: ["AVG CPU", () => {
    const v = cfgNodes().map((n) => S.nodes[n.id]?.sys?.cpu).filter((x) => x != null);
    return [v.length ? Math.round(d3.mean(v)) + "%" : "--", v.length ? t("{n} nodes", { n: v.length }) : ""];
  }],
  kuma: ["KUMA UP", () => {
    const ms = Object.values(S.nodes).flatMap((n) => n.kuma || []);
    return ms.length ? [ms.filter((m) => m.status === "up").length, `/${ms.length}`] : ["--", ""];
  }],
  worst: ["SLOWEST", () => {
    const es = (S.latency.edges || []).filter((e) => e.src === hub() && isVis(e.dst));
    const dead = es.find((e) => e.ms == null);
    if (dead) return ["TIMEOUT", dead.dst];
    const w = es.reduce((a, e) => (!a || e.ms > a.ms ? e : a), null);
    return w ? [fmtMs(w.ms), w.dst] : ["--", ""];
  }],
  derp: ["DERP", () => {
    const ts = (S.latency.edges || []).filter((e) => e.via === "tailscale" && isVis(e.src) && isVis(e.dst));
    return ts.length ? [ts.filter((e) => e.route === "relay").length, `/${ts.length}`] : ["--", ""];
  }],
};

function renderTop() {
  $("brand-title").textContent = S.config.title || "MESHATLAS";
  $("brand-sub").textContent = "// " + (S.config.subtitle || "");
  $("kpis").innerHTML = prefs.kpis.map((k) => {
    const [label, fn] = KPI_DEFS[k];
    const [v, sub] = fn();
    return `<div class="kpi"><span class="kpi-l">${label}</span><span class="kpi-v">${esc(v)}${sub ? `<small>${esc(sub)}</small>` : ""}</span></div>`;
  }).join("");

  const issues = computeIssues();
  const sys = $("sys");
  const anyOff = cfgNodes().some((n) => nodeStatus(n.id).online === false && n.kind === "linux");
  sys.className = "sys" + (!apiOk || anyOff ? " bad" : issues.length ? " warn" : "");
  $("sys-text").textContent = !apiOk ? "API OFFLINE" : !S.tailscale.at ? "SYNCING" :
    issues.length ? `${issues.length} ISSUE${issues.length > 1 ? "S" : ""}` : "ALL SYSTEMS NOMINAL";
  sys.title = issues.length ? t("Show the list of issues") : "";
  sys.setAttribute("aria-expanded", String(!$("issues").hidden));
  if (!$("issues").hidden) renderIssues();
}

function tickClock() {
  const d = new Date();
  const local = new Intl.DateTimeFormat("en-US", {
    hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit", timeZoneName: "short",
  }).format(d);
  const utc = d.toISOString().slice(0, 10) + " · " + d.toISOString().slice(11, 19) + " UTC";
  const localDate = new Intl.DateTimeFormat("sv-SE", { year: "numeric", month: "2-digit", day: "2-digit" }).format(d);
  $("clk-local").textContent = prefs.clock === "utc" ? d.toISOString().slice(11, 19) + " UTC" : local;
  $("clk-utc").textContent = prefs.clock === "utc" ? `${localDate} · ${local}` : utc;
  document.querySelectorAll(".ago[data-ts]").forEach((el) => { el.textContent = fmtAgo(+el.dataset.ts); });
}

/* ---------- node list ---------- */
/** List order (a setting). Arrow keys follow the same order. */
function listOrder() {
  const nodes = cfgNodes();
  const idx = new Map(allNodes().map((n, i) => [n.id, i]));
  const locIdx = new Map(Object.keys(S.config.locations).map((k, i) => [k, i]));
  const rank = { off: 0, warn: 1, idle: 2, on: 3 };
  const lat = (id) => (id === hub() ? -1 : link(hub(), id)?.ms ?? 1e9);
  const by = {
    config: (a, b) => idx.get(a.id) - idx.get(b.id),
    loc: (a, b) => (locIdx.get(a.loc) ?? 99) - (locIdx.get(b.loc) ?? 99) || idx.get(a.id) - idx.get(b.id),
    status: (a, b) => rank[nodeStatus(a.id).level] - rank[nodeStatus(b.id).level] || idx.get(a.id) - idx.get(b.id),
    latency: (a, b) => lat(a.id) - lat(b.id),
  }[prefs.sort] || ((a, b) => idx.get(a.id) - idx.get(b.id));
  return [...nodes].sort(by);
}

/** Right column of the list: latency / CPU / memory / containers / availability, per settings. */
function listMetric(id, st) {
  const n = S.nodes[id] || {};
  const dim = (t) => `<span style="color:var(--fg-4)">${t}</span>`;
  if (st.online === false) return `<span style="color:var(--fg-3)">OFFLINE</span>`;
  switch (prefs.listMetric) {
    case "cpu": return n.sys?.cpu != null ? `${Math.round(n.sys.cpu)}%` + meterPct(n.sys.cpu) : dim("—");
    case "mem": { const p = n.sys?.mem ? pct(n.sys.mem.used, n.sys.mem.total) : null; return p != null ? `${Math.round(p)}%` + meterPct(p) : dim("—"); }
    case "ctr": { const cs = n.docker?.containers; return cs ? `${cs.filter((c) => c.state === "running").length}/${cs.length}` : dim("—"); }
    case "uptime": { const u = upt?.nodes?.[id]; return u ? fmtPct(u.pct) : dim("—"); }
    default: {
      if (id === hub()) return `<span style="color:var(--fg-3)">HUB</span>`;
      const e = link(hub(), id);
      return e ? (e.ms == null ? `<span style="color:var(--bad)">TIMEOUT</span>` : fmtMs(e.ms) + meter3(e.ms)) : dim("—");
    }
  }
}
const fmtPct = (p) => (p >= 99.995 ? "100%" : p >= 99 ? p.toFixed(2) + "%" : p.toFixed(1) + "%");
const meterPct = (p) => {
  const f = p >= 85 ? 3 : p >= 50 ? 2 : p >= 10 ? 1 : 0;
  return `<span class="meter3 ${p >= 85 ? "hot" : ""}" aria-hidden="true">${[0, 1, 2].map((i) => `<i class="${i < f ? "f" : ""}"></i>`).join("")}</span>`;
};

function renderList() {
  const rows = listOrder().map((cfg) => {
    const id = cfg.id, n = S.nodes[id] || {}, st = nodeStatus(id), loc = locOf(id);
    const cs = n.docker?.containers;
    const ctr = cs && prefs.listMetric !== "ctr" ? ` · ${cs.filter((c) => c.state === "running").length}/${cs.length} CTR` : "";
    return `<button class="node-row ${id === sel ? "sel" : ""} ${st.online === false ? "down" : ""}" data-id="${esc(id)}" type="button" title="${t("Click to select, double-click or Enter for details")}">
      <span class="sq ${sqClass(st.level)}"></span>
      <span class="nm">${esc(id)}</span>
      <span class="ms">${listMetric(id, st)}</span>
      <span></span>
      <span class="sub">${esc(loc?.code || "—")} · ${esc(cfg.where || "")}${ctr}</span>
      <span class="sp">${prefs.listSpark ? spark(S.spark[id]) : ""}</span>
    </button>`;
  });
  const extras = S.extraNodes || [];
  if (extras.length) {
    rows.push(`<div class="list-sep">UNPLACED</div>`);
    for (const x of extras) {
      rows.push(`<div class="node-row ${x.online ? "" : "down"}" style="cursor:default" title="${esc(x.ip)}">
        <span class="sq ${x.online ? "on" : "off"}"></span>
        <span class="nm">${esc(x.id)}</span>
        <span class="ms" style="color:var(--fg-3)">${x.online ? "ONLINE" : "OFFLINE"}</span>
        <span></span>
        <span class="sub">${esc(x.os || "")}${x.online ? "" : " · " + t("last seen") + " " + esc(fmtAgo(Date.parse(x.lastSeen) / 1000))}</span>
        <span></span>
      </div>`);
    }
  }
  const html = rows.join("");
  const box = $("node-list");
  if (box.dataset.sig !== html) {           // only rewrite when changed, so focus and hover survive
    const focusId = document.activeElement?.closest?.(".node-row[data-id]")?.dataset.id;
    box.innerHTML = html;
    box.dataset.sig = html;
    if (focusId) box.querySelector(`.node-row[data-id="${CSS.escape(focusId)}"]`)?.focus();
  }
  const online = cfgNodes().filter((c) => nodeStatus(c.id).online).length;
  $("idx-sub").textContent = `${online}/${cfgNodes().length} ONLINE`;
}

/* ---------- map ---------- */
async function loadLand() {
  const topo = await fetch("vendor/land-110m.json").then((r) => r.json());
  land = topojson.feature(topo, topo.objects.land);
}

/** Pick a view that fits every location: rotate to the middle of the smallest longitude span, centre on the lat range. */
function fitView() {
  const locs = S ? Object.values(S.config.locations) : [];
  if (!locs.length) return { lon0: 10, lat0: 25, spanLon: 360, spanLat: 150 };
  const lons = locs.map((l) => ((((l.lon + 180) % 360) + 360) % 360) - 180).sort((a, b) => a - b);
  let gap = lons[0] + 360 - lons.at(-1), gi = lons.length - 1;      // largest empty arc of longitude
  for (let i = 0; i < lons.length - 1; i++) if (lons[i + 1] - lons[i] > gap) { gap = lons[i + 1] - lons[i]; gi = i; }
  const start = lons[(gi + 1) % lons.length], span = 360 - gap;
  const lats = locs.map((l) => l.lat);
  const lo = Math.min(...lats), hi = Math.max(...lats);
  return { lon0: start + span / 2, lat0: Math.max(-50, Math.min(65, (lo + hi) / 2)),
    spanLon: Math.min(360, Math.max(60, span + 44)), spanLat: Math.min(150, Math.max(36, hi - lo + 26)) };
}

function layoutMap() {
  const el = $("map");
  const r = el.getBoundingClientRect();
  M.W = Math.max(200, Math.round(r.width));
  M.H = Math.max(160, Math.round(r.height));
  const v = fitView();
  M.view = v;
  M.fitSig = JSON.stringify(S ? Object.values(S.config.locations).map((l) => [l.lat, l.lon]) : []);
  const pxPerDeg = Math.min(M.W / v.spanLon, M.H / v.spanLat);
  M.proj = d3.geoEquirectangular().rotate([-v.lon0, 0]).center([0, v.lat0])
    .scale((pxPerDeg * 180) / Math.PI).translate([M.W / 2, M.H / 2]);
  drawDots();
  M.sig = "";
  renderMap();
}

function drawDots() {
  if (!land) return;
  const { W, H, proj } = M;
  const c = $("map-dots");
  const dpr = window.devicePixelRatio || 1;
  c.width = W * dpr; c.height = H * dpr;
  const ctx = c.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);

  // graticule
  const gpath = d3.geoPath(proj, ctx);
  ctx.beginPath(); gpath(d3.geoGraticule().step([10, 10])());
  ctx.strokeStyle = "rgba(255,255,255,0.035)"; ctx.lineWidth = 1; ctx.stroke();

  // draw land onto an offscreen canvas as a mask, then sample it on a grid to get the dot matrix
  const off = document.createElement("canvas");
  off.width = W; off.height = H;
  const octx = off.getContext("2d", { willReadFrequently: true });
  octx.beginPath(); d3.geoPath(proj, octx)(land); octx.fillStyle = "#fff"; octx.fill();
  const img = octx.getImageData(0, 0, W, H).data;
  const step = W > 1000 ? 6 : 5;
  const locs = S ? Object.values(S.config.locations).map((l) => proj([l.lon, l.lat])) : [];
  for (let y = step / 2; y < H; y += step) {
    for (let x = step / 2; x < W; x += step) {
      if (img[((y | 0) * W + (x | 0)) * 4 + 3] < 128) continue;
      let near = 0;
      for (const p of locs) {
        const d = Math.hypot(p[0] - x, p[1] - y);
        if (d < 90) near = Math.max(near, 1 - d / 90);
      }
      const v = Math.round([38, 58, 84][prefs.land] + near * [52, 72, 80][prefs.land]);
      ctx.fillStyle = `rgb(${v},${v},${v})`;
      ctx.fillRect(x - 0.9, y - 0.9, 1.8, 1.8);
    }
  }
}

function lonLabel(L) {
  let l = ((L + 540) % 360) - 180;
  if (Math.abs(l) === 180) return "180°";
  return l >= 0 ? `${l}°E` : `${-l}°W`;
}

function bezier(p0, p2, k) {
  const dx = p2[0] - p0[0], dy = p2[1] - p0[1], d = Math.hypot(dx, dy) || 1;
  let nx = dy / d, ny = -dx / d;
  if (ny > 0) { nx = -nx; ny = -ny; }       // arcs bow upwards
  const c = [(p0[0] + p2[0]) / 2 + nx * d * k, (p0[1] + p2[1]) / 2 + ny * d * k];
  const at = (t) => [
    (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * c[0] + t * t * p2[0],
    (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * c[1] + t * t * p2[1],
  ];
  return { d: `M${p0[0].toFixed(1)},${p0[1].toFixed(1)} Q${c[0].toFixed(1)},${c[1].toFixed(1)} ${p2[0].toFixed(1)},${p2[1].toFixed(1)}`, at, len: d };
}
const overlap = (a, b, pad = 4) =>
  a.x < b.x + b.w + pad && b.x < a.x + a.w + pad && a.y < b.y + b.h + pad && b.y < a.y + a.h + pad;

function renderMap() {
  if (!S || !M.proj || view !== "map") return;
  const matrix = mapMode === "matrix";
  $("matrix").hidden = !matrix;
  $("map-svg").style.display = $("map-dots").style.display = matrix ? "none" : "";
  document.querySelectorAll("[data-mapmode]").forEach((b) => b.classList.toggle("on", b.dataset.mapmode === mapMode));
  if (matrix) return renderMatrix();
  const { list, reversed } = edgesFrom(sel);
  const statuses = Object.fromEntries(cfgNodes().map((n) => [n.id, nodeStatus(n.id).level]));
  const sig = JSON.stringify([M.W, M.H, sel, mapMode, openLoc, S.latency.at, statuses, prefs.hidden, prefs.arcLabels,
    prefs.flow, prefs.showIcmp, prefs.locTags, cfgNodes().map((n) => link(sel, n.id)?.ms && Math.round(link(sel, n.id).ms))]);
  if (sig === M.sig) return;
  M.sig = sig;

  const { W, H, proj } = M;
  const svg = d3.select("#map-svg").attr("viewBox", `0 0 ${W} ${H}`)
    .on("click", () => { if (openLoc) toggleLoc(null); });   // clicking empty map closes the card
  svg.selectAll("*").remove();
  const P = (l) => proj([l.lon, l.lat]);
  const selLocKey = cfgNode(sel)?.loc;

  // frame ticks
  const frame = svg.append("g").attr("fill", "#5e5e5e").attr("font-size", 10.5).attr("letter-spacing", ".06em");
  for (let L = -180; L < 180; L += 20) {
    const x = proj([L, 0])[0];
    if (x < 30 || x > W - 30) continue;
    frame.append("line").attr("x1", x).attr("x2", x).attr("y1", H - 6).attr("y2", H).attr("stroke", "#444");
    frame.append("text").attr("x", x).attr("y", H - 10).attr("text-anchor", "middle").text(lonLabel(L));
  }
  for (let la = -20; la <= 80; la += 10) {
    const y = proj([M.view.lon0, la])[1];
    if (y < 16 || y > H - 24) continue;
    frame.append("line").attr("x1", W - 6).attr("x2", W).attr("y1", y).attr("y2", y).attr("stroke", "#444");
    frame.append("text").attr("x", W - 10).attr("y", y + 3.5).attr("text-anchor", "end").text(`${Math.abs(la)}°${la >= 0 ? "N" : "S"}`);
  }
  frame.append("text").attr("x", 12).attr("y", 20).attr("fill", "#5e5e5e")
    .text(`EQUIRECTANGULAR · λ0 ${lonLabel(Math.round(M.view.lon0))} · TAILNET MESH`);

  // locations: markers and a small code are always shown; only the clicked card is drawn. Arc labels avoid them.
  const locKeys = Object.keys(S.config.locations).filter((k) => cfgNodes().some((n) => n.loc === k));
  if (openLoc && !locKeys.includes(openLoc)) openLoc = null;
  const tags = locKeys.map((k) => locTag(k, P(S.config.locations[k])));
  const boxes = openLoc ? [calloutBox(openLoc, P(S.config.locations[openLoc]))] : [];
  resolveOverlaps(boxes, W, H);
  const obstacles = [
    ...boxes.map((b) => ({ x: b.x, y: b.y, w: b.w, h: b.h })),
    ...tags.map((t) => ({ x: t.p[0] - 14, y: t.p[1] - 14, w: 28, h: 28 })),
    ...(prefs.locTags ? tags.map((t) => t.box) : []),
  ];

  // arcs: node mode draws the selected node to every other node; mesh mode draws one summary arc per location pair
  const specs = mapMode === "mesh" ? meshSpecs(selLocKey) : nodeSpecs(list, reversed, selLocKey);
  const defs = svg.append("defs");
  const arcs = svg.append("g");
  const labels = [];
  specs.forEach((s, ai) => {
    const { d, at, len } = bezier(P(s.from), P(s.to), s.k);
    const id = `arc${ai}`;
    defs.append("path").attr("id", id).attr("d", d);
    const op = (s.dead ? 0.85 : [0.9, 0.62, 0.45][tier(s.ms)]) * (s.dim ? 0.45 : 1);
    const dash = s.dead ? "3 4" : s.route === "relay" ? "6 5" : s.route === "icmp" ? "1.5 4" : null;
    arcs.append("path").attr("d", d).attr("fill", "none")
      .attr("stroke", s.dead ? "var(--bad)" : "#fff").attr("stroke-opacity", op).attr("stroke-width", s.width || 1.3)
      .attr("stroke-dasharray", dash);
    if (!s.dead && prefs.flow) {
      const dur = Math.min(6, Math.max(1.8, 1.4 + s.ms / 55));
      arcs.append("path").attr("d", d).attr("fill", "none").attr("class", "arc-flow")
        .attr("stroke", "#fff").attr("stroke-width", 2.2).attr("stroke-linecap", "round")
        .attr("stroke-dasharray", "2 28").attr("stroke-opacity", s.dim ? 0.35 : 0.85)
        .style("animation-duration", `${dur}s`);
      if (!s.dim) {
        const comet = arcs.append("g");
        comet.append("circle").attr("r", 7).attr("fill", "#fff").attr("opacity", 0.12);
        comet.append("circle").attr("r", 2.4).attr("fill", "#fff");
        comet.append("animateMotion").attr("dur", `${dur * 1.6}s`).attr("repeatCount", "indefinite")
          .append("mpath").attr("href", `#${id}`);
      }
    }
    // hover target
    arcs.append("path").attr("d", d).attr("fill", "none").attr("stroke", "transparent").attr("stroke-width", 12)
      .style("cursor", "help")
      .on("mousemove", (ev) => showTip(ev, s.tip))
      .on("mouseleave", hideTip);
    labels.push({ at, len, text: s.label, dead: s.dead });
  });
  // labels: longest arcs first; very short arcs get none; on a collision slide along the arc, else skip
  // (the location card has every latency, so a skipped label loses nothing).
  const lg = svg.append("g");
  const placed = [];
  labels.sort((a, b) => b.len - a.len);
  for (const l of labels) {
    if (l.len < 110 || !l.text || prefs.arcLabels === "none") continue;
    const w = l.text.length * 7.3 + 14, h = 20;
    for (const t of [0.5, 0.42, 0.58, 0.34, 0.66, 0.27, 0.73]) {
      const [cx, cy] = l.at(t);
      const r = { x: cx - w / 2, y: cy - h / 2, w, h };
      if (r.x < 4 || r.y < 24 || r.x + w > W - 4 || r.y + h > H - 20) continue;
      if (obstacles.some((o) => overlap(r, o)) || placed.some((o) => overlap(r, o))) continue;
      placed.push(r);
      const g = lg.append("g").attr("transform", `translate(${r.x.toFixed(1)},${r.y.toFixed(1)})`);
      g.append("rect").attr("width", w).attr("height", h).attr("fill", "#050505").attr("stroke", l.dead ? "var(--bad)" : "#3a3a3a");
      g.append("text").attr("x", w / 2).attr("y", 14).attr("text-anchor", "middle").attr("font-size", 12)
        .attr("fill", l.dead ? "var(--bad)" : "#f0f0f0").text(l.text);
      break;
    }
  }

  // location markers: the square shows the worst status there; a small code + count sits next to it. Click toggles the card.
  const leaders = svg.append("g");
  const marks = svg.append("g");
  const cos = svg.append("g");
  for (const tg of tags) {
    const [x, y] = tg.p;
    const levels = cfgNodes().filter((n) => n.loc === tg.key).map((n) => statuses[n.id]);
    const level = levels.every((l) => l === "off") ? "off" : levels.some((l) => l === "warn" || l === "off") ? "warn" : "on";
    const isSel = tg.key === selLocKey, isOpen = tg.key === openLoc;
    const m = marks.append("g").attr("transform", `translate(${x},${y})`).attr("class", "loc-hit")
      .attr("role", "button").attr("tabindex", 0)
      .attr("aria-label", t(isOpen ? "{name}: {n} nodes, close card" : "{name}: {n} nodes, open card", { name: S.config.locations[tg.key].name, n: tg.count }))
      .on("click", (ev) => { ev.stopPropagation(); hideTip(); toggleLoc(tg.key); })
      .on("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); toggleLoc(tg.key); } })
      .on("mousemove", (ev) => { if (!isOpen) showTip(ev, locTipText(tg.key)); })
      .on("mouseleave", hideTip);
    if (isSel) {
      m.append("circle").attr("r", 8).attr("fill", "none").attr("stroke", "#fff").attr("class", "pulse-ring");
      m.append("circle").attr("r", 8).attr("fill", "none").attr("stroke", "#fff").attr("class", "pulse-ring r2");
    }
    m.append("circle").attr("r", 16).attr("fill", "transparent");
    m.append("rect").attr("x", -8).attr("y", -8).attr("width", 16).attr("height", 16).attr("fill", isOpen ? "rgba(255,255,255,0.08)" : "none")
      .attr("stroke", isSel || isOpen ? "#fff" : "#6a6a6a").attr("transform", "rotate(45)");
    const color = level === "warn" ? "var(--warn)" : level === "off" ? "none" : "#fff";
    m.append("rect").attr("x", -3.5).attr("y", -3.5).attr("width", 7).attr("height", 7)
      .attr("fill", color).attr("stroke", level === "off" ? "#777" : "none");
    if (!prefs.locTags) continue;
    m.append("rect").attr("x", tg.box.x - x - 2).attr("y", tg.box.y - y).attr("width", tg.box.w + 4).attr("height", tg.box.h)
      .attr("fill", "transparent");
    m.append("text").attr("x", tg.left ? -15 : 15).attr("y", 4).attr("text-anchor", tg.left ? "end" : "start")
      .attr("font-size", 11).attr("letter-spacing", ".08em")
      .attr("fill", isSel || isOpen ? "#f0f0f0" : "#9a9a9a")
      .attr("stroke", "#060606").attr("stroke-width", 3).attr("paint-order", "stroke").text(tg.text);
  }

  // card: only for the open location
  for (const b of boxes) {
    const [x, y] = b.p;
    // leader line from the marker to the nearest corner of the card
    const cx = Math.max(b.x, Math.min(x, b.x + b.w)), cy = Math.max(b.y, Math.min(y, b.y + b.h));
    leaders.append("polyline").attr("points", `${x},${y} ${cx},${cy}`).attr("fill", "none").attr("stroke", "#555").attr("stroke-width", 1);
    leaders.append("rect").attr("x", cx - 2).attr("y", cy - 2).attr("width", 4).attr("height", 4).attr("fill", "#888");

    const g = cos.append("g").attr("class", "co").attr("transform", `translate(${b.x},${b.y})`)
      .on("click", (ev) => ev.stopPropagation());
    g.append("rect").attr("width", b.w).attr("height", b.h).attr("fill", "rgba(6,6,6,0.94)").attr("stroke", "#8a8a8a");
    g.append("text").attr("x", 10).attr("y", 16).attr("font-size", 10.5).attr("letter-spacing", ".14em")
      .attr("fill", "#8a8a8a").text(b.header);
    const close = g.append("g").attr("class", "co-x").attr("transform", `translate(${b.w - 22},2)`)
      .attr("role", "button").attr("tabindex", 0).attr("aria-label", t("Close card"))
      .on("click", (ev) => { ev.stopPropagation(); toggleLoc(null); })
      .on("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); toggleLoc(null); } });
    close.append("rect").attr("width", 20).attr("height", 18).attr("fill", "transparent");
    close.append("text").attr("x", 10).attr("y", 13.5).attr("text-anchor", "middle").attr("font-size", 13)
      .attr("fill", "#9a9a9a").text("×");
    b.nodes.forEach((n, i) => {
      const yy = 24 + i * 22;
      const row = g.append("g").attr("class", "co-row").attr("transform", `translate(0,${yy})`)
        .on("click", (ev) => { ev.stopPropagation(); select(n.id); })
        .on("dblclick", (ev) => { ev.stopPropagation(); openNode(n.id); });
      row.append("rect").attr("class", "co-hl").attr("x", 1).attr("width", b.w - 2).attr("height", 22)
        .attr("fill", n.id === sel ? "rgba(255,255,255,0.10)" : "rgba(255,255,255,0.05)")
        .attr("opacity", n.id === sel ? 1 : 0);
      if (n.id === sel) row.append("rect").attr("x", 1).attr("width", 2).attr("height", 22).attr("fill", "#fff");
      const lv = statuses[n.id];
      row.append("rect").attr("x", 10).attr("y", 7).attr("width", 8).attr("height", 8)
        .attr("fill", lv === "warn" ? "var(--warn)" : lv === "off" ? "none" : lv === "idle" ? "#7a7a7a" : "#fff")
        .attr("stroke", lv === "off" ? "#666" : "none");
      row.append("text").attr("x", 26).attr("y", 15.5).attr("font-size", 12.5)
        .attr("fill", lv === "off" ? "#7a7a7a" : "#f0f0f0").attr("font-weight", n.id === sel ? 700 : 400).text(n.id);
      row.append("text").attr("x", b.w - 10).attr("y", 15.5).attr("font-size", 12).attr("text-anchor", "end")
        .attr("fill", n.metricColor).text(n.metric);
    });
  }

  if (mapMode === "mesh") {
    const pairs = meshBest();
    const all = [...pairs.values()];
    const cross = all.filter((e) => cfgNode(e.src).loc !== cfgNode(e.dst).loc);
    const icmp = all.filter((e) => e.route === "icmp").length;
    $("map-sub").textContent = t("Mesh · {n} pairs ({x} across locations) · direct {d} · relayed {r}", { n: all.length, x: cross.length, d: all.filter((e) => e.route === "direct").length, r: all.filter((e) => e.route === "relay").length }) + (icmp ? " · " + t("public ping {n}", { n: icmp }) : "");
  } else {
    const ok = list.filter((e) => e.ms != null);
    $("map-sub").textContent = list.length
      ? `${reversed ? t("measured to {id}", { id: sel }) : t("from {id}", { id: sel })} · ${t("{n} links", { n: list.length })} · ${[[t("direct"), "direct"], [t("relayed"), "relay"], [t("public ping"), "icmp"]]
        .map(([lb, r]) => [lb, list.filter((e) => e.route === r).length]).filter(([lb, c], i) => c || i < 2).map(([lb, c]) => `${lb} ${c}`).join(" · ")}${ok.length < list.length ? " · " + t("{n} down", { n: list.length - ok.length }) : ""}`
      : t("{id}: no latency data", { id: sel });
  }
  document.querySelectorAll("[data-mapmode]").forEach((b) => b.classList.toggle("on", b.dataset.mapmode === mapMode));
}

function edgeLabel(e) {
  return `${e.ms == null ? "TIMEOUT" : fmtMs(e.ms)}${e.route === "relay" ? " · DERP" : e.route === "icmp" ? " · ICMP" : ""}`;
}
function edgeTip(e, arrow = "→") {
  return `${e.src} ${arrow} ${e.dst}  ${e.ms == null ? t("unreachable") : fmtMs(e.ms)}${e.min != null ? ` (${fmtMs(e.min)}–${fmtMs(e.max)})` : ""} · ${routeText(e)}`;
}

function nodeSpecs(list, reversed, selLocKey) {
  const selLoc = S.config.locations[selLocKey];
  if (!selLoc) return [];
  const byLoc = {};
  for (const e of list) {
    if (!isVis(e.dst) || (!prefs.showIcmp && e.route === "icmp")) continue;
    const tl = cfgNode(e.dst)?.loc;
    if (!tl || tl === selLocKey || !S.config.locations[tl]) continue;
    (byLoc[tl] = byLoc[tl] || []).push(e);
  }
  const out = [];
  for (const [lk, es] of Object.entries(byLoc)) {
    es.sort((a, b) => (a.ms ?? 1e9) - (b.ms ?? 1e9));
    es.forEach((e, i) => out.push({
      from: reversed ? S.config.locations[lk] : selLoc, to: reversed ? selLoc : S.config.locations[lk],
      k: 0.2 + i * 0.1, ms: e.ms, dead: e.ms == null, route: e.route,
      // "fastest per location": only the fastest link (and dead ones) of a location get a number
      label: prefs.arcLabels === "best" && i > 0 && e.ms != null ? "" : edgeLabel(e), tip: edgeTip(e),
    }));
  }
  return out;
}

/** One edge per node pair: whichever direction measured lower. */
function meshBest() {
  const best = new Map();
  for (const e of S.latency.edges || []) {
    if (!cfgNode(e.src) || !cfgNode(e.dst) || !isVis(e.src) || !isVis(e.dst)) continue;
    if (!prefs.showIcmp && e.route === "icmp") continue;
    const k = [e.src, e.dst].sort().join("|");
    const cur = best.get(k);
    if (!cur || (e.ms ?? 1e9) < (cur.ms ?? 1e9)) best.set(k, e);
  }
  return best;
}

function meshSpecs(selLocKey) {
  // Tailscale and public-ping links are summarised separately (the ping arc bows higher so they do not overlap).
  const groups = new Map();
  for (const e of meshBest().values()) {
    const la = cfgNode(e.src).loc, lb = cfgNode(e.dst).loc;
    if (la === lb || !S.config.locations[la] || !S.config.locations[lb]) continue;
    const key = [la, lb].sort().join("|") + (e.route === "icmp" ? "|icmp" : "|ts");
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(e);
  }
  const out = [];
  for (const [key, es] of groups) {
    const [la, lb, kind] = key.split("|");
    const ok = es.filter((e) => e.ms != null).sort((a, b) => a.ms - b.ms);
    const min = ok[0]?.ms ?? null, max = ok.at(-1)?.ms ?? null;
    const allRelay = ok.length && ok.every((e) => e.route === "relay");
    out.push({
      from: S.config.locations[la], to: S.config.locations[lb], k: kind === "icmp" ? 0.32 : 0.2,
      ms: min, dead: !ok.length, route: kind === "icmp" ? "icmp" : allRelay ? "relay" : "direct",
      width: 1 + Math.min(2, es.length * 0.35),
      dim: selLocKey && la !== selLocKey && lb !== selLocKey,
      label: !ok.length ? "TIMEOUT" : ok.length > 1 && Math.round(max) !== Math.round(min) ? `${fmtMs(min)}~${fmtMs(max)}` : fmtMs(min),
      tip: `${S.config.locations[la].name} ↔ ${S.config.locations[lb].name} · ${t("{n} pairs", { n: es.length })}\n` +
        es.sort((a, b) => (a.ms ?? 1e9) - (b.ms ?? 1e9)).map((e) => edgeTip(e, "↔")).join("\n"),
    });
  }
  return out;
}

function routeText(e) {
  if (e.route === "relay") return t("relayed") + (e.derp ? " · " + e.derp : "");
  if (e.route === "icmp") return t("public ICMP ping (outside Tailscale)");
  if (e.route === "direct") return t("direct WireGuard path");
  return e.state || "";
}

function calloutBox(key, p) {
  const loc = S.config.locations[key];
  const nodes = cfgNodes().filter((n) => n.loc === key).map((n) => {
    const st = nodeStatus(n.id);
    let metric = "", metricColor = "#9a9a9a";
    if (st.online === false) { metric = "OFFLINE"; metricColor = "#6a6a6a"; }
    else if (n.id === sel) { metric = "SELECTED"; metricColor = "#ffffff"; }
    else {
      const e = link(sel, n.id);
      if (e) { metric = e.ms == null ? "TIMEOUT" : fmtMs(e.ms); metricColor = e.ms == null ? "var(--bad)" : "#d0d0d0"; }
      else metric = "—";
    }
    return { id: n.id, metric, metricColor };
  });
  const header = `${loc.code}  ${loc.name}${loc.approx ? " (" + t("approx.") + ")" : ""}`;
  const cjk = (s) => [...s].reduce((a, ch) => a + (ch.charCodeAt(0) > 0x2e80 ? 2 : 1), 0);
  const w = Math.max(168, cjk(header) * 7 + 44, ...nodes.map((n) => (n.id.length + n.metric.length) * 7.4 + 54));
  const h = 30 + nodes.length * 22;
  const [dx, dy] = loc.callout || [30, 30];
  const x = dx >= 0 ? p[0] + dx : p[0] + dx - w;
  const y = dy >= 0 ? p[1] + dy : p[1] + dy - h;
  return { key, p, nodes, header, w, h, x, y, dx, dy };
}

/** The small always-on tag next to a marker ("LAX 3"), on the card side, away from the arcs. */
function locTag(key, p) {
  const loc = S.config.locations[key];
  const count = cfgNodes().filter((n) => n.loc === key).length;
  const text = `${(loc.code || key).split("-")[0]} ${count}`;
  const w = text.length * 7 + 2, h = 14;
  let left = (loc.callout || [30, 30])[0] < 0;
  // flip sides near the map edge (leave room for latitude ticks on the right)
  if (left && p[0] - 15 - w < 4) left = false;
  else if (!left && p[0] + 15 + w > M.W - 44) left = true;
  return { key, p, count, text, left, box: { x: left ? p[0] - 15 - w : p[0] + 15, y: p[1] - h / 2 - 1, w, h } };
}

/** Hover preview of a marker: the location and each node's status / latency, without opening the card. */
function locTipText(key) {
  const b = calloutBox(key, [0, 0]);
  return `${b.header}\n${b.nodes.map((n) => `${n.id.padEnd(16)} ${n.metric}`).join("\n")}\n${t("Click to open")}`;
}

function toggleLoc(key) {
  openLoc = key && key !== openLoc ? key : null;
  M.sig = "";
  renderMap();
}

function resolveOverlaps(boxes, W, H) {
  const clamp = (b) => {
    b.x = Math.max(8, Math.min(W - b.w - 8, b.x));
    b.y = Math.max(28, Math.min(H - b.h - 26, b.y));
  };
  boxes.forEach(clamp);
  for (let iter = 0; iter < 6; iter++) {
    let moved = false;
    for (let i = 0; i < boxes.length; i++) {
      for (let j = i + 1; j < boxes.length; j++) {
        const a = boxes[i], b = boxes[j];
        const ox = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
        const oy = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
        if (ox > -6 && oy > -6) {
          const dir = b.dy >= 0 ? 1 : -1;
          b.y += dir * (oy + 8);
          clamp(b);
          if (Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y) > -6) {
            b.x += (b.dx >= 0 ? 1 : -1) * (ox + 8);
            clamp(b);
          }
          moved = true;
        }
      }
    }
    if (!moved) break;
  }
}

/* ---------- tooltip ---------- */
function showTip(ev, text) {
  const t = $("tip");
  t.textContent = text;
  t.hidden = false;
  const x = Math.min(window.innerWidth - t.offsetWidth - 8, ev.clientX + 14);
  const y = Math.min(window.innerHeight - t.offsetHeight - 8, ev.clientY + 14);
  t.style.left = x + "px"; t.style.top = y + "px";
}
function hideTip() { $("tip").hidden = true; }

/* ---------- detail panel ---------- */
const SYS_UNIT = /^(systemd-|dbus|cron|getty@|serial-getty@|polkit|rsyslog|snapd|snap\.|unattended-upgrades|udisks2|multipathd|ModemManager|networkd-dispatcher|packagekit|accounts-daemon|irqbalance|user@|user-runtime-dir@|chrony|qemu-guest-agent|cloud-|apport|atd|blk-availability|console-setup|finalize-kernel|keyboard-setup|kmod|lvm2|plymouth|setvbuf|ufw|apparmor|e2scrub|fwupd|thermald|upower|wpa_supplicant|avahi|bluetooth|power-profiles|switcheroo|rtkit|colord|gdm|kerneloops|secureboot|grub|motd|ssh|uuidd|rpcbind|lxd|open-iscsi|iscsid|pollinate|aliyun|AssistDaemon|aegis|tuned|gpg-agent|dirmngr|pipewire|wireplumber|xdg-|at-spi|gnome-|pulseaudio|filter-chain|emergency|rescue|sysstat|logrotate|man-db|dpkg|apt-|motd-news|ua-|ubuntu-|update-notifier|NetworkManager|networking|resolvconf|ifup@|netplan|open-vm-tools|vgauth|hv-|walinuxagent|google-|nvidia-persistenced|smartmontools|lm-sensors|mdmonitor|mdadm|zfs|ldconfig|modprobe@|getty-static|binfmt|casper|friendly-recovery|systemd)/;

function ctrTag(c) {
  if (c.state === "running") return c.health === "unhealthy" ? ["UNH", "unh"] : ["RUN", "run"];
  if (c.state === "restarting") return ["RST", "rst"];
  if (c.state === "exited") return ["EXT", "ext"];
  if (c.state === "created") return ["NEW", "ext"];
  if (c.state === "paused") return ["PAU", "ext"];
  if (c.state === "dead") return ["DEAD", "dead"];
  return [String(c.state || "?").slice(0, 4).toUpperCase(), "ext"];
}
const ctrIssue = (c) => c.health === "unhealthy" || c.state === "restarting" || c.state === "dead";

function segBar(p) {
  const f = Math.round(((p ?? 0) / 100) * 30);
  const cls = p >= 95 ? "bad" : p >= 85 ? "warn" : "";
  return `<div class="seg ${cls}">${Array.from({ length: 30 }, (_, i) => `<i class="${i < f ? "f" : ""}"></i>`).join("")}</div>`;
}

function renderDetail(force = false) {
  if (!S || !sel) return;
  const cfg = cfgNode(sel);
  if (!cfg) return;
  const n = S.nodes[sel] || {};
  const sig = JSON.stringify([sel, tab, n.collect?.at, n.tailscale?.online, S.latency.at, S.kuma?.at, ctrUi.mode, ctrUi.q,
    [...ctrUi.open], [...openCtr], [...openSvc], showSysSvc, hist.at, upt?.at]);
  if (!force && sig === detailSig) return;
  detailSig = sig;

  const scroller = $("d-scroll");
  const scrollTop = scroller ? scroller.scrollTop : 0;
  const active = document.activeElement;
  const searchFocused = active && active.id === "ctr-q";
  const caret = searchFocused ? active.selectionStart : null;

  const st = nodeStatus(sel);
  const loc = locOf(sel);
  const sys = n.sys || null;
  const chip = st.online === false ? ["OFFLINE", "off"] : st.level === "warn" ? ["DEGRADED", "warn"] : st.online ? ["ONLINE", ""] : ["NO DATA", "off"];
  const cs = n.docker?.containers || [];
  const svcs = n.services || [];
  const peers = edgesFrom(sel).list;

  let meters = "";
  if (sys && !sys.error) {
    const rows = [];
    if (sys.cpu != null) rows.push(["CPU", sys.cpu, t("{n} cores · load {l}", { n: sys.ncpu || "?", l: (sys.load || []).join(" / ") })]);
    if (sys.mem) rows.push(["MEM", pct(sys.mem.used, sys.mem.total), `${gib(sys.mem.used)} / ${gib(sys.mem.total)} GiB`]);
    for (const d of sys.disks || []) {
      const p = pct(d.used, d.used + d.avail);
      rows.push([`DISK ${d.mount === "/System/Volumes/Data" ? "/" : d.mount}`, p, `${gib(d.used)} / ${gib(d.used + d.avail)} GiB · ${t("free")} ${gib(d.avail)}`]);
    }
    meters = `<div class="meters">${rows.map(([l, p, x]) => `
      <div class="mt"><span class="mt-l">${esc(l)}</span>${segBar(p)}<span class="mt-v">${p == null ? "—" : p.toFixed(0) + "%"}</span></div>
      <div class="mt"><span></span><span class="mt-x">${esc(x)}</span></div>`).join("")}</div>`;
  } else {
    meters = `<div class="meters"><div class="empty">${cfg.collected ? (n.collect ? t("No system data from this node yet.") : t("Collecting…")) : t("Not collected over SSH: status and latency only.")}</div></div>`;
  }

  const tabs = [
    ["overview", t("Overview"), ""],
    ["ctr", t("Containers"), n.docker ? `${cs.filter((c) => c.state === "running").length}/${cs.length}` : ""],
    ["svc", t("Services"), (svcs.some((u) => u.active === "failed") || (n.kuma || []).some((m) => m.status === "down")) ? "!"
      : svcs.length ? String(svcs.filter((u) => u.sub === "running").length) : (n.kuma || []).length ? String(n.kuma.length) : ""],
    ["lat", t("Latency"), peers.length ? String(peers.length) : ""],
  ];
  if (!tabs.some((t) => t[0] === tab)) tab = "overview";

  let body = "";
  if (tab === "overview") body = tabOverview(cfg, n, st, loc);
  else if (tab === "ctr") body = tabContainers(n);
  else if (tab === "svc") body = tabServices(svcs);
  else body = tabLatency();

  $("detail").innerHTML = `
    <div class="ph"><span class="ph-t">NODE // DETAIL</span><span class="ph-r">${esc((cfg.kind || "").toUpperCase())}${cfg.collected ? " · " + (cfg.self ? t("LOCAL") : "SSH") : ""}</span>
      <button class="ph-btn" type="button" data-open="${esc(sel)}" title="${t("Open the full detail page (Enter)")}">${t("Details")} ↗</button></div>
    <div class="d-scroll" id="d-scroll">
      <div class="d-head">
        <div class="d-name">${esc(sel)} <span class="chip ${chip[1]}">${chip[0]}</span></div>
        <div class="d-sub">${esc(cfg.role || "")} · ${esc(loc?.name || "")} · ${esc(cfg.where || "")}</div>
        <div class="d-sub2">${esc(sys?.os || cfg.kind)}${sys?.uptime ? " · " + t("up {d}", { d: esc(fmtDur(sys.uptime)) }) : ""}${n.collect?.at ? ` · ${t("collected")} <span class="ago" data-ts="${n.collect.at}">${esc(fmtAgo(n.collect.at))}</span> (${n.collect.elapsed}s)` : ""}</div>
      </div>
      ${meters}
      <div class="tabs" role="tablist">${tabs.map(([k, label, c]) => `<button class="tab ${k === tab ? "on" : ""}" data-tab="${k}" role="tab" type="button">${label}${c ? `<small>${esc(c)}</small>` : ""}</button>`).join("")}</div>
      <div class="tab-body">${body}</div>
    </div>`;

  const ns = $("d-scroll");
  if (ns) ns.scrollTop = scrollTop;
  if (searchFocused) {
    const q = $("ctr-q");
    if (q) { q.focus(); if (caret != null) q.setSelectionRange(caret, caret); }
  }
  drawMiniChart();
}

function tabOverview(cfg, n, st, loc) {
  const notes = [...st.issues.map((t) => ({ t, err: true })), ...(cfg.notes || []).map((t) => ({ t, err: false }))];
  const kv = overviewKV(cfg, n, loc);
  return `${notes.length ? `<div class="notes">${notes.map((x) => `<div class="note ${x.err ? "err" : ""}">${esc(x.t)}</div>`).join("")}</div>` : ""}
    <dl class="kv">${kv.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl>
    <div class="sec-t"><span>CPU / MEM · ${t("history")}</span><span>${hist.data && hist.node === sel ? t("{n} points", { n: hist.data.cpu.length }) : ""}</span></div>
    <svg class="mini-chart" id="mini-chart"></svg>`;
}

/** Key/value rows of the overview, shared by the side panel and the detail page. */
function overviewKV(cfg, n, loc) {
  const ts = n.tailscale;
  const cs = n.docker?.containers || [];
  const svcs = n.services || [];
  const toHub = sel === hub() ? null : link(hub(), sel);
  let tsText;
  if (!cfg.inTailnet) tsText = t("not in the tailnet");
  else if (!ts) tsText = "—";
  else tsText = ts.online ? t("online") + (ts.relay ? " · " + t("home DERP {r}", { r: ts.relay }) : "") : t("offline · last seen {ago}", { ago: fmtAgo(Date.parse(ts.lastSeen) / 1000) });
  const kv = [
    ["TAILNET", tsText],
    [t("To {id}", { id: hub() }), sel === hub() ? t("this node is the hub (latency is measured from here)") : toHub ? `${fmtMs(toHub.ms)} · ${routeText(toHub)}` : "—"],
    [t("Location"), `${loc?.name || t("unknown")}${loc?.approx || cfg.approxLoc ? " (" + t("approx.") + ")" : ""}${cfg.where ? " · " + cfg.where : ""}`],
    [t("System"), n.sys?.os ? `${n.sys.os} · ${n.sys.kernel || ""}` : "—"],
    [t("Containers"), n.docker ? t("{r} running / {n} · {b} unhealthy", { r: cs.filter((c) => c.state === "running").length, n: cs.length, b: cs.filter(ctrIssue).length }) : cfg.collected ? t("no Docker") : "—"],
    [t("Services"), svcs.length ? t("{r} running · {f} failed", { r: svcs.filter((u) => u.sub === "running").length, f: svcs.filter((u) => u.active === "failed").length }) : "—"],
    ...((n.kuma || []).length ? [["KUMA", t("{u} up · {d} down · {n} total", { u: n.kuma.filter((m) => m.status === "up").length, d: n.kuma.filter((m) => m.status === "down").length, n: n.kuma.length })]] : []),
    [t("Collect"), cfg.collected ? (n.collect ? (n.collect.ok ? (cfg.self ? t("local, every {s}s", { s: S.config.intervals.node }) : t("read-only SSH, every {s}s", { s: S.config.intervals.node }))
      : t("last {n} attempts failed: {err}", { n: n.collect.fails, err: n.collect.error }) + (n.collect.dataAt ? " · " + t("showing data from {ago}", { ago: fmtAgo(n.collect.dataAt) }) : "")) : t("waiting for the first round"))
      : pingsTo(sel).length ? t("public ping from {src}, every {s}s", { src: pingsTo(sel).map((e) => e.src).join(", "), s: S.config.intervals.latency }) : t("Tailscale status and latency only")],
  ];
  const u = upt?.nodes?.[sel];
  kv.splice(1, 0, [t("Availability 24h"), u ? `${fmtPct(u.pct)} · ${t("{n} samples", { n: u.samples })}${upt.first && upt.first > upt.since + 3600 ? " · " + t("recording since {ago}", { ago: fmtAgo(upt.first) }) : ""}` : t("collecting")]);
  return kv;
}

function tabContainers(n) {
  if (!n.docker) return `<div class="empty">${cfgNode(sel).collected ? t("Docker is not installed here.") : t("Containers are not collected for this node.")}</div>`;
  if (n.docker.error) return `<div class="note err">${esc(n.docker.error)}</div>`;
  const all = n.docker.containers;
  const q = ctrUi.q.trim().toLowerCase();
  const pass = (c) => {
    if (ctrUi.mode === "run" && c.state !== "running") return false;
    if (ctrUi.mode === "stop" && c.state === "running") return false;
    if (ctrUi.mode === "issue" && !ctrIssue(c)) return false;
    if (q && !(c.name.toLowerCase().includes(q) || (c.project || "").toLowerCase().includes(q) || (c.image || "").toLowerCase().includes(q))) return false;
    return true;
  };
  const groups = new Map();
  for (const c of all) {
    if (!pass(c)) continue;
    const k = c.project || t("(standalone)");
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(c);
  }
  const keys = [...groups.keys()].sort((a, b) => {
    const ia = groups.get(a).some(ctrIssue), ib = groups.get(b).some(ctrIssue);
    if (ia !== ib) return ia ? -1 : 1;
    return a.localeCompare(b);
  });
  const many = keys.length > 8;
  const modes = [["all", t("All")], ["run", t("Running")], ["stop", t("Stopped")], ["issue", t("Problems")]];
  const stale = all.some((c) => c.statsStale);
  let html = `<div class="toolbar">
      <input class="search" id="ctr-q" type="search" placeholder="${t("Filter: container / project / image")}" value="${esc(ctrUi.q)}" autocomplete="off" spellcheck="false">
      ${modes.map(([k, l]) => `<button class="fchip ${ctrUi.mode === k ? "on" : ""}" data-mode="${k}" type="button">${l}</button>`).join("")}
    </div>`;
  if (stale) html += `<div class="sec-t" style="margin-top:0"><span>${t("CPU / memory refresh every few rounds on this node")}</span></div>`;
  if (!keys.length) return html + `<div class="empty">${t("No matching containers.")}</div>`;
  for (const k of keys) {
    const cs = groups.get(k).sort((a, b) => a.name.localeCompare(b.name));
    const issue = cs.some(ctrIssue);
    const explicit = ctrUi.open.get(k);
    const open = explicit != null ? explicit : !!q || !many || issue;
    const run = cs.filter((c) => c.state === "running").length;
    const cpu = cs.reduce((a, c) => a + (c.cpu || 0), 0);
    html += `<div class="grp"><button class="grp-h" data-grp="${esc(k)}" type="button">
        <span class="car">${open ? "▾" : "▸"}</span><span class="gn">${esc(k)}</span>
        <span class="gw">${issue ? "! " + t("problem") : ""}</span>
        <span class="gc">${run}/${cs.length} · ${cpu.toFixed(1)}%</span></button>`;
    if (open) {
      html += `<div class="ctr ctr-h"><span>STATE</span><span>NAME</span><span class="n">CPU</span><span class="n">MEM</span></div>`;
      for (const c of cs) {
        const [tg, cls] = ctrTag(c);
        const key = `${sel}/${c.name}`;
        const isOpen = openCtr.has(key);
        html += `<div class="ctr click ${c.state === "running" ? "" : "stopped"} ${isOpen ? "open" : ""}" data-ctr="${esc(key)}" role="button" tabindex="0">
          <span class="st ${cls}">[${tg}]</span><span class="nm"><span class="car2">${isOpen ? "▾" : "▸"}</span>${esc(c.name)}</span>
          <span class="n">${c.cpu != null && c.state === "running" ? c.cpu.toFixed(1) + "%" : "—"}</span>
          <span class="n">${c.mem && c.state === "running" ? esc(c.mem.replace("iB", "")) : "—"}</span></div>`;
        if (isOpen) html += ctrDetail(c);
      }
    }
    html += `</div>`;
  }
  return html;
}

/** Parse `docker ps` Ports: link what is reachable over the tailnet, mark what is bound to localhost only. */
function portLinks(ports, nodeIp) {
  const out = [], seen = new Set();
  for (const part of String(ports || "").split(",").map((s) => s.trim()).filter(Boolean)) {
    const m = part.match(/^(.*):(\d+)(?:-\d+)?->(\d+)(?:-\d+)?\/(tcp|udp)$/);
    if (!m) { out.push({ text: `${part} (${t("container network only, not published")})`, href: null, lo: true }); continue; }
    const host = m[1].replace(/^\[|\]$/g, ""), hp = m[2], cp = m[3], proto = m[4];
    const local = host === "127.0.0.1" || host === "::1";
    const key = `${hp}/${proto}/${local}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const ip = host === "0.0.0.0" || host === "::" ? nodeIp : host.startsWith("100.") ? host : null;
    const scheme = ["443", "8443", "9443"].includes(hp) ? "https" : "http";
    out.push({
      text: `${local ? t("localhost only") + " 127.0.0.1" : host === "::" || host === "0.0.0.0" ? t("all interfaces") : host}:${hp} → ${cp}/${proto}`,
      href: !local && proto === "tcp" && ip ? `${scheme}://${ip}:${hp}/` : null, lo: local,
    });
  }
  return out;
}

function ctrDetail(c) {
  const ip = cfgNode(sel)?.tailscaleIp;
  const ports = portLinks(c.ports, ip);
  const portHtml = c.networks === "host"
    ? t("host network: uses host ports directly, Docker shows no mapping")
    : ports.length ? ports.map((p) => p.href
      ? `<span class="pt"><a href="${esc(p.href)}" target="_blank" rel="noopener noreferrer">${esc(p.href)}</a> <span class="lo">${esc(p.text)}</span></span>`
      : `<span class="pt ${p.lo ? "lo" : ""}">${esc(p.text)}</span>`).join("") : t("no published ports");
  const rows = [
    [t("Image"), esc(c.image)],
    [t("Status"), esc(c.status) + (c.health && !String(c.status).includes(c.health) ? ` · ${esc(c.health)}` : "")],
    [t("Project"), esc(c.project || t("(not started by compose)"))],
    [t("Created"), esc((c.createdAt || "").replace(/ [+-]\d{4} \w+$/, "")) + (c.runningFor ? ` · ${esc(c.runningFor)}` : "")],
    [t("Networks"), esc(c.networks || "—")],
    [t("Ports"), portHtml],
    [t("Logs"), `<code>docker logs --tail 100 ${esc(c.name)}</code>`],
  ];
  return `<dl class="xd">${rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>`;
}

function kumaSection(n) {
  const ms = n.kuma || [];
  if (!ms.length) return "";
  const order = { down: 0, pending: 1, unknown: 2, maintenance: 3, up: 4 };
  const rows = [...ms].sort((a, b) => order[a.status] - order[b.status] || a.name.localeCompare(b.name)).map((m) => `
    <div class="km ${m.status === "down" ? "down" : ""}" title="${esc(m.group)} · ${esc(m.type)}${m.time ? "\n" + t("last check") + " " + esc(m.time) + " UTC" : ""}">
      <span class="sq ${m.status === "up" ? "on" : m.status === "down" ? "bad" : "idle"}"></span>
      <span class="nm">${esc(m.name)}</span>
      <span class="n">${m.ping != null ? m.ping + "ms" : "—"}</span>
      <span class="n">${m.uptime24 != null ? (m.uptime24 * 100).toFixed(m.uptime24 >= 0.9995 ? 0 : 1) + "%" : "—"}</span>
      ${m.status === "down" && m.msg ? `<span class="ms2">${esc(m.msg)}</span>` : ""}
    </div>`).join("");
  const down = ms.filter((m) => m.status === "down").length;
  return `<div class="sec-t" style="margin-top:0"><span>KUMA · ${ms.length}${down ? ` · <span style="color:var(--bad)">DOWN ${down}</span>` : ""}</span>
      ${S.kuma?.url ? `<a href="${esc(S.kuma.url)}" target="_blank" rel="noopener noreferrer">${t("status page")} ↗</a>` : ""}</div>
    <div class="km" style="color:var(--fg-3);font-size:11px;letter-spacing:.1em"><span></span><span>NAME</span><span class="n">PING</span><span class="n">24H</span></div>
    ${rows}`;
}

function tabServices(svcs, withKuma = true) {
  const n = S.nodes[sel] || {};
  const kuma = withKuma ? kumaSection(n) : "";
  if (!svcs.length) return kuma + `<div class="empty">${cfgNode(sel).collected ? t("No systemd here (or nothing collected).") : t("Services are not collected for this node.")}</div>`;
  const failed = svcs.filter((u) => u.active === "failed");
  const actives = svcs.filter((u) => u.active !== "failed");
  const key = actives.filter((u) => !SYS_UNIT.test(u.unit));
  const sysu = actives.filter((u) => SYS_UNIT.test(u.unit));
  const row = (u) => {
    const k = `${sel}/${u.scope}/${u.unit}`;
    const isOpen = openSvc.has(k);
    const user = u.scope === "user";
    return `<div class="svc click ${u.active === "failed" ? "failed" : ""}" data-svc="${esc(k)}" role="button" tabindex="0">
      <span class="sq ${u.active === "failed" ? "bad" : u.sub === "running" ? "on" : "idle"}"></span>
      <span class="nm">${esc(u.unit.replace(/\.service$/, ""))}</span>
      <span>${user ? '<span class="tg">USER</span> ' : ""}<span class="tg">${esc(u.sub)}</span></span>
      <span class="ds">${esc(u.desc)}</span></div>` + (isOpen ? `<dl class="xd">
      <dt>${t("Unit")}</dt><dd>${esc(u.unit)}${user ? " (" + t("user unit") + ")" : ""}</dd>
      <dt>${t("State")}</dt><dd>${esc(u.active)} / ${esc(u.sub)}</dd>
      <dt>${t("Description")}</dt><dd>${esc(u.desc || "—")}</dd>
      <dt>${t("Inspect")}</dt><dd><code>${user ? "systemctl --user" : "systemctl"} status ${esc(u.unit)}</code><br><code>${user ? "journalctl --user" : "sudo journalctl"} -u ${esc(u.unit)} -n 100</code></dd></dl>` : "");
  };
  let html = kuma;
  const top = kuma ? "" : 'style="margin-top:0"';
  if (failed.length) html += `<div class="sec-t" ${kuma ? 'style="color:var(--bad)"' : 'style="margin-top:0;color:var(--bad)"'}><span>FAILED · ${failed.length}</span></div>${failed.map(row).join("")}`;
  key.sort((a, b) => (a.sub === "running" ? 0 : 1) - (b.sub === "running" ? 0 : 1) || a.unit.localeCompare(b.unit));
  html += `<div class="sec-t" ${failed.length ? "" : top}><span>${t("Services")} · ${key.length}</span><span>${key.filter((u) => u.sub === "running").length} running</span></div>${key.map(row).join("")}`;
  html += `<div class="sec-t"><span>${t("System units")} · ${sysu.length}</span><button class="linkbtn" id="toggle-sys" type="button">${showSysSvc ? t("hide") : t("show")}</button></div>`;
  if (showSysSvc) html += sysu.map(row).join("");
  return html;
}

function tabLatency() {
  const { list, reversed } = edgesFrom(sel);
  const cfg = cfgNode(sel);
  if (!list.length) {
    return `<div class="empty">${cfg.inTailnet ? t("No latency data yet (the first round takes about half a minute).") : t("Not in the tailnet and no public ping configured, so no latency data.")}</div>`;
  }
  const rows = [...list].sort((a, b) => (a.ms ?? 1e9) - (b.ms ?? 1e9));
  const series = (hist.node === sel && hist.data) ? hist.data.latency : {};
  let html = `<div class="sec-t" style="margin-top:0"><span>${reversed ? t("measured by other nodes") : t("measured from this node")} · ${esc(S.latency.at ? fmtAgo(S.latency.at) : "")}</span><span>24H</span></div>`;
  html += `<div class="lat lat-h"><span>TARGET</span><span class="v">RTT</span><span>ROUTE</span><span>TREND</span></div>`;
  for (const e of rows) {
    const rt = e.ms == null ? ["TIMEOUT", "bad"] : e.route === "relay" ? ["DERP", "relay"] : e.route === "icmp" ? ["ICMP", "icmp"] : ["DIRECT", ""];
    html += `<div class="lat" title="${esc(routeText(e))}${e.min != null ? `\nmin ${fmtMs(e.min)} / max ${fmtMs(e.max)}` : ""}">
      <span class="nm" data-goto="${esc(e.dst)}">${esc(e.dst)}</span>
      <span class="v">${fmtMs(e.ms)}</span>
      <span class="rt ${rt[1]}">${rt[0]}</span>
      <span>${spark(series[e.dst], 92, 18, "#bdbdbd")}</span></div>`;
  }
  return html;
}

function drawMiniChart() {
  const el = $("mini-chart");
  if (!el || !hist.data || hist.node !== sel) return;
  const w = el.clientWidth || 380, h = el.clientHeight || 86;
  const svg = d3.select(el).attr("viewBox", `0 0 ${w} ${h}`);
  svg.selectAll("*").remove();
  const { cpu, mem } = hist.data;
  const pts = [...cpu, ...mem];
  if (pts.length < 2) {
    svg.append("text").attr("x", 0).attr("y", 20).attr("fill", "#6e6e6e").attr("font-size", 12)
      .text(t("History is still building up; check back in a few minutes."));
    return;
  }
  const x = d3.scaleTime().domain(d3.extent(pts, (p) => p[0] * 1000)).range([30, w - 4]);
  const y = d3.scaleLinear().domain([0, 100]).range([h - 16, 6]);
  for (const v of [0, 50, 100]) {
    svg.append("line").attr("x1", 30).attr("x2", w).attr("y1", y(v)).attr("y2", y(v)).attr("stroke", "#1c1c1c");
    svg.append("text").attr("x", 0).attr("y", y(v) + 4).attr("fill", "#5e5e5e").attr("font-size", 10.5).text(v + "%");
  }
  const line = d3.line().x((p) => x(p[0] * 1000)).y((p) => y(p[1]));
  svg.append("path").attr("d", line(cpu)).attr("fill", "none").attr("stroke", "#fff").attr("stroke-width", 1.4);
  svg.append("path").attr("d", line(mem)).attr("fill", "none").attr("stroke", "#8a8a8a").attr("stroke-width", 1.4).attr("stroke-dasharray", "4 3");
  svg.append("text").attr("x", w - 4).attr("y", h - 2).attr("text-anchor", "end").attr("fill", "#7a7a7a").attr("font-size", 10.5)
    .text("— CPU   - - MEM");
}

/* ---------- bottom: event log ---------- */
const logPass = (e) => logFilter === "alert" ? e.level === "warn" || e.level === "error"
  : logFilter === "sel" ? e.node === sel : true;

function evLine(e) {
  return `<span class="t">${hhmmss(e.ts)}</span><span class="k">[${esc(e.kind)}]</span><span class="m" title="${esc(e.msg)}${e.node ? "\n" + t("Click to open {id}", { id: esc(e.node) }) : ""}">${esc(e.msg)}</span>`;
}

function renderLog(rebuild = false) {
  const box = $("log");
  const evs = S.events || [];
  document.querySelectorAll("[data-logf]").forEach((b) => b.classList.toggle("on", b.dataset.logf === logFilter));
  if (rebuild) { box.innerHTML = ""; lastEventId = 0; }
  const fresh = evs.filter((e) => e.id > lastEventId);
  if (!fresh.length && box.childElementCount) return;
  const nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
  box.querySelector(".cursor-line")?.remove();
  box.querySelector(".ev-empty")?.remove();
  for (const e of fresh) {
    lastEventId = Math.max(lastEventId, e.id);
    if (!logPass(e)) continue;
    const div = document.createElement("div");
    div.className = `ev ${e.level}${e.node && cfgNode(e.node) ? " click" : ""}`;
    if (e.node) div.dataset.evnode = e.node;
    div.innerHTML = evLine(e);
    box.appendChild(div);
  }
  if (!box.querySelector(".ev:not(.cursor-line)")) {
    box.insertAdjacentHTML("beforeend", `<div class="ev-empty">${logFilter === "sel" ? t("No recent events for {id}.", { id: esc(sel) }) : t("No recent alerts.")}</div>`);
  }
  while (box.childElementCount > 300) box.firstElementChild.remove();
  const cur = document.createElement("div");
  cur.className = "ev cursor-line";
  cur.innerHTML = `<span class="t">${hhmmss(Date.now() / 1000)}</span><span class="k">&gt;</span><span class="m"><span class="cursor"></span></span>`;
  box.appendChild(cur);
  if (nearBottom || fresh.length === evs.length) box.scrollTop = box.scrollHeight;
}

/* ---------- bottom: latency timeline ---------- */
const GRAYS = ["#ffffff", "#d6d6d6", "#b0b0b0", "#939393", "#7a7a7a", "#c4c4c4", "#a0a0a0", "#868686", "#6c6c6c"];
const DASHES = [null, "5 3", "1.5 3", "8 3 2 3", null, "3 3", "1 2", "6 2", "2 4"];

function chartMsg(el, text) {
  const w = el.clientWidth || 300, h = el.clientHeight || 80;
  const svg = d3.select(el).attr("viewBox", `0 0 ${w} ${h}`);
  svg.selectAll("*").remove();
  svg.append("text").attr("x", 16).attr("y", 28).attr("fill", "#6e6e6e").attr("font-size", 12).text(text);
}

const latencySeries = () => Object.entries(hist.data?.latency || {})
  .filter(([dst, pts]) => pts.length && isVis(dst)).map(([name, pts]) => ({ name, pts }));

function renderTimeline() {
  const el = $("timeline");
  document.querySelectorAll("[data-range]").forEach((b) => b.classList.toggle("on", +b.dataset.range === rangeH));
  if (!el.clientWidth || view !== "map") return;
  $("tl-title").textContent = `LATENCY // ${sel || ""}`;
  if (!hist.data || hist.node !== sel) return chartMsg(el, t("Loading…"));
  const series = latencySeries();
  if (!series.length) {
    $("tl-sub").textContent = "";
    return chartMsg(el, cfgNode(sel)?.inTailnet ? t("No history yet: one point per latency round.") : t("No latency data for this node."));
  }
  const r = drawLineChart(el, series, { unit: "ms", bucket: hist.data.bucket, robust: true });
  if (r) $("tl-sub").textContent = `${rangeLabel()} (${t("{d} of data", { d: fmtDur((r.now - r.x0) / 1000) })}) · ${t("{n} lines", { n: series.length })} · ${t("{m}-min averages", { m: Math.round((hist.data.bucket || 120) / 60) })}`;
}
const rangeLabel = () => (rangeH >= 168 ? t("7 days") : t("{h} hours", { h: rangeH }));

/**
 * Generic line chart: series = [{name, pts: [[ts, v]...], color?, dash?}].
 * End-of-line labels on the right (pushed apart so they never overlap), crosshair readout on hover. unit: ms or %.
 */
function drawLineChart(el, series, o = {}) {
  const w = el.clientWidth, h = el.clientHeight;
  if (!w || !h) return null;
  const svg = d3.select(el).attr("viewBox", `0 0 ${w} ${h}`);
  svg.selectAll("*").remove();
  const pctUnit = o.unit === "%";
  const fmt = pctUnit ? (v) => (v == null ? "—" : Math.round(v) + "%") : fmtMs;
  const m = { l: 46, r: o.legendW ?? 132, t: 12, b: 24 };
  const all = series.flatMap((s) => s.pts).filter((p) => p[1] != null);
  if (!all.length) { chartMsg(el, t("No data.")); return null; }
  const now = Date.now();
  const first = d3.min(all, (p) => p[0] * 1000);
  const x0 = Math.max(now - rangeH * 3600 * 1000, Math.min(first, now - 30 * 60 * 1000));
  const x = d3.scaleTime().domain([x0, now]).range([m.l, w - m.r]);
  // robust: the y max follows the 97th percentile so a few spikes do not flatten the chart (readouts stay exact)
  const vals = all.map((p) => p[1]).sort((a, b) => a - b);
  const vmax = vals.at(-1) || 10, q97 = d3.quantile(vals, 0.97) || vmax;
  const ymax = o.fixedMax || (o.robust && vmax > q97 * 1.6 ? q97 * 1.35 : vmax * 1.15);
  const clipped = !o.fixedMax && o.robust && vmax > ymax;
  if (clipped) m.t = 26;          // room for the note above the plot
  const y = d3.scaleLinear().domain([0, ymax]).nice(4).range([h - m.b, m.t]);

  const gy = svg.append("g").attr("font-size", 10.5).attr("fill", "#5e5e5e");
  for (const v of y.ticks(4)) {
    gy.append("line").attr("x1", m.l).attr("x2", w - m.r).attr("y1", y(v)).attr("y2", y(v)).attr("stroke", "#191919");
    gy.append("text").attr("x", m.l - 8).attr("y", y(v) + 3.5).attr("text-anchor", "end").text(v + (pctUnit ? "%" : "ms"));
  }
  if (clipped) {
    gy.append("text").attr("x", w - m.r).attr("y", 13).attr("text-anchor", "end").attr("fill", "#7a7a7a")
      .text(t("spikes up to {ms} are clipped at the top", { ms: fmtMs(vmax) }));
  }
  const gx = svg.append("g").attr("font-size", 10.5).attr("fill", "#5e5e5e");
  const tfmt = d3.timeFormat(now - x0 > 36 * 3600 * 1000 ? "%m-%d" : "%H:%M");
  for (const t of x.ticks(Math.max(2, Math.floor((w - m.l - m.r) / 90)))) {
    gx.append("line").attr("x1", x(t)).attr("x2", x(t)).attr("y1", h - m.b).attr("y2", h - m.b + 4).attr("stroke", "#444");
    gx.append("text").attr("x", x(t)).attr("y", h - 6).attr("text-anchor", "middle").text(tfmt(t));
  }
  const ss = series.filter((s) => s.pts.some((p) => p[1] != null))
    .sort((a, b) => (b.pts.at(-1)[1] ?? 0) - (a.pts.at(-1)[1] ?? 0));
  const line = d3.line().defined((p) => p[1] != null).x((p) => x(p[0] * 1000)).y((p) => y(Math.min(p[1], y.domain()[1])));
  // do not bridge gaps (e.g. collector downtime): break the line when points are > 3.5 intervals apart
  const gapBreak = (pts) => {
    if (pts.length < 3) return pts;
    const diffs = pts.slice(1).map((p, i) => p[0] - pts[i][0]).sort((a, b) => a - b);
    const stepS = o.bucket || diffs[Math.floor(diffs.length / 2)];
    const out = [pts[0]];
    for (let i = 1; i < pts.length; i++) {
      if (stepS && pts[i][0] - pts[i - 1][0] > stepS * 3.5) out.push([pts[i - 1][0] + stepS, null]);
      out.push(pts[i]);
    }
    return out;
  };
  const ends = [];
  ss.forEach((s, i) => {
    const color = s.color || GRAYS[i % GRAYS.length];
    const dash = s.dash !== undefined ? s.dash : DASHES[i % DASHES.length];
    svg.append("path").attr("d", line(gapBreak(s.pts))).attr("fill", "none").attr("stroke", color).attr("stroke-width", 1.4)
      .attr("stroke-dasharray", dash);
    if (s.pts.length < 4) {
      for (const p of s.pts) svg.append("rect").attr("x", x(p[0] * 1000) - 1.5).attr("y", y(p[1]) - 1.5).attr("width", 3).attr("height", 3).attr("fill", color);
    }
    const last = s.pts.at(-1);
    ends.push({ name: s.name, color, y: y(last[1]), v: last[1] });
  });
  if (m.r > 20) {
    // end labels: push down to avoid overlaps, then shift everything up if they run past the bottom
    const gap = Math.min(13, (h - m.b - m.t) / Math.max(1, ends.length));
    ends.sort((a, b) => a.y - b.y);
    for (let i = 1; i < ends.length; i++) if (ends[i].y - ends[i - 1].y < gap) ends[i].y = ends[i - 1].y + gap;
    const bottom = h - m.b;
    if (ends.length && ends.at(-1).y > bottom) {
      ends.at(-1).y = bottom;
      for (let i = ends.length - 2; i >= 0; i--) if (ends[i + 1].y - ends[i].y < gap) ends[i].y = ends[i + 1].y - gap;
    }
    const gl = svg.append("g").attr("font-size", 11.5);
    for (const e of ends) {
      gl.append("line").attr("x1", w - m.r + 4).attr("x2", w - m.r + 14).attr("y1", e.y).attr("y2", e.y).attr("stroke", e.color);
      gl.append("text").attr("x", w - m.r + 18).attr("y", e.y + 4).attr("fill", e.color).text(`${e.name} ${fmt(e.v)}`);
    }
  }
  // hover readout
  const cross = svg.append("line").attr("y1", m.t).attr("y2", h - m.b).attr("stroke", "#555").attr("stroke-dasharray", "2 3").attr("opacity", 0);
  svg.append("rect").attr("x", m.l).attr("y", m.t).attr("width", Math.max(0, w - m.l - m.r)).attr("height", Math.max(0, h - m.t - m.b))
    .attr("fill", "transparent")
    .on("mousemove", (ev) => {
      const [mx] = d3.pointer(ev);
      const t = x.invert(mx).getTime() / 1000;
      cross.attr("x1", mx).attr("x2", mx).attr("opacity", 1);
      const lines = ss.map((s) => {
        const p = s.pts.reduce((best, q) => (Math.abs(q[0] - t) < Math.abs(best[0] - t) ? q : best), s.pts[0]);
        return `${s.name.padEnd(16)} ${fmt(p[1])}`;
      });
      showTip(ev, `${d3.timeFormat("%m-%d %H:%M")(new Date(t * 1000))}\n${lines.join("\n")}`);
    })
    .on("mouseleave", () => { cross.attr("opacity", 0); hideTip(); });
  return { x0, now };
}

/* ---------- interaction ---------- */
function select(id) {
  if (!id || !cfgNode(id)) return;
  const changed = id !== sel;
  if (changed) { ctrUi.q = ""; ctrUi.open = new Map(); pctr.q = ""; }
  sel = id;
  store.set("ma.sel", sel);
  if (view === "node" && changed) history.replaceState(null, "", `#/node/${encodeURIComponent(id)}`);
  renderAll(true);
  if (changed && logFilter === "sel") renderLog(true);
  loadHistory(true);
  if (view === "node") loadPageEvents(true);
}

/** Open a detail page. Optional focus: {ctr: "node/container"} scrolls to that container and expands it. */
function openNode(id, focus) {
  if (!cfgNode(id)) return;
  closeOverlays();
  pageFocus = focus || null;
  const h = `#/node/${encodeURIComponent(id)}`;
  if (location.hash === h) route(); else location.hash = h;
}
function goMap() { if (view !== "map") location.hash = "#/"; }
const rerenderDetail = () => (view === "node" ? renderPage(true) : renderDetail(true));

/** Routing: #/ overview; #/node/<id> detail page. */
function route() {
  const m = location.hash.match(/^#\/node\/([^/?#]+)/);
  const id = m ? decodeURIComponent(m[1]) : null;
  const prev = view;
  view = id && (!S || cfgNode(id)) ? "node" : "map";
  $("app").classList.toggle("paged", view === "node");
  $("page").hidden = view !== "node";
  hideTip();
  if (view === "node") {
    if (id !== sel) { sel = id; store.set("ma.sel", sel); ctrUi.q = ""; pctr.q = ""; }
    document.title = `${id} · MeshAtlas`;
  } else document.title = "MeshAtlas";
  if (!S) return;
  if (view === "node") {
    if (prev !== "node") $("page").scrollTop = 0;
    renderAll(true);
    loadHistory(true);
    loadPageEvents(true);
  } else if (prev === "node") {
    requestAnimationFrame(() => {
      layoutMap();
      renderAll(true);
      renderTimeline();
      if (pendingLoc) { const k = pendingLoc; pendingLoc = null; openLoc = null; toggleLoc(k); }
      else $("node-list").querySelector(".node-row.sel")?.focus({ preventScroll: true });
    });
  }
}
window.addEventListener("hashchange", route);

function cycleMapMode() {
  const modes = ["node", "mesh", "matrix"];
  mapMode = modes[(modes.indexOf(mapMode) + 1) % modes.length];
  store.set("ma.mode", mapMode);
  M.sig = "";
  renderMap();
}

function step(delta) {
  const ids = listOrder().map((n) => n.id);
  if (!ids.length) return;
  const i = ids.indexOf(sel);
  select(ids[i < 0 ? 0 : (i + delta + ids.length) % ids.length]);
}

document.addEventListener("click", (ev) => {
  const t = ev.target;
  if (t.closest("#sys")) return toggleIssues();
  if (t.closest("#btn-search")) return openPalette();
  if (t.closest("#btn-settings")) return openSettings();
  if (t.closest("#btn-help")) return openHelp();
  if (t.closest("[data-close]")) return closeOverlays();
  if (t.classList.contains("overlay")) return closeOverlays();
  const iss = t.closest("[data-issue-node]");
  if (iss) return openNode(iss.dataset.issueNode);
  if (!$("issues").hidden && !t.closest("#issues")) closeOverlays("issues-only");
  const op = t.closest("[data-open]");
  if (op) return openNode(op.dataset.open);
  if (t.closest("[data-back]")) return goMap();
  const nav = t.closest("[data-pnav]");
  if (nav) return step(+nav.dataset.pnav);
  const row = t.closest(".node-row[data-id]");
  if (row) return select(row.dataset.id);
  const evn = t.closest(".ev[data-evnode]");
  if (evn && cfgNode(evn.dataset.evnode)) return select(evn.dataset.evnode);
  const lf = t.closest("[data-logf]");
  if (lf) { logFilter = lf.dataset.logf; store.set("ma.logf", logFilter); return renderLog(true); }
  const tb = t.closest("[data-tab]");
  if (tb) { tab = tb.dataset.tab; store.set("ma.tab", tab); return renderDetail(true); }
  const mode = t.closest("[data-mode]");
  if (mode) { ctrUi.mode = mode.dataset.mode; return renderDetail(true); }
  const g = t.closest("[data-grp]");
  if (g) {
    const k = g.dataset.grp;
    const cur = g.querySelector(".car").textContent === "▾";
    ctrUi.open.set(k, !cur);
    return renderDetail(true);
  }
  if (t.id === "toggle-sys") { showSysSvc = !showSysSvc; return rerenderDetail(); }
  if (t.closest("a")) return;
  const mm = t.closest("[data-mapmode]");
  if (mm) { mapMode = mm.dataset.mapmode; store.set("ma.mode", mapMode); M.sig = ""; return renderMap(); }
  const rg = t.closest("[data-range]");
  if (rg) { rangeH = +rg.dataset.range; store.set("ma.range", rangeH); renderTimeline(); return loadHistory(true); }
  const cr = t.closest("[data-ctr]");
  if (cr) { const k = cr.dataset.ctr; openCtr.has(k) ? openCtr.delete(k) : openCtr.add(k); return rerenderDetail(); }
  const sv = t.closest("[data-svc]");
  if (sv) { const k = sv.dataset.svc; openSvc.has(k) ? openSvc.delete(k) : openSvc.add(k); return rerenderDetail(); }
  const go = t.closest("[data-goto]");
  if (go) return select(go.dataset.goto);
  if (pageClick(t)) return;
});
document.addEventListener("dblclick", (ev) => {
  const row = ev.target.closest(".node-row[data-id]");
  if (row) openNode(row.dataset.id);
});
document.addEventListener("input", (ev) => {
  if (ev.target.id === "ctr-q") { ctrUi.q = ev.target.value; renderDetail(true); }
  else if (ev.target.id === "pg-ctr-q") { pctr.q = ev.target.value; renderPage(true); }
  else if (ev.target.id === "pal-q") renderPalette();
});

/* Keys: / or ⌘K search, "," settings, ? help, Esc back/close, ↑↓ switch node, Enter details, m map mode */
document.addEventListener("keydown", (ev) => {
  const k = ev.key;
  const inField = /^(INPUT|TEXTAREA|SELECT)$/.test(ev.target.tagName);
  if ((ev.metaKey || ev.ctrlKey) && k.toLowerCase() === "k") { ev.preventDefault(); return togglePalette(); }
  if (k === "Escape") {
    if (closeOverlays()) return ev.preventDefault();
    if (inField) return ev.target.blur();
    if (openLoc) return toggleLoc(null);
    if (view === "node") return goMap();
    return;
  }
  if (overlayOpen()) return;          // dialogs handle their own keys
  if ((k === "Enter" || k === " ") && ev.target.matches?.("[data-ctr],[data-svc]")) { ev.preventDefault(); return ev.target.click(); }
  if (inField || ev.metaKey || ev.ctrlKey || ev.altKey) return;
  if (k === "Enter" && ev.target.matches?.(".node-row[data-id]")) { ev.preventDefault(); return openNode(ev.target.dataset.id); }
  if (k === "/") { ev.preventDefault(); return openPalette(); }
  if (k === ",") { ev.preventDefault(); return openSettings(); }
  if (k === "?") { ev.preventDefault(); return openHelp(); }
  if (ev.target.closest?.("button, a, [role=button], [tabindex]") && (k === "Enter" || k === " ")) return;
  if (k === "Enter" && view === "map") { ev.preventDefault(); return openNode(sel); }
  if (k === "m" && view === "map") return cycleMapMode();
  if (k === "ArrowDown" || k === "ArrowUp" || (view === "node" && (k === "[" || k === "]"))) {
    ev.preventDefault();
    return step(k === "ArrowDown" || k === "]" ? 1 : -1);
  }
});

/* ---------- data loop ---------- */
function renderAll(force = false) {
  if (!S) return;
  if (!sel || !cfgNode(sel)) sel = hub();
  renderTop();
  if (view === "node") return renderPage(force);
  renderList();
  if (force) M.sig = "";
  renderMap();
  renderDetail(force);
  renderLog();
  const foot = prefs.refresh === 0 ? t("Auto refresh paused (turn it on in settings)")
    : S.latency.at ? t("latency {ago} ({s}s)", { ago: fmtAgo(S.latency.at), s: S.latency.elapsed }) + (S.latency.running ? " · " + t("measuring…") : "")
    : S.latency.running ? t("first latency round…") : t("waiting for latency data");
  $("map-foot").textContent = foot;
  $("map-foot").title = foot;
}

/** After a settings change: layout toggles, refresh rate, full re-render. */
function applyPrefs() {
  const app = $("app");
  app.classList.toggle("no-log", !prefs.showLog);
  app.classList.toggle("no-tl", !prefs.showTimeline);
  app.classList.toggle("no-bottom", !prefs.showLog && !prefs.showTimeline);
  schedulePoll();
  tickClock();
  if (!S) return;
  if (!cfgNode(sel)) sel = hub();
  $("node-list").dataset.sig = "";
  M.sig = "";
  if (view === "map") requestAnimationFrame(() => { layoutMap(); renderAll(true); renderTimeline(); });
  else renderAll(true);
}

let pollTimer = null;
function schedulePoll() {
  clearTimeout(pollTimer);
  if (prefs.refresh > 0) pollTimer = setTimeout(async () => { await poll(); schedulePoll(); }, prefs.refresh * 1000);
}

async function poll() {
  try {
    const r = await fetch("api/state", { cache: "no-store" });
    if (!r.ok) throw new Error(r.status);
    S = await r.json();
    apiOk = true;
    const first = !M.proj;
    notifyEvents(S.events || []);
    if (first || (view === "map" && M.fitSig !== JSON.stringify(Object.values(S.config.locations).map((l) => [l.lat, l.lon])))) layoutMap();
    renderAll();
    if (first) {
      loadHistory(true);
      loadUptime();
      if (view === "node") route();
    }
  } catch (e) {
    apiOk = false;
    if (S) renderTop();
    else $("sys-text").textContent = "API OFFLINE";
  }
}

async function loadHistory(force = false) {
  if (!sel) return;
  if (!force && hist.node === sel && hist.hours === rangeH && Date.now() - hist.at < 60000) return;
  const node = sel;
  try {
    const hours = rangeH;
    const r = await fetch(`api/history?node=${encodeURIComponent(node)}&hours=${hours}`, { cache: "no-store" });
    const data = await r.json();
    if (node !== sel || hours !== rangeH) return;
    hist = { node, data, at: Date.now(), hours };
    renderTimeline();
    rerenderDetail();
  } catch { /* try again next time */ }
}

async function loadUptime() {
  try {
    const r = await fetch("api/uptime?hours=24&buckets=48", { cache: "no-store" });
    upt = { ...(await r.json()), at: Date.now() };
    if (view === "map") { if (prefs.listMetric === "uptime") renderList(); renderDetail(true); }
    else renderPage(true);
  } catch { /* try again next time */ }
}

let resizeTimer = null;
const ro = new ResizeObserver(() => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    if (!S) return;
    if (view === "map") { layoutMap(); renderTimeline(); drawMiniChart(); }
    else drawPageCharts();
  }, 120);
});
