"use strict";
/* Search palette (⌘K), issues popover, keyboard help, latency matrix, browser notifications and boot. */

let pendingLoc = null;     // location to open after returning from a detail page
let lastFocus = null;      // where focus goes back when a dialog closes

/* ---------- overlays ---------- */
const MODALS = ["palette", "drawer", "help"];
const overlayOpen = () => MODALS.some((id) => !$(id).hidden);

/** Close overlays. keep: the one to leave open; "issues-only" closes just the issues popover. Returns true if anything closed. */
function closeOverlays(keep) {
  if (keep === "issues-only") {
    if ($("issues").hidden) return false;
    $("issues").hidden = true;
    $("sys").setAttribute("aria-expanded", "false");
    return true;
  }
  let closed = false;
  for (const id of [...MODALS, "issues"]) {
    if (id !== keep && !$(id).hidden) { $(id).hidden = true; closed = true; }
  }
  if (keep !== "issues") $("sys").setAttribute("aria-expanded", "false");
  if (closed && !keep && lastFocus && document.contains(lastFocus)) lastFocus.focus({ preventScroll: true });
  if (closed && !keep) lastFocus = null;
  return closed;
}
function rememberFocus() { if (!overlayOpen()) lastFocus = document.activeElement; }

/* ---------- issues popover ---------- */
function toggleIssues() {
  const el = $("issues");
  if (!el.hidden) return closeOverlays("issues-only");
  closeOverlays("issues");
  el.hidden = false;
  $("sys").setAttribute("aria-expanded", "true");
  renderIssues();
}

function renderIssues() {
  if (!S) return;
  const list = computeIssues();
  $("issues").innerHTML = `
    <div class="iss-h"><span>ISSUES · ${list.length}</span><button class="ib" type="button" data-close aria-label="${t("Close")}">×</button></div>
    ${list.length ? list.map((i) => i.node
      ? `<button class="iss" type="button" data-issue-node="${esc(i.node)}"><span class="sq ${i.level === "bad" ? "bad" : "warn"}"></span><span class="iss-n">${esc(i.node)}</span><span class="iss-t">${esc(i.text)}</span><span class="iss-go">${t("Details")} ↗</span></button>`
      : `<div class="iss"><span class="sq warn"></span><span class="iss-n">${t("Collector")}</span><span class="iss-t">${esc(i.text)}</span><span></span></div>`).join("")
      : `<div class="iss-ok">${t("All clear, nothing to report.")}</div>`}`;
}

/* ---------- keyboard help ---------- */
function openHelp() {
  rememberFocus();
  closeOverlays("help");
  $("help").hidden = false;
  $("help").querySelector("[data-close]")?.focus();
}

/* ---------- search palette ---------- */
let palSel = 0, palItems = [];
const TYPE_RANK = { node: 0, location: 1, container: 2, service: 3, kuma: 4, command: 5 };
const TYPE_LABEL = () => ({ node: t("Nodes"), location: t("Locations"), container: t("Containers"), service: t("Services"), kuma: "Kuma", command: t("Commands") });

function openPalette() {
  rememberFocus();
  closeOverlays("palette");
  $("palette").hidden = false;
  const q = $("pal-q");
  q.value = "";
  renderPalette();
  q.focus();
}
function togglePalette() { $("palette").hidden ? openPalette() : closeOverlays(); }

function showLocation(k) {
  if (mapMode === "matrix") { mapMode = "node"; store.set("ma.mode", mapMode); }
  if (view === "node") { pendingLoc = k; location.hash = "#/"; } else { openLoc = null; toggleLoc(k); }
}
function setMapMode(m) {
  mapMode = m;
  store.set("ma.mode", m);
  M.sig = "";
  if (view === "node") location.hash = "#/"; else renderMap();
}

