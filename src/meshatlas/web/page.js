"use strict";
/* Node detail page (#/node/<id>): a dossier sidebar plus a workspace.
 *   left:  identity / resource bars / availability / alerts / notes (the last block stretches to the bottom)
 *   right: 6 metric tiles → resource or latency chart + latency bars → containers·services·Kuma·links tabs + events
 * Data comes from S / hist / upt that app.js already loads, plus per-node events from api/events. */

const pctr = { q: "", mode: "all", sort: "state", dir: 1, group: false };   // container table filter and sort
let pageFocus = null;     // where to land after opening: {ctr: "node/container"} | {svc: key, sys} | {kuma: true}
let pev = { node: null, list: [], at: 0, lvl: "all", more: false };
let pageSig = "";
let ptab = store.get("ma.ptab", "ctr");          // bottom panel tab: ctr | svc | kuma | link
let pchart = store.get("ma.pchart", "res");      // chart: res (CPU/memory) | lat (latency history)
let hlSel = null, hlUntil = 0;

const showSec = (k) => !prefs.hiddenSections.includes(k);

/* ---------- data ---------- */
async function loadPageEvents(force = false, before = null) {
  if (view !== "node" || !sel) return;
  if (!force && !before && pev.node === sel && Date.now() - pev.at < 30000) return;
  const node = sel, lvl = pev.lvl;
  try {
    const q = new URLSearchParams({ node, limit: "100" });
    if (lvl === "alert") q.set("level", "warn,error");
    if (before) q.set("before", String(before));
    const r = await fetch(`api/events?${q}`, { cache: "no-store" });
    const d = await r.json();
    if (node !== sel || lvl !== pev.lvl) return;
    const got = d.events || [];
    pev = { node, lvl, at: Date.now(), list: before ? [...pev.list, ...got] : got, more: got.length === 100 };
    renderPage(true);
  } catch { /* try again next time */ }
}

/** Events from the database plus newer ones already in api/state, newest first, de-duplicated. */
function pageEvents() {
  const seen = new Set(pev.node === sel ? pev.list.map((e) => e.id) : []);
  const live = (S.events || []).filter((e) => e.node === sel && !seen.has(e.id) &&
    (pev.lvl !== "alert" || e.level === "warn" || e.level === "error"));
  return [...live, ...(pev.node === sel ? pev.list : [])].sort((a, b) => b.id - a.id);
}

/** Bottom tabs this node has (tabs without data are left out). */
function pageTabs(cfg, n) {
  const tabs = [];
  if (n.docker) tabs.push(["ctr", t("Containers"), `${(n.docker.containers || []).length}`]);
  if ((n.services || []).length) tabs.push(["svc", t("Services"), `${n.services.filter((u) => u.sub === "running").length}`, n.services.some((u) => u.active === "failed")]);
  if ((n.kuma || []).length) tabs.push(["kuma", "Kuma", `${n.kuma.length}`, n.kuma.some((m) => m.status === "down")]);
  tabs.push(["link", t("Links"), `${edgesFrom(sel).list.length}`]);
  return tabs;
}

