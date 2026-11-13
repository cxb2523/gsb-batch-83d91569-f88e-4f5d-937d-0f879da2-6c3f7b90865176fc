"use strict";
/* Display preferences. Stored per browser in localStorage: nothing is written to the server and nobody else is
 * affected. Loaded first: `store` and `prefs` are used by every other script. */

const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode etc. */ } },
};

/** Detail-page modules. The layout is fixed (left dossier + right workspace); settings only toggle them. */
const PAGE_SECTIONS = [
  ["metrics", "Metric tiles"],
  ["resources", "Resource / latency chart"],
  ["latency", "Latency bars"],
  ["containers", "Containers · services · Kuma · links"],
  ["events", "Event stream"],
  ["uptime", "Sidebar: availability"],
  ["alerts", "Sidebar: alerts"],
  ["info", "Sidebar: notes"],
];

/** Top-bar metrics to choose from. Values come from KPI_DEFS in app.js. */
const KPI_CHOICES = [
  ["nodes", "Node count"], ["online", "Online"], ["ctr", "Containers"], ["p50", "Hub P50 latency"],
  ["issues", "Issues"], ["cpu", "Average CPU"], ["kuma", "Kuma up"], ["worst", "Slowest link"], ["derp", "Relayed links"],
];

const PREF_DEFAULTS = {
  lang: "auto",            // auto | en | zh
  hidden: [],              // hidden nodes: out of the list, map and top-bar numbers; still searchable
  sort: "config",          // config | loc | status | latency
  listMetric: "latency",   // latency | cpu | mem | ctr | uptime
  listSpark: true,
  arcLabels: "all",        // all | best | none
  flow: true,
  showIcmp: true,
  locTags: true,
  land: 1,                 // 0 dim / 1 normal / 2 bright
  showLog: true,
  showTimeline: true,
  kpis: ["nodes", "online", "ctr", "p50"],
  hiddenSections: [],
  refresh: 5,              // seconds; 0 = paused
  clock: "local",          // local | utc
  notify: false,
};

let prefs = loadPrefs();

function loadPrefs() {
  const saved = store.get("ma.prefs", {}) || {};
  const p = { ...PREF_DEFAULTS, ...saved };
  p.kpis = (p.kpis || []).filter((k) => KPI_CHOICES.some((c) => c[0] === k)).slice(0, 5);
  return p;
}

function setPref(key, value) {
  prefs[key] = value;
  store.set("ma.prefs", prefs);
  if (key === "lang") applyLang();
  applyPrefs();
}

/* ---------- settings drawer ---------- */
function openSettings() {
  rememberFocus();
  closeOverlays("drawer");
  $("drawer").hidden = false;
  renderSettings();
  $("drawer").querySelector("button, input, select")?.focus();
}

const radio = (key, opts) => `<div class="seg-tg wrap" role="radiogroup">${opts.map(([v, l]) =>
  `<button type="button" role="radio" aria-checked="${prefs[key] === v}" class="${prefs[key] === v ? "on" : ""}" data-pref="${key}" data-val='${JSON.stringify(v)}'>${esc(l)}</button>`).join("")}</div>`;
const toggle = (key, label, hint = "") => `<label class="sw"><input type="checkbox" data-pref="${key}" ${prefs[key] ? "checked" : ""}>
  <span class="sw-box" aria-hidden="true"></span><span class="sw-l">${esc(label)}${hint ? `<small>${esc(hint)}</small>` : ""}</span></label>`;
const check = (attr, key, label, checked, disabled = false) => `<label class="sw sm"><input type="checkbox" ${attr}="${esc(key)}" ${checked ? "checked" : ""} ${disabled ? "disabled" : ""}>
  <span class="sw-box" aria-hidden="true"></span><span class="sw-l">${esc(label)}</span></label>`;