/** Search index: nodes, locations, containers, services (non-system and failed ones), Kuma monitors, commands. */
function buildIndex() {
  const out = [];
  if (!S) return out;
  for (const c of allNodes()) {
    const loc = S.config.locations[c.loc];
    out.push({ type: "node", label: c.id, sub: [loc?.name, c.role, c.where, isVis(c.id) ? "" : t("hidden")].filter(Boolean).join(" · "),
      kw: `${c.tailscaleIp || ""} ${loc?.code || ""} ${c.os || ""}`, dot: nodeStatus(c.id).level, run: () => openNode(c.id) });
  }
  for (const [k, l] of Object.entries(S.config.locations)) {
    const ns = allNodes().filter((n) => n.loc === k);
    if (!ns.length) continue;
    out.push({ type: "location", label: `${l.code}  ${l.name}`, sub: ns.map((n) => n.id).join(", "), kw: k, run: () => showLocation(k) });
  }
  for (const c of allNodes()) {
    const n = S.nodes[c.id] || {};
    for (const x of n.docker?.containers || []) {
      out.push({ type: "container", label: x.name, sub: `${c.id} · ${x.project || t("standalone")} · ${x.image}`, kw: x.ports || "",
        dot: ctrIssue(x) ? "warn" : x.state === "running" ? "on" : "off", run: () => openNode(c.id, { ctr: `${c.id}/${x.name}` }) });
    }
    for (const u of n.services || []) {
      const isSys = SYS_UNIT.test(u.unit);
      if (isSys && u.active !== "failed") continue;
      const key = `${c.id}/${u.scope}/${u.unit}`;
      out.push({ type: "service", label: u.unit.replace(/\.service$/, ""), sub: `${c.id} · ${u.sub}${u.scope === "user" ? " · " + t("user unit") : ""} · ${u.desc || ""}`,
        dot: u.active === "failed" ? "bad" : u.sub === "running" ? "on" : "off", run: () => openNode(c.id, { svc: key, sys: isSys }) });
    }
    for (const m of n.kuma || []) {
      out.push({ type: "kuma", label: m.name, sub: `${c.id} · ${m.status.toUpperCase()}${m.ping != null ? " · " + m.ping + "ms" : ""}`,
        dot: m.status === "up" ? "on" : m.status === "down" ? "bad" : "off", run: () => openNode(c.id, { kuma: true }) });
    }
  }
  const cmds = [
    [t("Map: links from the selected node"), "map node", () => setMapMode("node")],
    [t("Map: whole mesh"), "mesh all", () => setMapMode("mesh")],
    [t("Map: latency matrix"), "matrix table", () => setMapMode("matrix")],
    [t("Open details of {id}", { id: sel }), "detail page", () => openNode(sel)],
    [t("Back to the map"), "back home map", () => goMap()],
    [t("Display settings"), "settings preferences options", () => openSettings()],
    [t("Keyboard shortcuts"), "help keys shortcuts", () => openHelp()],
    [prefs.refresh ? t("Pause auto refresh") : t("Resume auto refresh (5 s)"), "pause resume refresh", () => setPref("refresh", prefs.refresh ? 0 : 5)],
    [t("Refresh now"), "refresh reload", () => poll()],
    ...(S.kuma?.url ? [[t("Open the Uptime Kuma status page"), "kuma status", () => window.open(S.kuma.url, "_blank", "noopener")]] : []),
  ];
  for (const [label, kw, run] of cmds) out.push({ type: "command", label, sub: "", kw, run });
  return out;
}

function palScore(item, q, toks) {
  const hay = `${item.label} ${item.sub} ${item.kw || ""}`.toLowerCase();
  if (!toks.every((x) => hay.includes(x))) return null;
  const label = item.label.toLowerCase();
  const s = label === q ? 0 : label.startsWith(toks[0]) ? 1 : label.includes(toks[0]) ? 2 : 3;
  return s * 10 + (TYPE_RANK[item.type] ?? 9);
}