/* ---------- render ---------- */
function renderPage(force = false) {
  if (!S || view !== "node") return;
  const cfg = cfgNode(sel);
  if (!cfg) return;
  const n = S.nodes[sel] || {};
  if (pageFocus?.ctr) { ptab = "ctr"; openCtr.add(pageFocus.ctr); pctr.mode = "all"; pctr.q = ""; }
  if (pageFocus?.svc) { ptab = "svc"; openSvc.add(pageFocus.svc); if (pageFocus.sys) showSysSvc = true; }
  if (pageFocus?.kuma) ptab = "kuma";
  const tabs = pageTabs(cfg, n);
  if (!tabs.some((tb) => tb[0] === ptab)) ptab = tabs[0][0];
  const chartMode = cfg.collected ? pchart : "lat";

  const sig = JSON.stringify([sel, n.collect?.at, n.tailscale?.online, S.latency.at, S.kuma?.at, hist.at, upt?.at, pev.at, pev.lvl,
    pctr, [...openCtr], [...openSvc], showSysSvc, prefs.hiddenSections, prefs.hidden, rangeH, ptab, chartMode,
    (S.events || []).filter((e) => e.node === sel).at(-1)?.id]);
  if (!force && sig === pageSig) return;
  pageSig = sig;

  const page = $("page");
  // remember scroll positions and input focus, restore them after re-rendering
  const keep = {};
  for (const id of ["page", "pg-side", "pg-tbl", "pg-evs"]) { const el = $(id); if (el) keep[id] = el.scrollTop; }
  const active = document.activeElement;
  const qFocused = active && active.id === "pg-ctr-q";
  const caret = qFocused ? active.selectionStart : null;

  const st = nodeStatus(sel), loc = locOf(sel);
  const ids = listOrder().map((x) => x.id);
  const idx = ids.indexOf(sel);

  page.innerHTML = `
    <div class="pg-bar panel">
      <button class="btn ghost" type="button" data-back>← ${t("Back to map")} <kbd>Esc</kbd></button>
      <span class="pg-crumb">NODE // ${esc(loc?.code || "—")} // <b>${esc(sel)}</b></span>
      <span class="pg-nav">
        <button class="ib" type="button" data-pnav="-1" aria-label="${t("Previous node")}" title="${t("Previous node")} (↑ / [)">‹</button>
        <span class="pg-pos">${idx >= 0 ? `${idx + 1} / ${ids.length}` : t("hidden")}</span>
        <button class="ib" type="button" data-pnav="1" aria-label="${t("Next node")}" title="${t("Next node")} (↓ / ])">›</button>
        <button class="btn ghost" type="button" data-copylink>${t("Copy link")}</button>
        <span class="seg-tg" role="group" aria-label="${t("History range")}">${[[1, "1H"], [6, "6H"], [24, "24H"], [168, "7D"]].map(([h, l]) =>
          `<button type="button" data-range="${h}" class="${rangeH === h ? "on" : ""}">${l}</button>`).join("")}</span>
      </span>
    </div>
    <div class="pg-layout">
      <aside class="pg-side" id="pg-side">${sideHtml(cfg, n, st, loc)}</aside>
      ${mainHtml(cfg, n, st, tabs, chartMode)}
    </div>`;

  for (const [id, top] of Object.entries(keep)) { const el = $(id); if (el) el.scrollTop = top; }
  if (qFocused) {
    const q = $("pg-ctr-q");
    if (q) { q.focus(); if (caret != null) q.setSelectionRange(caret, caret); }
  }
  drawPageCharts();
  if (pageFocus) {
    const f = pageFocus;
    pageFocus = null;
    hlSel = f.ctr ? `[data-ctr="${CSS.escape(f.ctr)}"]` : f.svc ? `[data-svc="${CSS.escape(f.svc)}"]` : null;
    hlUntil = Date.now() + 4000;
    const el = hlSel && page.querySelector(hlSel);
    if (el) {
      el.scrollIntoView({ block: "center" });
      el.focus({ preventScroll: true });
    }
  }
  // highlight the row we jumped to from search for 4 s (survives auto-refresh re-renders)
  if (hlSel && Date.now() < hlUntil) page.querySelector(hlSel)?.classList.add("hl");
}

