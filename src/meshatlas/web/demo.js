"use strict";
/* Demo mode: a made-up tailnet spread over seven cities, generated in the browser.
 * Active when config.js sets window.MESHATLAS.demo (``meshatlas demo`` and the GitHub Pages site).
 * It answers api/* requests itself, so the rest of the app runs unchanged. */

(function () {
  if (!(window.MESHATLAS && window.MESHATLAS.demo)) return;

  // deterministic pseudo-random numbers so every visitor sees the same tailnet
  let seed = 20261113;
  const rnd = () => { seed |= 0; seed = (seed + 0x6d2b79f5) | 0; let x = Math.imul(seed ^ (seed >>> 15), 1 | seed); x = (x + Math.imul(x ^ (x >>> 7), 61 | x)) ^ x; return ((x ^ (x >>> 14)) >>> 0) / 4294967296; };
  const pick = (arr) => arr[Math.floor(rnd() * arr.length)];
  const GiB = 2 ** 30;
  const T0 = Date.now() / 1000;

  const LOCS = {
    sfo: { name: "San Francisco", code: "SFO", lat: 37.77, lon: -122.42 },
    nyc: { name: "New York", code: "NYC", lat: 40.71, lon: -74.01 },
    lhr: { name: "London", code: "LHR", lat: 51.51, lon: -0.13 },
    fra: { name: "Frankfurt", code: "FRA", lat: 50.11, lon: 8.68 },
    sin: { name: "Singapore", code: "SIN", lat: 1.35, lon: 103.82 },
    tok: { name: "Tokyo", code: "TOK", lat: 35.68, lon: 139.69 },
    syd: { name: "Sydney", code: "SYD", lat: -33.87, lon: 151.21 },
  };

  const CTRS = {
    homelab: ["immich-server", "immich-ml", "immich-db", "immich-redis", "jellyfin", "sonarr", "radarr", "prowlarr", "qbittorrent",
      "nextcloud", "nextcloud-db", "nextcloud-redis", "vaultwarden", "paperless", "paperless-db", "home-assistant", "mosquitto",
      "zigbee2mqtt", "grafana", "prometheus", "node-exporter", "cadvisor", "uptime-kuma", "traefik", "authelia", "gitea",
      "gitea-db", "code-server", "homepage", "adguard", "syncthing", "freshrss", "miniflux", "stirling-pdf", "it-tools", "ntfy"],
    nas: ["minio", "restic-server", "samba", "photoprism", "photoprism-db", "scrutiny", "duplicati", "rclone-sync", "filebrowser", "netdata"],
    "vps-fra": ["caddy", "headscale-ui", "umami", "umami-db", "plausible", "plausible-db", "clickhouse", "wireguard-ui"],
    "vps-nyc": ["mailcow-postfix", "mailcow-dovecot", "mailcow-rspamd", "unbound", "acme"],
    "vps-tok": ["caddy", "speedtest", "derper", "vector"],
    "build-lhr": ["gitea-runner", "registry", "buildkitd", "minio-cache", "drone"],
    "backup-syd": ["restic-rest", "healthchecks"],
  };
  const PROJ = (name) => name.split("-")[0].replace(/^(node|cadvisor)$/, "monitoring").replace(/^(prometheus|grafana)$/, "monitoring");

  const NODES = [
    { id: "homelab", loc: "sfo", role: "Home server", where: "garage rack", kind: "linux", os: "linux", ip: "100.64.0.1", self: true, ncpu: 16, mem: 64, cpu: 18, disks: [["/", 1000, 0.41], ["/srv", 8000, 0.63]] },
    { id: "nas", loc: "sfo", role: "NAS", where: "garage rack", kind: "linux", os: "linux", ip: "100.64.0.2", ncpu: 4, mem: 16, cpu: 7, disks: [["/", 256, 0.22], ["/tank", 24000, 0.71]] },
    { id: "pi-gateway", loc: "sfo", role: "Raspberry Pi · subnet router", where: "hallway", kind: "linux", os: "linux", ip: "100.64.0.3", ncpu: 4, mem: 4, cpu: 4, disks: [["/", 64, 0.38]], noDocker: true },
    { id: "macbook", loc: "sfo", role: "Laptop", where: "", kind: "mac", os: "macOS", ip: "100.64.0.10", tailOnly: true },
    { id: "phone", loc: "sfo", role: "Phone", where: "", kind: "ios", os: "iOS", ip: "100.64.0.11", tailOnly: true, relay: "sfo" },
    { id: "vps-fra", loc: "fra", role: "Edge proxy · analytics", where: "Hetzner", kind: "linux", os: "linux", ip: "100.64.1.1", ncpu: 4, mem: 8, cpu: 12, disks: [["/", 160, 0.48]] },
    { id: "vps-nyc", loc: "nyc", role: "Mail · DNS", where: "DigitalOcean", kind: "linux", os: "linux", ip: "100.64.1.2", ncpu: 2, mem: 4, cpu: 9, disks: [["/", 80, 0.57]] },
    { id: "build-lhr", loc: "lhr", role: "CI runner", where: "OVH", kind: "linux", os: "linux", ip: "100.64.1.3", ncpu: 8, mem: 32, cpu: 34, disks: [["/", 512, 0.66]] },
    { id: "vps-tok", loc: "tok", role: "Asia edge · custom DERP", where: "Vultr", kind: "linux", os: "linux", ip: "100.64.1.4", ncpu: 2, mem: 4, cpu: 6, disks: [["/", 55, 0.33]] },
    { id: "probe-sin", loc: "sin", role: "Latency probe", where: "Linode", kind: "linux", os: "linux", ip: "100.64.1.5", tailOnly: true },
    { id: "backup-syd", loc: "syd", role: "Offsite backup", where: "parents' house", kind: "linux", os: "linux", ip: "100.64.1.6", ncpu: 4, mem: 8, cpu: 3, disks: [["/", 120, 0.31], ["/backup", 12000, 0.82]], relay: "syd" },
    { id: "status-page", loc: "fra", role: "Public status page", where: "outside the tailnet", kind: "linux", external: true },
  ];
  const byId = Object.fromEntries(NODES.map((n) => [n.id, n]));

  function dist(a, b) {
    const r = Math.PI / 180, A = LOCS[a], B = LOCS[b];
    const h = Math.sin((B.lat - A.lat) * r / 2) ** 2 + Math.cos(A.lat * r) * Math.cos(B.lat * r) * Math.sin((B.lon - A.lon) * r / 2) ** 2;
    return 12742 * Math.asin(Math.sqrt(h));
  }
  /** Base RTT for a pair: light in fibre (~200 km/ms, ×1.4 for real routes), plus a few ms, plus DERP detours. */
  function baseMs(a, b) {
    const na = byId[a], nb = byId[b];
    let ms = 2.5 + (2 * dist(na.loc, nb.loc) / 200) * 1.4;
    if (na.relay || nb.relay) ms += 38;
    return ms;
  }
  const routeOf = (a, b) => (byId[a].relay || byId[b].relay ? "relay" : "direct");
  const derpOf = (a, b) => `DERP(${byId[a].relay || byId[b].relay})`;
  const wave = (t, phase, period = 5400) => Math.sin(t / period + phase);

  // containers, services, Kuma
  const containers = {};
  for (const [id, names] of Object.entries(CTRS)) {
    containers[id] = names.map((name, i) => {
      const port = 3000 + Math.floor(rnd() * 6000);
      const stopped = id === "homelab" && (name === "qbittorrent" || name === "stirling-pdf");
      const unhealthy = id === "backup-syd" && name === "healthchecks";
      return {
        name, image: `ghcr.io/example/${name}:${pick(["latest", "1.4", "2.0.3", "stable"])}`,
        state: stopped ? "exited" : "running",
        status: stopped ? "Exited (0) 3 days ago" : unhealthy ? "Up 2 days (unhealthy)" : `Up ${pick(["2 days", "5 days", "3 weeks", "6 hours"])}${i % 3 ? " (healthy)" : ""}`,
        health: unhealthy ? "unhealthy" : i % 3 ? "healthy" : "",
        project: PROJ(name), ports: i % 4 === 0 ? "" : i % 5 === 0 ? `127.0.0.1:${port}->${port}/tcp` : `0.0.0.0:${port}->${port}/tcp, [::]:${port}->${port}/tcp`,
        networks: `${PROJ(name)}_default`, runningFor: pick(["2 days ago", "5 days ago", "3 weeks ago"]), createdAt: "2026-11-01 09:12:44 +0000 UTC",
        cpu: stopped ? null : Math.round(rnd() * 400) / 100, memPct: Math.round(rnd() * 800) / 100,
        mem: stopped ? "" : `${(rnd() * 900 + 20).toFixed(1)}MiB`,
      };
    });
  }
  const SVC = ["docker", "tailscaled", "ssh", "systemd-journald", "systemd-networkd", "cron", "chrony", "node_exporter"];
  function services(id) {
    const list = SVC.map((u) => ({ unit: `${u}.service`, active: "active", sub: "running", desc: u, scope: "system" }));
    if (id === "backup-syd") list.push({ unit: "restic-prune.service", active: "failed", sub: "failed", desc: "Prune old restic snapshots", scope: "system" });
    if (id === "homelab") list.push({ unit: "zfs-scrub.timer", active: "active", sub: "waiting", desc: "Monthly ZFS scrub", scope: "system" });
    if (id === "pi-gateway") list.push({ unit: "pihole-FTL.service", active: "active", sub: "running", desc: "Pi-hole FTL", scope: "system" });
    return list;
  }
  const KUMA = [
    ["Immich", "up", 41], ["Jellyfin", "up", 12], ["Nextcloud", "up", 88], ["Vaultwarden", "up", 9], ["Home Assistant", "up", 15],
    ["Gitea", "up", 22], ["vps-fra caddy", "up", 151], ["vps-nyc mail", "up", 71], ["backup-syd heartbeat", "down", null],
  ].map(([name, status, ping], i) => ({ id: i + 1, name, group: "Services", type: "http", status, ping, time: "", msg: status === "down" ? "No heartbeat for 2h 14m" : "",
    uptime24: status === "down" ? 0.912 : 0.998 + rnd() * 0.002, node: NODES.find((n) => name.includes(n.id))?.id || "homelab" }));

  // events: a backlog plus a new one every ~35 s
  const EVT = [
    ["SYNC", "info", "homelab", "homelab first collection done · 1.9s · 34/36 containers running"],
    ["NODE", "info", null, "tailnet example.ts.net: 12 nodes, 10 online"],
    ["LINK", "warn", "backup-syd", "homelab → backup-syd route direct → relay"],
    ["SVC", "warn", "backup-syd", "backup-syd/restic-prune.service failed"],
    ["KUMA", "warn", "backup-syd", "backup-syd heartbeat up → down"],
    ["CTR", "ok", "vps-fra", "vps-fra/plausible exited → running"],
    ["CTR", "warn", "backup-syd", "backup-syd/healthchecks became unhealthy"],
    ["LINK", "warn", "vps-tok", "homelab → vps-tok jumped to 214ms (was 118ms)"],
    ["CTR", "info", "build-lhr", "build-lhr/gitea-runner appeared (running)"],
    ["NODE", "error", "phone", "phone went offline"],
    ["NODE", "ok", "phone", "phone is back online"],
  ];
  const LIVE = [
    ["CTR", "info", "build-lhr", "build-lhr/buildkitd running → exited"], ["CTR", "ok", "build-lhr", "build-lhr/buildkitd exited → running"],
    ["LINK", "warn", "vps-tok", "homelab → vps-tok jumped to 196ms (was 117ms)"], ["KUMA", "ok", "homelab", "Jellyfin pending → up"],
    ["CTR", "info", "homelab", "homelab/paperless restarted"], ["NODE", "info", "macbook", "macbook is back online"],
  ];
  const events = EVT.map(([kind, level, node, msg], i) => ({ id: i + 1, ts: T0 - (EVT.length - i) * 1500, kind, level, node, msg }));

  function edgesNow(now) {
    const out = [];
    const peers = NODES.filter((n) => !n.external);
    const collected = peers.filter((n) => !n.tailOnly);
    for (const src of collected) {
      for (const dst of peers) {
        if (dst.id === src.id || (!src.self && dst.id === "phone")) continue;
        const b = baseMs(src.id, dst.id);
        const ms = Math.round((b * (1 + 0.06 * wave(now, src.ip.length + dst.ip.length)) + rnd() * 2) * 10) / 10;
        out.push({ src: src.id, dst: dst.id, ms, min: Math.round(ms * 0.94 * 10) / 10, max: Math.round(ms * 1.12 * 10) / 10, state: "ok",
          route: routeOf(src.id, dst.id), derp: routeOf(src.id, dst.id) === "relay" ? derpOf(src.id, dst.id) : null, via: "tailscale" });
      }
    }
    for (const src of ["homelab", "vps-fra"]) {
      const b = baseMs(src, "vps-fra") || 3;
      out.push({ src, dst: "status-page", ms: Math.round((src === "vps-fra" ? 1.2 : b + 4) * 10) / 10, min: null, max: null, state: "ok", route: "icmp", derp: null, via: "icmp" });
    }
    return out;
  }

  function sys(n, now) {
    if (n.tailOnly || n.external) return null;
    const cpu = Math.max(1, Math.round((n.cpu * (1 + 0.5 * wave(now, n.ncpu, 900)) + rnd() * 3) * 10) / 10);
    return { os: n.id === "pi-gateway" ? "Debian GNU/Linux 12 (bookworm)" : "Ubuntu 24.04.1 LTS", kernel: "6.8.0-48-generic",
      uptime: 86400 * (4 + n.ncpu) + (now - T0), load: [cpu / 25, cpu / 28, cpu / 30].map((x) => Math.round(x * 100) / 100),
      ncpu: n.ncpu, cpu, mem: { total: n.mem * GiB, used: n.mem * GiB * (0.35 + 0.25 * (n.cpu / 40)) },
      disks: n.disks.map(([m, size, f]) => ({ mount: m, total: size * GiB, used: size * GiB * f, avail: size * GiB * (1 - f) })) };
  }

  function state() {
    const now = Date.now() / 1000;
    if (now - (events.at(-1)?.ts || 0) > 35) {
      const [kind, level, node, msg] = LIVE[events.length % LIVE.length];
      events.push({ id: events.length + 1, ts: now, kind, level, node, msg });
    }
    const edges = edgesNow(now);
    const nodes = {};
    for (const n of NODES) {
      const offline = n.id === "phone" && Math.floor(now / 600) % 3 === 0;
      nodes[n.id] = {
        collect: n.tailOnly || n.external ? null : { ok: true, at: now - 20, elapsed: Math.round((1.4 + rnd()) * 100) / 100, error: null, stale: false, fails: 0, dataAt: now - 20 },
        tailscale: n.external ? null : { online: !offline, lastSeen: offline ? new Date((now - 900) * 1000).toISOString() : null, relay: n.relay || n.loc, self: !!n.self, active: true, os: n.os },
        sys: sys(n, now), docker: CTRS[n.id] ? { containers: containers[n.id], stats: true } : n.noDocker ? null : null,
        services: n.tailOnly || n.external ? null : services(n.id), kuma: KUMA.filter((m) => m.node === n.id),
      };
    }
    const spark = {};
    for (const e of edges.filter((x) => x.src === "homelab")) spark[e.dst] = Array.from({ length: 30 }, (_, i) => [now - (30 - i) * 120, Math.round(e.ms * (1 + 0.08 * wave(now - (30 - i) * 120, e.dst.length, 1500)) * 10) / 10]);
    return {
      now, startedAt: T0 - 86400 * 3,
      config: {
        title: "MESHATLAS", subtitle: "DEMO · GENERATED DATA", hub: "homelab", tailnet: "example.ts.net",
        locations: LOCS, intervals: { node: 120, latency: 120 },
        nodes: NODES.map((n) => ({ id: n.id, loc: n.loc, where: n.where, role: n.role, kind: n.kind, os: n.os || "", notes: n.id === "backup-syd" ? ["Behind CGNAT, so it is reached through DERP.", "Restic prune has been failing since the disk passed 80%."] : n.id === "status-page" ? ["Not in the tailnet: watched with ICMP from homelab and vps-fra."] : [],
          self: !!n.self, tailscaleIp: n.external ? null : n.ip, inTailnet: !n.external, collected: !(n.tailOnly || n.external), external: !!n.external, tags: n.external ? [] : ["tag:server"] })),
      },
      nodes, extraNodes: [], tailscale: { at: now - 30, error: null },
      latency: { at: now - 40, edges, error: null, elapsed: 3.2, running: false },
      kuma: { at: now - 30, error: null, url: null }, spark, events: events.slice(-150),
    };
  }

  /** Rare, deterministic latency spikes (~0.4 % of points) so charts look like a real network, not noise. */
  const spikeAt = (ts, key) => { const x = Math.sin(Math.floor(ts / 120) * 12.9898 + key.length * 78.233) * 43758.5453; return x - Math.floor(x) < 0.004; };

  function history(node, hours) {
    const now = Date.now() / 1000;
    const bucket = Math.max(120, Math.floor(hours * 3600 / 240));
    const pts = (fn) => { const out = []; for (let ts = now - hours * 3600; ts <= now; ts += bucket) out.push([ts, fn(ts)]); return out; };
    const latency = {};
    for (const e of edgesNow(now).filter((x) => x.src === node || x.dst === node)) {
      const other = e.src === node ? e.dst : e.src;
      const b = e.src === node ? baseMs(node, other) : baseMs(other, node);
      latency[other] = pts((ts) => Math.round((b * (1 + 0.07 * wave(ts, other.length)) + (spikeAt(ts, other) ? b * 1.6 : 0)) * 10) / 10);
    }
    const n = byId[node];
    const cpu = n.cpu ? pts((ts) => Math.max(0.5, Math.round(n.cpu * (1 + 0.6 * wave(ts, 1, 3600)) * 10) / 10)) : [];
    const mem = n.mem ? pts((ts) => Math.round((48 + 12 * wave(ts, 2, 20000)) * 10) / 10) : [];
    const status = pts((ts) => (node === "backup-syd" && now - ts > 5 * 3600 && now - ts < 5.6 * 3600 ? 0 : node === "phone" && Math.floor(ts / 600) % 3 === 0 ? 0 : 1));
    return { node, hours, bucket, latency, cpu, mem, status };
  }

  function uptime(hours, nb) {
    const now = Date.now() / 1000, since = now - hours * 3600, size = hours * 3600 / nb;
    const nodes = {};
    for (const n of NODES) {
      const strip = Array.from({ length: nb }, (_, i) => (n.id === "backup-syd" && i > nb * 0.7 && i < nb * 0.76 ? 0 : n.id === "phone" && i % 3 === 0 ? 0.6 : 1));
      nodes[n.id] = { pct: Math.round(1000 * strip.reduce((a, b) => a + b, 0) / nb) / 10, samples: Math.round(hours * 30), strip };
    }
    return { hours, buckets: nb, since, size, first: since, nodes };
  }

  function eventsFor(q) {
    let list = [...events].reverse();
    if (q.get("node")) list = list.filter((e) => e.node === q.get("node"));
    if (q.get("level")) list = list.filter((e) => q.get("level").split(",").includes(e.level));
    if (q.get("before")) list = list.filter((e) => e.id < +q.get("before"));
    return { events: list.slice(0, +(q.get("limit") || 100)) };
  }

  const realFetch = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const url = new URL(typeof input === "string" ? input : input.url, location.href);
    const m = url.pathname.match(/\/api\/(\w+)$/);
    if (!m) return realFetch(input, init);
    const q = url.searchParams;
    const body = m[1] === "state" ? state()
      : m[1] === "history" ? history(q.get("node"), +(q.get("hours") || 24))
      : m[1] === "uptime" ? uptime(+(q.get("hours") || 24), +(q.get("buckets") || 48))
      : m[1] === "events" ? eventsFor(q) : { error: "not found" };
    return new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } });
  };
})();