function renderPalette() {
  const q = $("pal-q").value.trim().toLowerCase();
  const items = buildIndex();
  if (!q) palItems = items.filter((i) => i.type === "node" || i.type === "command");
  else {
    const toks = q.split(/\s+/);
    palItems = items.map((i) => ({ i, s: palScore(i, q, toks) })).filter((x) => x.s != null)
      .sort((a, b) => a.s - b.s).slice(0, 60).map((x) => x.i);
  }
  palSel = 0;
  const box = $("pal-list");
  if (!palItems.length) {
    box.innerHTML = `<div class="pal-empty">${t("No matches. Try a node, container, service, Kuma monitor, location or command.")}</div>`;
    return;
  }
  const labels = TYPE_LABEL();
  let last = null;
  box.innerHTML = palItems.map((it, i) => {
    const head = it.type !== last ? `<div class="pal-g">${esc(labels[it.type])}</div>` : "";
    last = it.type;
    return `${head}<div class="pal-row ${i === 0 ? "on" : ""}" id="pal-${i}" data-pal="${i}" role="option" aria-selected="${i === 0}">
      ${it.dot ? `<span class="sq ${sqClass(it.dot)}"></span>` : `<span class="pal-ic">›</span>`}
      <span class="pal-l">${hl(it.label, q)}</span><span class="pal-s">${hl(it.sub, q)}</span></div>`;
  }).join("");
  $("pal-q").setAttribute("aria-activedescendant", "pal-0");
}
/** Highlight the first matching word. */
function hl(text, q) {
  const tok = q.split(/\s+/)[0];
  if (!tok) return esc(text);
  const i = text.toLowerCase().indexOf(tok);
  if (i < 0) return esc(text);
  return esc(text.slice(0, i)) + `<mark>${esc(text.slice(i, i + tok.length))}</mark>` + esc(text.slice(i + tok.length));
}
function palMove(d) {
  if (!palItems.length) return;
  $(`pal-${palSel}`)?.classList.remove("on");
  $(`pal-${palSel}`)?.setAttribute("aria-selected", "false");
  palSel = (palSel + d + palItems.length) % palItems.length;
  const el = $(`pal-${palSel}`);
  el.classList.add("on");
  el.setAttribute("aria-selected", "true");
  el.scrollIntoView({ block: "nearest" });
  $("pal-q").setAttribute("aria-activedescendant", `pal-${palSel}`);
}
function palRun(i) {
  const it = palItems[i];
  if (!it) return;
  closeOverlays();
  it.run();
}
$("pal-q").addEventListener("keydown", (ev) => {
  if (ev.key === "ArrowDown") { ev.preventDefault(); palMove(1); }
  else if (ev.key === "ArrowUp") { ev.preventDefault(); palMove(-1); }
  else if (ev.key === "Enter") { ev.preventDefault(); palRun(palSel); }
});
$("pal-list").addEventListener("click", (ev) => {
  const r = ev.target.closest("[data-pal]");
  if (r) palRun(+r.dataset.pal);
});
$("pal-list").addEventListener("mousemove", (ev) => {
  const r = ev.target.closest("[data-pal]");
  if (r && +r.dataset.pal !== palSel) palMove(+r.dataset.pal - palSel);
});

/* keep Tab inside open dialogs */
document.addEventListener("keydown", (ev) => {
  if (ev.key !== "Tab") return;
  const box = MODALS.map((id) => $(id)).find((el) => !el.hidden);
  if (!box) return;
  const f = [...box.querySelectorAll("button:not([disabled]), input:not([disabled]), [tabindex='0'], a[href]")].filter((e) => e.offsetParent);
  if (!f.length) return;
  if (ev.shiftKey && document.activeElement === f[0]) { ev.preventDefault(); f.at(-1).focus(); }
  else if (!ev.shiftKey && document.activeElement === f.at(-1)) { ev.preventDefault(); f[0].focus(); }
});