function renderSettings() {
  const all = S ? S.config.nodes : [];
  const notifyState = !("Notification" in window) ? t("Not supported by this browser.")
    : Notification.permission === "denied" ? t("The browser blocked notifications; allow them in the site settings.")
    : Notification.permission === "granted" ? t("Allowed.") : t("The browser will ask for permission.");

  $("drawer-body").innerHTML = `
    <section class="set-sec">
      <h3>${t("Language")}</h3>
      ${radio("lang", [["auto", t("Auto")], ["en", "English"], ["zh", "中文"]])}
    </section>
    <section class="set-sec">
      <h3>${t("Nodes")}</h3>
      <div class="set-row"><span class="set-l">${t("List order")}</span>${radio("sort", [["config", t("Default")], ["loc", t("By location")], ["status", t("Problems first")], ["latency", t("By latency")]])}</div>
      <div class="set-row"><span class="set-l">${t("Right column of the list")}</span>${radio("listMetric", [["latency", t("Latency")], ["cpu", "CPU"], ["mem", t("Memory")], ["ctr", t("Containers")], ["uptime", t("Availability")]])}</div>
      ${toggle("listSpark", t("Show latency sparklines in the list"))}
      <div class="set-sub">${t("Visible nodes")} <small>${t("Hidden nodes leave the list, the map and the top-bar numbers. Search still finds them.")}</small></div>
      <div class="chk-grid">${all.map((n) => check("data-node", n.id, n.id, !prefs.hidden.includes(n.id))).join("")}</div>
    </section>
    <section class="set-sec">
      <h3>${t("Map")}</h3>
      <div class="set-row"><span class="set-l">${t("Latency labels on links")}</span>${radio("arcLabels", [["all", t("All")], ["best", t("Fastest per location")], ["none", t("None")]])}</div>
      <div class="set-row"><span class="set-l">${t("Land brightness")}</span>${radio("land", [[0, t("Dim")], [1, t("Normal")], [2, t("Bright")]])}</div>
      ${toggle("flow", t("Animated flow on links"))}
      ${toggle("showIcmp", t("Show public ping links"), t("Servers outside the tailnet, watched with ICMP"))}
      ${toggle("locTags", t("Show location code and node count"))}
    </section>
    <section class="set-sec">
      <h3>${t("Layout")}</h3>
      ${toggle("showLog", t("Event log at the bottom"))}
      ${toggle("showTimeline", t("Latency timeline at the bottom"), t("With both off the map takes the space."))}
      <div class="set-sub">${t("Top-bar metrics")} <small>${t("Up to 5, in the order you tick them.")}</small></div>
      <div class="chk-grid">${KPI_CHOICES.map(([k, l]) => check("data-kpi", k, t(l), prefs.kpis.includes(k), !prefs.kpis.includes(k) && prefs.kpis.length >= 5)).join("")}</div>
      <div class="set-sub">${t("Detail page modules")} <small>${t("When a module is off, its neighbour takes the space.")}</small></div>
      <div class="chk-grid">${PAGE_SECTIONS.map(([k, l]) => check("data-sec", k, t(l), !prefs.hiddenSections.includes(k))).join("")}</div>
    </section>
    <section class="set-sec">
      <h3>${t("Refresh and time")}</h3>
      <div class="set-row"><span class="set-l">${t("Auto refresh")}</span>${radio("refresh", [[5, t("5 s")], [15, t("15 s")], [60, t("1 min")], [0, t("Paused")]])}</div>
      <div class="set-row"><span class="set-l">${t("Big clock shows")}</span>${radio("clock", [["local", t("Local time")], ["utc", "UTC"]])}</div>
    </section>
    <section class="set-sec">
      <h3>${t("Notifications")}</h3>
      ${toggle("notify", t("Browser notification on new alerts"), t("Node offline, container or service trouble, link down. The page must stay open.") + " " + notifyState)}
    </section>
    <section class="set-sec set-foot">
      <button type="button" class="btn" id="prefs-reset">${t("Reset to defaults")}</button>
      <span class="set-note">${t("Settings live in this browser only.")}</span>
    </section>`;
}

document.addEventListener("click", (ev) => {
  const b = ev.target.closest("#drawer [data-pref][data-val]");
  if (b) {
    setPref(b.dataset.pref, JSON.parse(b.dataset.val));
    return renderSettings();
  }
  if (ev.target.id === "prefs-reset") {
    prefs = { ...PREF_DEFAULTS, hidden: [], kpis: [...PREF_DEFAULTS.kpis], hiddenSections: [] };
    store.set("ma.prefs", prefs);
    applyLang();
    applyPrefs();
    return renderSettings();
  }
});

document.addEventListener("change", async (ev) => {
  const el = ev.target;
  if (!el.closest("#drawer")) return;
  if (el.dataset.pref) {
    if (el.dataset.pref === "notify" && el.checked && "Notification" in window && Notification.permission === "default") {
      const r = await Notification.requestPermission();
      if (r !== "granted") el.checked = false;
    }
    setPref(el.dataset.pref, el.checked);
    return renderSettings();
  }
  if (el.dataset.node) {
    const id = el.dataset.node;
    setPref("hidden", el.checked ? prefs.hidden.filter((x) => x !== id) : [...new Set([...prefs.hidden, id])]);
    return;
  }
  if (el.dataset.kpi) {
    const k = el.dataset.kpi;
    setPref("kpis", el.checked ? [...prefs.kpis.filter((x) => x !== k), k].slice(0, 5) : prefs.kpis.filter((x) => x !== k));
    return renderSettings();
  }
  if (el.dataset.sec) {
    const k = el.dataset.sec;
    setPref("hiddenSections", el.checked ? prefs.hiddenSections.filter((x) => x !== k) : [...new Set([...prefs.hiddenSections, k])]);
  }
});