/* ---------- left dossier ---------- */
function sideHtml(cfg, n, st, loc) {
  const sys = n.sys || null;
  const chip = st.online === false ? ["OFFLINE", "off"] : st.level === "warn" ? ["DEGRADED", "warn"] : st.online ? ["ONLINE", ""] : ["NO DATA", "off"];
  const ts = n.tailscale;
  const collect = cfg.collected
    ? (n.collect ? (n.collect.ok ? (cfg.self ? t("local, every {s}s", { s: S.config.intervals.node }) : t("read-only SSH, every {s}s", { s: S.config.intervals.node }))
      : t("last {n} attempts failed", { n: n.collect.fails })) : t("waiting for the first round"))
    : pingsTo(sel).length ? t("public ping from {src}", { src: pingsTo(sel).map((e) => e.src).join(", ") }) : cfg.inTailnet ? t("Tailscale status and latency only") : t("not collected");
  const kv = [
    ["OS", sys?.os || (cfg.kind || "—")],
    ["Kernel", sys?.kernel || "—"],
    ["Tailnet", cfg.inTailnet ? `${cfg.tailscaleIp}${ts ? (ts.online ? " · " + t("online") : " · " + t("offline")) : ""}` : t("not in the tailnet")],
    ["Uptime", sys?.uptime ? fmtDur(sys.uptime) : "—"],
    [t("Location"), `${loc?.name || t("unknown")}${loc?.approx || cfg.approxLoc ? " (" + t("approx.") + ")" : ""}${cfg.where ? " · " + cfg.where : ""}`],
    [t("Collect"), collect],
  ];
  let html = `<section class="panel ps ps-id">
      <h1 class="pg-name">${esc(sel)}</h1>
      <div class="pg-badges"><span class="chip ${chip[1]}">${chip[0]}</span>${sel === hub() ? '<span class="chip off">HUB</span>' : ""}${!isVis(sel) ? '<span class="chip off">' + t("HIDDEN") + '</span>' : ""}</div>
      <div class="d-sub">${esc(cfg.role || "")}</div>
      <dl class="kv2">${kv.map(([a, b]) => `<dt>${esc(a)}</dt><dd title="${esc(b)}">${esc(b)}</dd>`).join("")}</dl>
    </section>`;

  if (sys && !sys.error && (sys.cpu != null || sys.mem)) {
    const rows = [];
    if (sys.cpu != null) rows.push(["CPU", sys.cpu, t("{n} cores · load {l}", { n: sys.ncpu || "?", l: (sys.load || []).join(" / ") })]);
    if (sys.mem) rows.push(["MEM", pct(sys.mem.used, sys.mem.total), `${gib(sys.mem.used)} / ${gib(sys.mem.total)} GiB`]);
    for (const d of sys.disks || []) {
      rows.push([`DISK ${d.mount === "/System/Volumes/Data" ? "/" : d.mount}`, pct(d.used, d.used + d.avail), `${gib(d.used)} / ${gib(d.used + d.avail)} GiB · ${t("free")} ${gib(d.avail)}`]);
    }
    html += `<section class="panel ps">
      <div class="ps-h"><span>RESOURCES</span><span>${n.collect?.at ? `<span class="ago" data-ts="${n.collect.at}">${esc(fmtAgo(n.collect.at))}</span>` : ""}</span></div>
      ${rows.map(([l, p, x]) => `<div class="rb"><span class="rb-l">${esc(l)}</span>${segBar(p)}<span class="rb-v">${p == null ? "—" : Math.round(p) + "%"}</span><span class="rb-x">${esc(x)}</span></div>`).join("")}
    </section>`;
  }

  if (showSec("uptime")) {
    const u = upt?.nodes?.[sel];
    html += `<section class="panel ps">
      <div class="ps-h"><span>AVAILABILITY · 24H</span><span class="ps-big ${u && u.pct < 99 ? "warn" : ""}">${u ? fmtPct(u.pct) : "—"}</span></div>
      ${u ? stripHtml(u.strip, upt.size) : `<div class="strip">${Array.from({ length: 48 }, () => '<i class="na"></i>').join("")}</div>`}
      <div class="strip-ax"><span>${t("24h ago")}</span><span>${t("12h ago")}</span><span>${t("now")}</span></div>
      <div class="ps-x">${u ? t("{n} samples", { n: u.samples }) + (upt.first && upt.first > upt.since + 3600 ? " · " + t("recording since {ago}", { ago: fmtAgo(upt.first) }) : "") : t("Collecting (one sample per node round)")}</div>
    </section>`;
  }

  if (showSec("alerts")) {
    html += `<section class="panel ps">
      <div class="ps-h"><span>ALERTS</span><span>${st.issues.length || ""}</span></div>
      ${st.issues.length ? st.issues.map((txt) => {
        const bad = st.online === false || /offline|unreachable|DOWN|in a row/i.test(txt);
        return `<div class="al ${bad ? "bad" : "warn"}"><span class="sq ${bad ? "bad" : "warn"}"></span><span>${esc(txt.replace(new RegExp("^" + sel.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + " "), ""))}</span></div>`;
      }).join("") : `<div class="al ok"><span class="sq on"></span><span>${t("No alerts")}</span></div>`}
    </section>`;
  }

  if (showSec("info")) {
    const notes = cfg.notes || [];
    html += `<section class="panel ps grow">
      <div class="ps-h"><span>NOTES</span></div>
      ${notes.length ? `<ul class="ps-notes">${notes.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : `<div class="ps-x">${t("No notes. Add them with notes = [...] under [nodes.{id}] in meshatlas.toml.", { id: sel })}</div>`}
      <div class="ps-x">${t("Last collected")}: ${n.collect?.at ? esc(new Date(n.collect.at * 1000).toLocaleString(LANG === "zh" ? "zh-CN" : undefined, { hour12: false })) : "—"}</div>
    </section>`;
  }
  return html;
}

/* ---------- right workspace ---------- */
function mainHtml(cfg, n, st, tabs, chartMode) {
  const showChart = showSec("resources"), showLat = showSec("latency");
  const showBottom = showSec("containers"), showEv = showSec("events");
  const rows = [];
  let html = "";
  if (showSec("metrics")) { rows.push("auto"); html += `<div class="pg-tiles">${tilesHtml(cfg, n)}</div>`; }
  if (showChart || showLat) {
    rows.push(showBottom || showEv ? "minmax(220px, 270px)" : "minmax(300px, 1fr)");
    if (showChart) html += `<section class="panel pp-chart ${showLat ? "s7" : "s12"}">${chartPanel(cfg, chartMode)}</section>`;
    if (showLat) html += `<section class="panel pp-lat ${showChart ? "s5" : "s12"}">${latBarsPanel()}</section>`;
  }
  if (showBottom || showEv) {
    rows.push("minmax(340px, 1fr)");
    if (showBottom) html += `<section class="panel pp-bottom ${showEv ? "s8" : "s12"}">${bottomPanel(cfg, n, tabs)}</section>`;
    if (showEv) html += `<section class="panel pp-ev ${showBottom ? "s4" : "s12"}">${eventsPanel()}</section>`;
  }
  if (!html) html = `<div class="empty s12">${t("All detail modules are off. Turn some on in settings (,).")}</div>`;
  return `<div class="pg-main" style="grid-template-rows:${rows.join(" ") || "auto"}">${html}</div>`;
}

function tile(label, value, sub, o = {}) {
  const cls = o.pct >= 95 ? "bad" : o.pct >= 85 ? "warn" : o.cls || "";
  const vis = o.spark && o.spark.length > 1 ? `<div class="tile-sp">${spark(o.spark, 200, 22, "#cfcfcf")}</div>`
    : o.ratio != null ? `<div class="tile-sp">${segBar(o.ratio * 100)}</div>` : `<div class="tile-sp"></div>`;
  return `<div class="tile panel ${cls}">
    <div class="tile-l">${esc(label)}</div>
    <div class="tile-v">${esc(value)}</div>
    <div class="tile-x" title="${esc(sub)}">${o.subHtml || esc(sub)}</div>
    ${vis}</div>`;
}

function tilesHtml(cfg, n) {
  const sys = n.sys || {};
  const own = hist.node === sel && hist.data ? hist.data : null;
  const toHub = sel === hub() ? null : link(hub(), sel);
  const hubTile = sel === hub()
    ? tile("TO HUB", "—", t("this node is the hub"), { spark: null })
    : tile(`TO ${hub().toUpperCase()}`, toHub ? (toHub.ms == null ? "TIMEOUT" : fmtMs(toHub.ms)) : "—",
      toHub ? routeText(toHub) : t("not measured"), { spark: S.spark[sel], cls: toHub && toHub.ms == null ? "bad" : "" });
  const u = upt?.nodes?.[sel];
  if (!cfg.collected) {
    const st = nodeStatus(sel);
    const probes = pingsTo(sel);
    const loc = locOf(sel);
    return [
      tile("STATUS", st.online === false ? "OFFLINE" : st.online ? "ONLINE" : "—", cfg.inTailnet ? t("Tailscale status") : t("from public ping"), { cls: st.online === false ? "bad" : "" }),
      hubTile,
      tile("AVAIL 24H", u ? fmtPct(u.pct) : "—", u ? t("{n} samples", { n: u.samples }) : t("collecting"), { ratio: u ? u.pct / 100 : null }),
      tile("PROBES", String(edgesFrom(sel).list.length), probes.length ? t("public ping from {src}", { src: probes.map((e) => e.src).join(", ") }) : t("tailscale ping")),
      tile("LOCATION", loc?.code || "—", `${loc?.name || ""} · ${cfg.where || ""}`),
      tile("NETWORK", cfg.inTailnet ? "TAILNET" : "PUBLIC", cfg.inTailnet ? cfg.tailscaleIp : t("not in the tailnet")),
    ].join("");
  }
  const cs = n.docker?.containers || [];
  const run = cs.filter((c) => c.state === "running").length;
  const bad = cs.filter(ctrIssue).length;
  const svcs = n.services || [];
  const failed = svcs.filter((u2) => u2.active === "failed").length;
  const km = n.kuma || [];
  const down = km.filter((m) => m.status === "down").length;
  const memP = sys.mem ? pct(sys.mem.used, sys.mem.total) : null;
  const tiles = [
    tile("CPU", sys.cpu != null ? `${Math.round(sys.cpu)}%` : "—", sys.ncpu ? `${sys.ncpu} cores · load ${(sys.load || [])[0] ?? "—"}` : "—", { pct: sys.cpu, spark: own?.cpu }),
    tile("MEM", memP != null ? `${Math.round(memP)}%` : "—", sys.mem ? `${gib(sys.mem.used)} / ${gib(sys.mem.total)} GiB` : "—", { pct: memP, spark: own?.mem }),
    n.docker ? tile("CONTAINERS", `${run}/${cs.length}`, `running · ${bad} unhealthy`, { ratio: cs.length ? run / cs.length : null, cls: bad ? "warn" : "" })
      : tile("DISK /", sys.disks?.[0] ? `${Math.round(pct(sys.disks[0].used, sys.disks[0].used + sys.disks[0].avail))}%` : "—", t("no Docker"), { ratio: sys.disks?.[0] ? sys.disks[0].used / (sys.disks[0].used + sys.disks[0].avail) : null }),
    tile("SERVICES", svcs.length ? String(svcs.filter((x) => x.sub === "running").length) : "—", svcs.length ? `running · ${failed} failed` : t("no systemd"),
      { cls: failed ? "warn" : "", subHtml: svcs.length ? `running · <span class="${failed ? "t-warn" : ""}">${failed} failed</span>` : null, ratio: svcs.length ? 1 - failed / svcs.length : null }),
    km.length ? tile("KUMA", `${km.length - down}/${km.length}`, down ? `up · ${down} DOWN` : t("all up"), { cls: down ? "warn" : "", subHtml: down ? `up · <span class="t-bad">${down} DOWN</span>` : null, ratio: (km.length - down) / km.length })
      : tile("AVAIL 24H", u ? fmtPct(u.pct) : "—", u ? t("{n} samples", { n: u.samples }) : t("collecting"), { ratio: u ? u.pct / 100 : null }),
    hubTile,
  ];
  return tiles.join("");
}

function chartPanel(cfg, mode) {
  const seg = cfg.collected ? `<span class="seg-tg" role="group" aria-label="${t("Chart content")}">
      <button type="button" data-pchart="res" class="${mode === "res" ? "on" : ""}">${t("Resources")}</button>
      <button type="button" data-pchart="lat" class="${mode === "lat" ? "on" : ""}">${t("Latency history")}</button></span>` : "";
  const d = hist.node === sel && hist.data ? hist.data : null;
  const info = d ? `${rangeLabel()} · ` + t("{m} min per point", { m: Math.round(d.bucket / 60) }) : "";
  return `<div class="ph"><span class="ph-t">${mode === "res" ? "RESOURCES" : "LATENCY HISTORY"} // ${rangeLabel()}</span><span class="ph-r">${info}</span>${seg}</div>
    <div class="pg-fill"><svg class="pg-svg" id="pg-chart" role="img" aria-label="${mode === "res" ? t("CPU and memory history") : t("Latency history")}"></svg></div>`;
}

function latBarsPanel() {
  const { list, reversed } = edgesFrom(sel);
  const rows = [...list].filter((e) => isVis(e.dst)).sort((a, b) => (a.ms ?? 1e9) - (b.ms ?? 1e9));
  const max = Math.max(150, ...rows.map((e) => e.ms || 0));
  const body = rows.length ? rows.map((e) => {
    const rt = e.ms == null ? ["TIMEOUT", "bad"] : e.route === "relay" ? ["DERP", "relay"] : e.route === "icmp" ? ["ICMP", "icmp"] : ["DIRECT", ""];
    const w = e.ms == null ? 100 : Math.max(2, (e.ms / max) * 100);
    return `<button class="lb" type="button" data-goto="${esc(e.dst)}" title="${esc(edgeTip(e))}\n${t("Click to open {id}", { id: esc(e.dst) })}">
      <span class="lb-n">${esc(e.dst)}</span>
      <span class="lb-bar ${rt[1]}"><i style="width:${w.toFixed(1)}%"></i></span>
      <span class="lb-v">${fmtMs(e.ms)}</span>
      <span class="rt ${rt[1]}">${rt[0]}</span></button>`;
  }).join("") : `<div class="empty">${cfgNode(sel).inTailnet ? t("No latency data yet.") : t("No latency data for this node.")}</div>`;
  return `<div class="ph"><span class="ph-t">LATENCY // ${reversed ? "TO" : "FROM"} ${esc(sel.toUpperCase())}</span><span class="ph-r">${t("{n} links", { n: rows.length })}${S.latency.at ? " · " + esc(fmtAgo(S.latency.at)) : ""}</span></div>
    <div class="pg-scroll lbs">${body}</div>`;
}

function bottomPanel(cfg, n, tabs) {
  let body = "", tools = "";
  if (ptab === "ctr") [tools, body] = ctrTable(cfg, n);
  else if (ptab === "svc") body = `<div class="pg-pad">${tabServices(n.services || [], false)}</div>`;
  else if (ptab === "kuma") body = `<div class="pg-pad">${kumaSection(n)}</div>`;
  else body = linkStats();
  if (tabs.length === 1) {
    return `<div class="ph"><span class="ph-t">LINKS // ${rangeLabel()}</span><span class="ph-r">${esc(linkStatsNote())}</span></div>
      <div class="pg-scroll" id="pg-tbl">${body}</div>`;
  }
  return `<div class="ph pg-tabs" role="tablist">
      ${tabs.map(([k, l, c, warn]) => `<button type="button" role="tab" aria-selected="${ptab === k}" class="ptab ${ptab === k ? "on" : ""}" data-ptab="${k}">${l}<small class="${warn ? "t-warn" : ""}">${c}${warn ? " !" : ""}</small></button>`).join("")}
    </div>
    ${tools}
    <div class="pg-scroll" id="pg-tbl">${body}</div>`;
}

const linkStatsNote = () => {
  const { reversed } = edgesFrom(sel);
  return `${reversed ? t("measured by other nodes") : t("measured from this node")} · ` + t("over the selected range");
};

/** Per-link stats over the selected range: now, average, P95, max, jitter, route and trend. */
function linkStats() {
  const { list } = edgesFrom(sel);
  const rows = [...list].filter((e) => isVis(e.dst)).sort((a, b) => (a.ms ?? 1e9) - (b.ms ?? 1e9));
  if (!rows.length) return `<div class="empty pg-pad">${cfgNode(sel).inTailnet ? t("No latency data yet.") : t("No latency data for this node.")}</div>`;
  const series = hist.node === sel && hist.data ? hist.data.latency : {};
  const head = `<div class="lst lst-h"><span>PEER</span><span class="n">NOW</span><span class="n">AVG</span><span class="n">P95</span><span class="n">MAX</span><span class="n">JITTER</span><span>ROUTE</span><span>TREND</span></div>`;
  const body = rows.map((e) => {
    const pts = series[e.dst] || [];
    const v = pts.map((p) => p[1]).filter((x) => x != null).sort((a, b) => a - b);
    const avg = v.length ? d3.mean(v) : null, p95 = v.length ? d3.quantile(v, 0.95) : null;
    const max = v.length ? v.at(-1) : null, jit = v.length > 1 ? d3.deviation(v) : null;
    const rt = e.ms == null ? ["TIMEOUT", "bad"] : e.route === "relay" ? ["DERP", "relay"] : e.route === "icmp" ? ["ICMP", "icmp"] : ["DIRECT", ""];
    const hot = (x) => (x != null && avg != null && x > avg * 2.5 && x - avg > 60 ? "t-warn" : "");
    return `<div class="lst" title="${esc(edgeTip(e))}">
      <button class="lst-n" type="button" data-goto="${esc(e.dst)}" title="${t("Open {id}", { id: esc(e.dst) })}">${esc(e.dst)}</button>
      <span class="n ${e.ms == null ? "t-bad" : ""}">${fmtMs(e.ms)}</span>
      <span class="n">${fmtMs(avg)}</span>
      <span class="n ${hot(p95)}">${fmtMs(p95)}</span>
      <span class="n ${hot(max)}">${fmtMs(max)}</span>
      <span class="n">${jit != null ? "±" + fmtMs(jit) : "—"}</span>
      <span><span class="rt ${rt[1]}">${rt[0]}</span></span>
      <span class="lst-sp">${spark(pts, 200, 20, "#bdbdbd")}</span></div>`;
  }).join("");
  return `<div class="lst-wrap">${head}${body}</div>`;
}

function eventsPanel() {
  const list = pageEvents();
  const today = new Date().toDateString();
  const fmt = (ts) => { const d = new Date(ts * 1000); return d3.timeFormat(d.toDateString() === today ? "%H:%M:%S" : "%m-%d %H:%M")(d); };
  const body = list.length ? list.map((e) => `<div class="es ${e.level}">
      <span class="es-dot"></span><span class="es-t">${fmt(e.ts)}</span>
      <span class="es-m"><b>[${esc(e.kind)}]</b> ${esc(e.msg)}</span></div>`).join("")
    : `<div class="empty">${pev.node === sel ? (pev.lvl === "alert" ? t("No alerts for this node.") : t("No events recorded for this node yet.")) : t("Loading…")}</div>`;
  return `<div class="ph"><span class="ph-t">EVENT STREAM</span><span class="ph-r">${list.length ? t("{n} events", { n: list.length + (pev.more ? "+" : "") }) : ""}</span>
      <span class="seg-tg" role="group" aria-label="${t("Event filter")}">${[["all", t("All")], ["alert", t("Alerts")]].map(([k, l]) =>
        `<button type="button" data-pevlvl="${k}" class="${pev.lvl === k ? "on" : ""}">${l}</button>`).join("")}</span></div>
    <div class="pg-scroll" id="pg-evs">${body}${pev.more ? `<button class="btn ghost es-more" type="button" data-pevmore>${t("Load older")}</button>` : ""}</div>
    <div class="pg-foot">${t("Newest first · kept for {d} days", { d: 7 })}</div>`;
}

function stripHtml(strip, size) {
  const mins = size ? Math.round(size / 60) : null;
  return `<div class="strip" role="img" aria-label="${t("Online history")}">${strip.map((v, i) => {
    const cls = v == null ? "na" : v >= 0.999 ? "up" : v <= 0.001 ? "down" : "part";
    const ago = mins ? t("{h}h ago", { h: Math.round((strip.length - i) * mins / 60 * 10) / 10 }) : "";
    const tip = v == null ? t("no data") : t("online {p}%", { p: Math.round(v * 100) });
    return `<i class="${cls}" title="${ago ? ago + " · " : ""}${tip}"></i>`;
  }).join("")}</div>`;
}

/* container table */
const CTR_COLS = [["state", "STATE"], ["name", "NAME"], ["project", "PROJECT"], ["image", "IMAGE"], ["cpu", "CPU", "n"], ["mem", "MEM", "n"], ["ports", "PORTS"], ["up", "STATUS"]];
const memBytes = (s) => {
  const m = String(s || "").match(/([\d.]+)\s*([KMGT]?i?B)/i);
  if (!m) return -1;
  const mul = { B: 1, KIB: 1024, KB: 1e3, MIB: 1024 ** 2, MB: 1e6, GIB: 1024 ** 3, GB: 1e9, TIB: 1024 ** 4, TB: 1e12 }[m[2].toUpperCase()] || 1;
  return parseFloat(m[1]) * mul;
};
const stateRank = (c) => (ctrIssue(c) ? 0 : c.state === "running" ? 1 : 2);

function ctrTable(cfg, n) {
  if (n.docker.error) return ["", `<div class="pg-pad"><div class="note err">${esc(n.docker.error)}</div></div>`];
  const all = n.docker.containers || [];
  const q = pctr.q.trim().toLowerCase();
  const modeOk = (c, mode) => mode === "run" ? c.state === "running" : mode === "stop" ? c.state !== "running" : mode === "issue" ? ctrIssue(c) : true;
  const list = all.filter((c) => modeOk(c, pctr.mode) &&
    (!q || [c.name, c.project, c.image, c.ports].some((v) => String(v || "").toLowerCase().includes(q))));
  const key = {
    state: (c) => [stateRank(c), c.name], name: (c) => [c.name], project: (c) => [c.project || "~", c.name],
    image: (c) => [c.image || "", c.name], cpu: (c) => [-(c.state === "running" ? c.cpu ?? -1 : -1), c.name],
    mem: (c) => [-(c.state === "running" ? memBytes(c.mem) : -1), c.name], ports: (c) => [c.ports ? 0 : 1, c.name],
    up: (c) => [c.createdAt || "", c.name],
  }[pctr.sort] || ((c) => [c.name]);
  const cmp = (a, b) => {
    const ka = key(a), kb = key(b);
    for (let i = 0; i < ka.length; i++) {
      if (ka[i] < kb[i]) return -pctr.dir;
      if (ka[i] > kb[i]) return pctr.dir;
    }
    return 0;
  };
  list.sort(cmp);
  if (pctr.group) list.sort((a, b) => (a.project || "~").localeCompare(b.project || "~") || cmp(a, b));
  const run = all.filter((c) => c.state === "running");
  const modes = [["all", t("All"), all.length], ["run", t("Running"), run.length], ["stop", t("Stopped"), all.length - run.length], ["issue", t("Problems"), all.filter(ctrIssue).length]];
  const ip = cfg.tailscaleIp;
  let rows = "", lastGroup = null;
  for (const c of list) {
    if (pctr.group && (c.project || "") !== lastGroup) {
      lastGroup = c.project || "";
      const g = list.filter((x) => (x.project || "") === lastGroup);
      rows += `<div class="ptr-g"><span>${esc(lastGroup || t("(standalone)"))}</span><span>${g.filter((x) => x.state === "running").length}/${g.length}</span></div>`;
    }
    const [tg, cls] = ctrTag(c);
    const k = `${sel}/${c.name}`;
    const open = openCtr.has(k);
    const ports = portLinks(c.ports, ip);
    const firstLink = ports.find((p) => p.href);
    const portCell = c.networks === "host" ? `<span class="dim">${t("host network")}</span>`
      : firstLink ? `<a href="${esc(firstLink.href)}" target="_blank" rel="noopener noreferrer">:${esc(firstLink.href.split(":").at(-1).replace("/", ""))}</a>${ports.length > 1 ? ` <span class="dim">+${ports.length - 1}</span>` : ""}`
      : ports.length ? `<span class="dim">${ports.some((p) => p.lo) ? t("localhost") : t("internal")}</span>` : `<span class="dim">—</span>`;
    const running = c.state === "running";
    rows += `<div class="ptr ${running ? "" : "stopped"} ${open ? "open" : ""}" data-ctr="${esc(k)}" role="button" tabindex="0" aria-expanded="${open}">
        <span class="st ${cls}"><i class="sq ${cls === "run" ? "on" : cls === "ext" ? "off" : cls === "dead" ? "bad" : "warn"}"></i>${tg}</span>
        <span class="nm">${esc(c.name)}</span>
        <span class="pj">${esc(c.project || "—")}</span>
        <span class="im" title="${esc(c.image)}">${esc(c.image)}</span>
        <span class="n">${running && c.cpu != null ? c.cpu.toFixed(1) + "%" : "—"}</span>
        <span class="n">${running && c.mem ? esc(c.mem.replace("iB", "")) : "—"}</span>
        <span class="po">${portCell}</span>
        <span class="up" title="${esc(c.status)}">${esc(String(c.status || "").replace(/^Up /, ""))}</span>
      </div>${open ? `<div class="ptr-x">${ctrDetail(c)}</div>` : ""}`;
  }
  const head = CTR_COLS.map(([k, l, num]) => `<button type="button" class="${num || ""} ${pctr.sort === k ? "on" : ""}" data-psort="${k}" aria-sort="${pctr.sort === k ? (pctr.dir > 0 ? "ascending" : "descending") : "none"}">${l}${pctr.sort === k ? (pctr.dir > 0 ? " ▲" : " ▼") : ""}</button>`).join("");
  const tools = `<div class="pg-tools">
      <input class="search sm" id="pg-ctr-q" type="search" placeholder="${t("Filter: container / project / image / port")}" value="${esc(pctr.q)}" autocomplete="off" spellcheck="false" aria-label="${t("Filter containers")}">
      ${modes.map(([k, l, c]) => `<button class="fchip ${pctr.mode === k ? "on" : ""}" data-pmode="${k}" type="button">${l} <small>${c}</small></button>`).join("")}
      <button class="fchip ${pctr.group ? "on" : ""}" data-pgroup type="button" aria-pressed="${pctr.group}" title="${t("Group by compose project")}">${t("Group by project")}</button>
      <span class="pg-count">${list.length === all.length ? String(all.length) : `${list.length} / ${all.length}`}</span>
    </div>`;
  const body = `<div class="ptable" role="table" aria-label="${t("Containers")}">
      <div class="ptr ptr-h" role="row">${head}</div>
      ${rows || `<div class="empty pg-pad">${t("No matching containers.")}</div>`}
    </div>${all.some((c) => c.statsStale) ? `<div class="pg-foot">${t("CPU / memory refresh every few rounds on this node")}</div>` : ""}`;
  return [tools, body];
}

/* ---------- charts ---------- */
function drawPageCharts() {
  if (view !== "node") return;
  const el = $("pg-chart");
  if (!el) return;
  const cfg = cfgNode(sel);
  const mode = cfg.collected ? pchart : "lat";
  const ok = hist.node === sel && hist.data;
  if (!ok) return chartMsg(el, t("Loading…"));
  if (mode === "res") {
    if (hist.data.cpu.length < 2) return chartMsg(el, t("History is still building up; check back in a few minutes."));
    drawLineChart(el, [
      { name: "CPU", pts: hist.data.cpu, color: "#ffffff", dash: null },
      { name: "MEM", pts: hist.data.mem, color: "#9a9a9a", dash: "4 3" },
    ], { unit: "%", fixedMax: 100, legendW: 92, bucket: hist.data.bucket });
  } else {
    const series = latencySeries();
    if (!series.length) return chartMsg(el, t("No latency history."));
    drawLineChart(el, series, { unit: "ms", legendW: 160, bucket: hist.data.bucket, robust: true });
  }
}

/* ---------- clicks inside the detail page (app.js hands them over last) ---------- */
function pageClick(t) {
  const tb = t.closest("[data-ptab]");
  if (tb) { ptab = tb.dataset.ptab; store.set("ma.ptab", ptab); renderPage(true); $("pg-tbl") && ($("pg-tbl").scrollTop = 0); return true; }
  const pc = t.closest("[data-pchart]");
  if (pc) { pchart = pc.dataset.pchart; store.set("ma.pchart", pchart); renderPage(true); return true; }
  const ps = t.closest("[data-psort]");
  if (ps) {
    const k = ps.dataset.psort;
    if (pctr.sort === k) pctr.dir = -pctr.dir; else { pctr.sort = k; pctr.dir = 1; }
    renderPage(true);
    $("page").querySelector(`[data-psort="${k}"]`)?.focus();
    return true;
  }
  const pm = t.closest("[data-pmode]");
  if (pm) { pctr.mode = pm.dataset.pmode; renderPage(true); return true; }
  if (t.closest("[data-pgroup]")) { pctr.group = !pctr.group; renderPage(true); return true; }
  const pl = t.closest("[data-pevlvl]");
  if (pl) { pev.lvl = pl.dataset.pevlvl; pev.list = []; pev.node = null; renderPage(true); loadPageEvents(true); return true; }
  if (t.closest("[data-pevmore]")) { const last = pev.list.at(-1); if (last) loadPageEvents(true, last.id); return true; }
  const cp = t.closest("[data-copylink]");
  if (cp) {
    const done = () => { cp.textContent = t("Copied ✓"); setTimeout(() => { cp.textContent = t("Copy link"); }, 1500); };
    navigator.clipboard?.writeText(location.href).then(done, () => { cp.textContent = location.href; });
    return true;
  }
  return false;
}