/* ---------- latency matrix (third map mode) ---------- */
function renderMatrix() {
  const ids = listOrder().map((n) => n.id);
  const edges = (S.latency.edges || []).filter((e) => isVis(e.src) && isVis(e.dst));
  const sources = ids.filter((id) => edges.some((e) => e.src === id));
  const cell = (src, dst) => {
    if (src === dst) return `<td class="self">·</td>`;
    const e = edges.find((x) => x.src === src && x.dst === dst);
    if (!e) return `<td class="na"></td>`;
    const tip = edgeTip(e);
    if (e.ms == null) return `<td class="dead" title="${esc(tip)}">✕</td>`;
    return `<td class="t${tier(e.ms)} r-${e.route || "x"}" title="${esc(tip)}" data-goto="${esc(src)}">${e.ms < 10 ? e.ms.toFixed(1) : Math.round(e.ms)}</td>`;
  };
  const head = ids.map((id) => `<th class="col ${id === sel ? "on" : ""}" scope="col"><button type="button" data-goto="${esc(id)}" title="${esc(id)}">${esc(id)}</button></th>`).join("");
  const rows = sources.map((s) => `<tr class="${s === sel ? "on" : ""}"><th scope="row"><button type="button" data-goto="${esc(s)}">${esc(s)}</button></th>${ids.map((d) => cell(s, d)).join("")}</tr>`).join("");
  $("matrix").innerHTML = sources.length ? `
    <div class="mx-wrap"><table class="mx">
      <thead><tr><th class="corner">FROM ↓ · TO →</th>${head}</tr></thead>
      <tbody>${rows}</tbody></table></div>
    <div class="mx-note">${t("Numbers are round-trip times in ms; brighter is faster.")} <span class="r-relay">${t("Dashed underline")}</span> = ${t("DERP / peer relay")}, <span class="r-icmp">${t("dotted underline")}</span> = ${t("public ping")}, ✕ = ${t("unreachable")}. ${t("Click a number to select its source.")}</div>`
    : `<div class="empty" style="padding:20px">${t("No latency data yet.")}</div>`;
  const dead = edges.filter((e) => e.ms == null).length;
  $("map-sub").textContent = t("Latency matrix · {s} sources × {n} nodes · {e} links", { s: sources.length, n: ids.length, e: edges.length }) + (dead ? " · " + t("{n} down", { n: dead }) : "");
}

/* ---------- browser notifications ---------- */
let notifiedId = 0;
function notifyEvents(evs) {
  if (!evs.length) return;
  const maxId = Math.max(...evs.map((e) => e.id));
  if (!notifiedId) { notifiedId = maxId; return; }      // never replay older events on first load
  const fresh = evs.filter((e) => e.id > notifiedId && (e.level === "error" || e.level === "warn") && e.ts > bootAt);
  notifiedId = Math.max(notifiedId, maxId);
  if (!prefs.notify || !fresh.length || !("Notification" in window) || Notification.permission !== "granted") return;
  for (const e of fresh.slice(-3)) {
    try {
      const nt = new Notification(`${e.level === "error" ? "✕" : "!"} ${e.node || "MeshAtlas"} · ${e.kind}`, { body: e.msg, tag: `ma-${e.id}` });
      nt.onclick = () => { window.focus(); if (e.node) openNode(e.node); nt.close(); };
    } catch { /* some browsers only allow notifications from a service worker */ }
  }
}

/* ---------- boot ---------- */
(async function main() {
  // URL parameters (handy for links and screenshots): ?lang=en|zh  ?mode=node|mesh|matrix  ?q=<search>
  const qp = new URLSearchParams(location.search);
  if (["en", "zh"].includes(qp.get("lang"))) prefs.lang = qp.get("lang");     // this visit only, not saved
  if (["node", "mesh", "matrix"].includes(qp.get("mode"))) mapMode = qp.get("mode");
  applyLang();
  ro.observe($("map"));
  ro.observe($("timeline").parentNode);
  ro.observe($("page"));
  applyPrefs();
  route();
  tickClock();
  setInterval(tickClock, 1000);
  try { await loadLand(); } catch { /* the map still works without land */ }
  await poll();
  schedulePoll();
  if (qp.get("q")) { openPalette(); $("pal-q").value = qp.get("q"); renderPalette(); }
  setInterval(() => loadHistory(false), 15000);
  setInterval(loadUptime, 60000);
  setInterval(() => loadPageEvents(false), 30000);
})();
