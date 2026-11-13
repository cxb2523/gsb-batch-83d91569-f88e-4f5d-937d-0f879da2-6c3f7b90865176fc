"""Collectors, shared state and history store.

Everything here is read-only towards the machines being watched:
  * ``tailscale status --json`` and ``tailscale ping`` on the hub (the machine running MeshAtlas)
  * optional SSH collection: ``remote_collect.py`` and a ping script are piped to ``python3 -`` over SSH
  * optional ICMP ping for servers outside the tailnet
  * optional Uptime Kuma public status page
"""

import json
import shlex
import sqlite3
import statistics
import subprocess
import threading
import time
import traceback
import urllib.request
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from . import tailscale
from .derp import region

HERE = Path(__file__).resolve().parent
REMOTE_SCRIPT = (HERE / "remote_collect.py").read_bytes()
NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))
KUMA_STATUS = {0: "down", 1: "up", 2: "pending", 3: "maintenance"}
PUBLIC_NODE_KEYS = ("id", "loc", "where", "role", "kind", "notes", "parent", "self", "tailscaleIp", "os", "tags",
                    "external", "approxLoc")


def now():
    return time.time()


def short(text, limit=160):
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit] + "…"


def _iso_age_days(iso):
    """Days since a tailscale timestamp like 2026-11-12T22:16:57.123456789Z (nanoseconds, so parse by hand)."""
    if not iso:
        return None
    try:
        t = datetime.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - t).total_seconds() / 86400


class Store:
    """SQLite history: latency, CPU/mem metrics, events and online status. Kept for ``keep_days``."""

    def __init__(self, path, keep_days):
        self.path = str(path)
        self.keep_days = keep_days
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.db() as c:
            c.execute("CREATE TABLE IF NOT EXISTS latency (ts REAL, src TEXT, dst TEXT, ms REAL, route TEXT)")
            c.execute("CREATE INDEX IF NOT EXISTS latency_src_ts ON latency(src, ts)")
            c.execute("CREATE INDEX IF NOT EXISTS latency_dst_ts ON latency(dst, ts)")
            c.execute("CREATE TABLE IF NOT EXISTS metrics (ts REAL, node TEXT, cpu REAL, mem REAL)")
            c.execute("CREATE INDEX IF NOT EXISTS metrics_node_ts ON metrics(node, ts)")
            c.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, kind TEXT, "
                      "level TEXT, msg TEXT, node TEXT)")
            c.execute("CREATE INDEX IF NOT EXISTS events_node_id ON events(node, id)")
            c.execute("CREATE INDEX IF NOT EXISTS events_ts ON events(ts)")
            c.execute("CREATE TABLE IF NOT EXISTS status (ts REAL, node TEXT, online INTEGER)")
            c.execute("CREATE INDEX IF NOT EXISTS status_node_ts ON status(node, ts)")
            c.execute("CREATE INDEX IF NOT EXISTS status_ts ON status(ts)")

    def db(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def prune(self):
        cutoff = now() - self.keep_days * 86400
        with self.db() as c:
            for table in ("latency", "metrics", "events", "status"):
                c.execute(f"DELETE FROM {table} WHERE ts < ?", (cutoff,))


def bucketize(rows, bucket):
    agg = {}
    for key, ts, val in rows:
        if val is None:
            continue
        b = int(ts // bucket) * bucket
        agg.setdefault(key, {}).setdefault(b, []).append(val)
    return {k: [[b + bucket / 2, round(sum(v) / len(v), 2)] for b, v in sorted(series.items())]
            for k, series in agg.items()}


class Atlas:
    """Owns the collectors, the in-memory state and the history store."""

    def __init__(self, cfg, data_dir):
        self.cfg = cfg
        self.col = cfg["collect"]
        self.store = Store(Path(data_dir) / "history.db", self.col["keep_days"])
        self.lock = threading.Lock()
        self.ev_lock = threading.Lock()
        self.events = deque(maxlen=400)
        self.last_event_id = 0
        self.started = now()
        self.hub = None
        self.nodes = {}            # id -> node description (discovered + config overrides + externals)
        self.locations = {}
        self.ts_peers = {}         # id -> tailscale peer info
        self.ts_meta = {"at": None, "error": None, "tailnet": ""}
        self.results = {}          # id -> last SSH/local collection result
        self.last_stats = {}
        self.latency = {"at": None, "edges": [], "error": None, "elapsed": None, "running": False}
        self.kuma = {"at": None, "monitors": [], "error": None, "url": None}
        self.probe_fails = {}
        self.probe_last = {}
        self._derp, self._derp_ids, self._derp_at = {}, {}, 0
        self._nearest, self._nearest_at = None, 0
        self._load_recent_events()

    # ---------- events ----------
    def _load_recent_events(self):
        with self.store.db() as c:
            rows = c.execute("SELECT id, ts, kind, level, msg, node FROM events ORDER BY id DESC LIMIT 150").fetchall()
        for r in reversed(rows):
            self.events.append(dict(zip(("id", "ts", "kind", "level", "msg", "node"), r)))
        if rows:
            self.last_event_id = rows[0][0]

    def emit(self, kind, msg, level="info", node=None):
        ts = now()
        with self.ev_lock:
            try:
                with self.store.db() as c:
                    eid = c.execute("INSERT INTO events (ts, kind, level, msg, node) VALUES (?,?,?,?,?)",
                                    (ts, kind, level, msg, node)).lastrowid
            except sqlite3.Error:
                eid = self.last_event_id + 1
            self.last_event_id = max(self.last_event_id, eid)
            with self.lock:
                self.events.append({"id": eid, "ts": ts, "kind": kind, "level": level, "msg": msg, "node": node})

    # ---------- commands ----------
    def ssh(self, target, remote_cmd, stdin=None, timeout=60):
        base = ["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={self.col['ssh_timeout']}",
                "-o", "ServerAliveInterval=15", "-o", "ControlMaster=auto",
                "-o", "ControlPath=~/.ssh/meshatlas-%C", "-o", "ControlPersist=10m"]
        return run_local(base + [target, remote_cmd], timeout=timeout, stdin=stdin)

    # ---------- discovery ----------
    def discover(self):
        """Rebuild the node list from ``tailscale status`` plus config overrides and external servers."""
        try:
            st = tailscale.status()
            err = None
        except Exception as exc:  # noqa: BLE001
            st, err = None, short(str(exc))
        if st is None:
            with self.lock:
                self.ts_meta["error"] = err
            self.emit("NODE", f"tailscale status failed: {err}", "error")
            return
        overrides = self.cfg["nodes"]
        disp = self.cfg["display"]
        hidden = set(disp["hide"]) | {k for k, v in overrides.items() if v.get("hidden")}
        max_age = disp.get("hide_offline_after_days") or 0
        locations = {k: {"name": v.get("name", k), "code": v.get("code", k.upper()), "lat": v["lat"], "lon": v["lon"]}
                     for k, v in self.cfg["locations"].items()}

        regions = self._derp_regions()

        def locate(key_or_derp):
            """Resolve a config location key or a DERP code into a location key (adding DERP locations lazily).
            Coordinates come from the live DERP map, then from the built-in table; custom regions have none."""
            if not key_or_derp:
                return None
            if key_or_derp in locations:
                return key_or_derp
            key = key_or_derp.lower()
            live = regions.get(key)
            reg = live if live and live[1] is not None else region(key)
            if not reg:
                return None
            locations.setdefault(key, {"name": reg[0], "code": key.upper(), "lat": reg[1], "lon": reg[2],
                                       "derp": True})
            return key

        me = st["self"]
        self.hub = me["id"]
        peers = {p["id"]: p for p in [me] + st["peers"]}
        nodes = {}
        for pid, p in peers.items():
            ov = overrides.get(pid, {})
            if pid in hidden:
                continue
            age = _iso_age_days(p["lastSeen"]) if not p["online"] else 0
            if max_age and age is not None and age > max_age and pid not in overrides:
                continue
            loc = locate(ov.get("location"))
            approx = False
            if not loc:
                loc, approx = locate(p["relay"]), True
            nodes[pid] = {
                "id": pid, "loc": loc, "approxLoc": approx and loc is not None, "self": p["self"],
                "where": ov.get("where") or (p["host"] if p["host"] != pid else ""),
                "role": ov.get("role") or ("This machine (hub)" if p["self"] else ", ".join(t.replace("tag:", "") for t in p["tags"])),
                "kind": ov.get("kind") or p["kind"], "os": p["os"], "tags": p["tags"],
                "notes": list(ov.get("notes") or []), "parent": ov.get("parent"),
                "tailscaleIp": p["ip"], "inTailnet": True,
                "ssh": ov.get("ssh"), "local": bool(p["self"] and self.col["collect_self"] and not ov.get("ssh")),
                "statsEvery": ov.get("statsEvery", 0), "external": False,
            }
        # the hub on a custom DERP region: use the nearest official region (by latency) as a rough location
        hub_node = nodes.get(self.hub)
        if hub_node and hub_node["loc"] is None:
            for code in self._nearest_codes():
                if locate(code):
                    hub_node["loc"], hub_node["approxLoc"] = locate(code), True
                    break
        # nodes with an unknown home region (custom DERP, no override) sit at the hub's location
        hub_loc = hub_node["loc"] if hub_node else None
        for n in nodes.values():
            if n["loc"] is None and hub_loc:
                n["loc"], n["approxLoc"] = hub_loc, True
        for ext in self.cfg["external"]:
            eid = ext["id"]
            if eid in hidden:
                continue
            nodes[eid] = {
                "id": eid, "loc": locate(ext.get("location")) or hub_loc, "approxLoc": not ext.get("location"),
                "self": False, "where": ext.get("where", ""), "role": ext.get("role", "External server"),
                "kind": ext.get("kind", "linux"), "os": "", "tags": [], "notes": list(ext.get("notes") or []),
                "parent": None, "tailscaleIp": None, "inTailnet": False, "ssh": ext.get("ssh"), "local": False,
                "statsEvery": ext.get("statsEvery", 0), "external": True, "address": ext["address"],
                "probeFrom": ext.get("probe_from") or ["hub"],
            }
        for n in nodes.values():
            n["collected"] = bool(n["ssh"] or n["local"])
        with self.lock:
            prev = self.ts_peers
            self.ts_peers = peers
            self.nodes = nodes
            self.locations = locations
            self.ts_meta = {"at": now(), "error": None, "tailnet": st["tailnet"]}
        if prev:
            for pid, p in peers.items():
                o = prev.get(pid)
                if o and o["online"] != p["online"] and pid in nodes:
                    self.emit("NODE", f"{pid} {'is back online' if p['online'] else 'went offline'}",
                              "ok" if p["online"] else "error", pid)
        else:
            online = sum(1 for n in nodes.values() if n["inTailnet"] and peers[n["id"]]["online"])
            self.emit("NODE", f"tailnet {st['tailnet'] or ''}: {len(nodes)} nodes, {online} online".replace("  ", " "), "info")

    def _derp_regions(self):
        """Live DERP map, refreshed every 6 h (also gives region-id -> code for netcheck)."""
        if now() - self._derp_at > 6 * 3600:
            self._derp_at = now()
            try:
                self._derp, self._derp_ids = tailscale.derp_map()
            except Exception:  # noqa: BLE001 - fall back to the built-in table
                pass
        return self._derp

    def _nearest_codes(self):
        if self._nearest is None or now() - self._nearest_at > 6 * 3600:
            self._nearest_at = now()
            try:
                self._nearest = tailscale.nearest_regions(self._derp_ids)
            except Exception:  # noqa: BLE001
                self._nearest = []
        return self._nearest

    # ---------- per-node collection (SSH or local) ----------
    def collect_node(self, node):
        nid = node["id"]
        t0 = now()
        args = []
        every = node.get("statsEvery") or 0
        if every and t0 - self.last_stats.get(nid, 0) < every:
            args = ["--no-stats"]
        try:
            if node["local"]:
                rc, so, se = run_local(["python3", "-"] + args, stdin=REMOTE_SCRIPT, timeout=120)
            else:
                rc, so, se = self.ssh(node["ssh"], "python3 -" + "".join(" " + a for a in args),
                                      stdin=REMOTE_SCRIPT, timeout=120)
            if rc != 0:
                raise RuntimeError(cmd_error(se, rc))
            data = json.loads(so.strip().splitlines()[-1])
            result = {"ok": True, "at": now(), "elapsed": round(now() - t0, 2), "data": data, "error": None}
            if (data.get("docker") or {}).get("stats"):
                self.last_stats[nid] = t0
        except Exception as exc:  # noqa: BLE001
            result = {"ok": False, "at": now(), "elapsed": round(now() - t0, 2), "data": None, "error": short(str(exc))}
        with self.lock:
            prev = self.results.get(nid)
            if result["ok"] and args and prev and prev.get("data"):
                old = {c["name"]: c for c in ((prev["data"].get("docker") or {}).get("containers") or [])}
                for c in (result["data"].get("docker") or {}).get("containers") or []:
                    o = old.get(c["name"])
                    if o and "cpu" in o and c.get("state") == "running":
                        c["cpu"], c["mem"], c["memPct"] = o.get("cpu"), o.get("mem"), o.get("memPct")
                        c["statsStale"] = True
            # a single failure (flaky link) keeps the previous data; two in a row count as a problem
            result["fails"] = 0 if result["ok"] else (prev or {}).get("fails", 0) + 1
            if not result["ok"] and prev and prev.get("data"):
                result["data"] = prev["data"]
                result["dataAt"] = prev.get("dataAt", prev.get("at"))
                result["stale"] = True
            elif result["ok"]:
                result["dataAt"] = result["at"]
            self.results[nid] = result
        self.diff_node(nid, prev, result)
        if result["ok"]:
            sysinfo = result["data"].get("sys") or {}
            mem = sysinfo.get("mem") or {}
            mem_pct = round(100.0 * mem["used"] / mem["total"], 1) if mem.get("total") else None
            with self.store.db() as c:
                c.execute("INSERT INTO metrics VALUES (?,?,?,?)", (now(), nid, sysinfo.get("cpu"), mem_pct))

    def diff_node(self, nid, prev, cur):
        def ctrs(r):
            return {c["name"]: c for c in (((r or {}).get("data") or {}).get("docker") or {}).get("containers") or []}

        def failed(r):
            return {u["unit"] for u in (((r or {}).get("data") or {}).get("services") or []) if u["active"] == "failed"}

        if prev is None:
            if cur["ok"]:
                d = cur["data"]
                cs = (d.get("docker") or {}).get("containers") or []
                parts = [f"{cur['elapsed']}s"]
                if d.get("docker") is not None:
                    parts.append(f"{sum(c['state'] == 'running' for c in cs)}/{len(cs)} containers running")
                if d.get("services"):
                    parts.append(f"{sum(u['sub'] == 'running' for u in d['services'])} services")
                self.emit("SYNC", f"{nid} first collection done · " + " · ".join(parts), "info", nid)
                if failed(cur):
                    self.emit("SVC", f"{nid} has {len(failed(cur))} failed unit(s): " + ", ".join(sorted(failed(cur))[:3]), "warn", nid)
            else:
                self.emit("SYNC", f"{nid} collection failed: {cur['error']}", "error", nid)
            return
        if not cur["ok"] and cur.get("fails") == 2:
            self.emit("SYNC", f"{nid} failed twice in a row: {cur['error']}", "error", nid)
        elif not cur["ok"] and cur.get("fails") == 1:
            self.emit("SYNC", f"{nid} skipped this round (keeping last data): {cur['error']}", "info", nid)
        elif cur["ok"] and prev.get("fails", 0) >= 2:
            self.emit("SYNC", f"{nid} collection recovered", "ok", nid)
        if not cur["ok"]:
            return
        before, after = ctrs(prev), ctrs(cur)
        changes = []
        for name, c in after.items():
            o = before.get(name)
            if o is None:
                changes.append((f"{nid}/{name} appeared ({c['state']})", "info"))
            elif o["state"] != c["state"]:
                changes.append((f"{nid}/{name} {o['state']} → {c['state']}", "ok" if c["state"] == "running" else "warn"))
            elif o.get("health") != c.get("health") and c.get("health") == "unhealthy":
                changes.append((f"{nid}/{name} became unhealthy", "warn"))
        for name in before.keys() - after.keys():
            changes.append((f"{nid}/{name} removed", "info"))
        for msg, lvl in changes[:8]:
            self.emit("CTR", msg, lvl, nid)
        if len(changes) > 8:
            self.emit("CTR", f"{nid}: {len(changes) - 8} more container changes", "info", nid)
        fb, fa = failed(prev), failed(cur)
        for unit in sorted(fa - fb):
            self.emit("SVC", f"{nid}/{unit} failed", "warn", nid)
        for unit in sorted(fb - fa):
            self.emit("SVC", f"{nid}/{unit} recovered", "ok", nid)

    # ---------- latency ----------
    def collect_latency(self):
        t0 = now()
        with self.lock:
            self.latency["running"] = True
            nodes = dict(self.nodes)
            peers = dict(self.ts_peers)
            hub = self.hub
        count = self.col["ping_count"]
        online = [n for n in nodes.values() if n["inTailnet"] and n["id"] != hub and peers.get(n["id"], {}).get("online")]
        edges, error = [], None

        def hub_ping(n):
            res = tailscale.ping(n["tailscaleIp"], count)
            return edge(hub, n["id"], res["times"], res["route"], res["derp"], "tailscale")

        jobs = {}
        pool = ThreadPoolExecutor(max_workers=12)
        for n in online:
            jobs[("hub", n["id"])] = pool.submit(hub_ping, n)
        # mesh: every reachable SSH node pings the others in one session
        groups = {}
        if self.col["mesh"]:
            for n in nodes.values():
                if n["ssh"] and n["inTailnet"] and peers.get(n["id"], {}).get("online"):
                    targets = [m for m in online + ([nodes[hub]] if hub in nodes else []) if m["id"] != n["id"]]
                    if targets:
                        groups[n["id"]] = ("mesh", targets)
        # ICMP for external servers, grouped by the node they are probed from
        for n in nodes.values():
            if not n["external"]:
                continue
            for src in n["probeFrom"]:
                src_id = hub if src == "hub" else src
                if src_id == hub or (src_id in nodes and nodes[src_id]["ssh"]):
                    groups.setdefault(f"icmp:{src_id}", ("icmp", []))[1].append(n)
        for key, (kind, targets) in groups.items():
            jobs[key] = pool.submit(self._group_probe, key, kind, targets, count)
        pool.shutdown(wait=True)
        for key, fut in jobs.items():
            try:
                got = fut.result()
                if isinstance(got, dict):
                    got = [got]
                if isinstance(key, str):
                    self.probe_fails[key] = 0
                    for e in got:
                        self.probe_last[(e["src"], e["dst"])] = e
                edges.extend(got)
            except Exception as exc:  # noqa: BLE001
                if isinstance(key, tuple):
                    error = (error + "; " if error else "") + f"ping {key[1]}: {short(str(exc), 80)}"
                    continue
                # debounce SSH groups: one failure reuses last round, two in a row are reported
                self.probe_fails[key] = self.probe_fails.get(key, 0) + 1
                src_id = key.split(":", 1)[1] if ":" in key else key
                if self.probe_fails[key] < 2:
                    edges.extend(dict(e, stale=True) for (s, _), e in self.probe_last.items() if s == src_id)
                else:
                    error = (error + "; " if error else "") + f"probes from {src_id}: {short(str(exc), 80)}"
        elapsed = round(now() - t0, 1)
        with self.lock:
            prev_edges = {(e["src"], e["dst"]): e for e in self.latency["edges"]}
            if edges:
                self.latency.update({"at": now(), "edges": edges, "elapsed": elapsed})
            self.latency["error"] = error
            self.latency["running"] = False
        if error:
            self.emit("PING", error, "error")
        if not edges:
            return
        ts = now()
        with self.store.db() as c:
            c.executemany("INSERT INTO latency VALUES (?,?,?,?,?)",
                          [(ts, e["src"], e["dst"], e["ms"], e["route"]) for e in edges
                           if e["ms"] is not None and not e.get("stale")])
        ok = [e for e in edges if e["ms"] is not None]
        hub_ms = [e["ms"] for e in ok if e["src"] == hub]
        self.emit("PING", f"{len(edges)} links · direct {sum(e['route'] == 'direct' for e in edges)} · relay "
                          f"{sum(e['route'] == 'relay' for e in edges)} · down {len(edges) - len(ok)}"
                          + (f" · {hub} P50 {statistics.median(hub_ms):.0f}ms" if hub_ms else "") + f" · {elapsed}s", "info")
        for e in edges:
            o = prev_edges.get((e["src"], e["dst"]))
            if not o or e["src"] != hub or e.get("stale"):
                continue
            if o["route"] != e["route"] and o["route"] and e["route"]:
                self.emit("LINK", f"{e['src']} → {e['dst']} route {o['route']} → {e['route']}", "warn", e["dst"])
            if (o["ms"] is None) != (e["ms"] is None):
                self.emit("LINK", f"{e['src']} → {e['dst']} {'recovered' if e['ms'] is not None else 'unreachable'}",
                          "ok" if e["ms"] is not None else "error", e["dst"])
            elif e["ms"] and o["ms"] and e["ms"] > max(o["ms"] * 2, o["ms"] + 60):
                self.emit("LINK", f"{e['src']} → {e['dst']} jumped to {e['ms']:.0f}ms (was {o['ms']:.0f}ms)", "warn", e["dst"])

    def _group_probe(self, key, kind, targets, count):
        with self.lock:
            hub = self.hub
            nodes = self.nodes
        src_id = key if kind == "mesh" else key.split(":", 1)[1]
        if kind == "mesh":
            ips = [t["tailscaleIp"] for t in targets]
            rc, so, se = self.ssh(nodes[src_id]["ssh"], "python3 - " + " ".join(shlex.quote(x) for x in [str(count)] + ips),
                                  stdin=tailscale.REMOTE_PING_SCRIPT.encode(), timeout=count * 5 + 60)
            if rc != 0:
                raise RuntimeError(cmd_error(se, rc))
            res = json.loads(so.strip().splitlines()[-1])
            if not res.get("ok"):
                raise RuntimeError("tailscale CLI not found on that node")
            out = []
            for t in targets:
                p = tailscale.parse_ping(res["raw"].get(t["tailscaleIp"], ""))
                out.append(edge(src_id, t["id"], p["times"], p["route"], p["derp"], "tailscale"))
            return out
        addrs = [t["address"] for t in targets]
        if src_id == hub:
            rc, so, se = run_local(["python3", "-"] + addrs, stdin=tailscale.ICMP_SCRIPT.encode(), timeout=60)
        else:
            rc, so, se = self.ssh(nodes[src_id]["ssh"], "python3 - " + " ".join(shlex.quote(a) for a in addrs),
                                  stdin=tailscale.ICMP_SCRIPT.encode(), timeout=60)
        if rc != 0:
            raise RuntimeError(cmd_error(se, rc))
        res = json.loads(so.strip().splitlines()[-1])
        return [edge(src_id, t["id"], res.get(t["address"]) or [], "icmp", None, "icmp") for t in targets]

    # ---------- Uptime Kuma (optional, public status page, no API key) ----------
    def collect_kuma(self):
        kc = self.cfg["kuma"]
        if not kc:
            return
        base = kc["url"].rstrip("/")
        try:
            with NO_PROXY.open(f"{base}/api/status-page/{kc['slug']}", timeout=20) as r:
                page = json.loads(r.read().decode())
            with NO_PROXY.open(f"{base}/api/status-page/heartbeat/{kc['slug']}", timeout=20) as r:
                beats = json.loads(r.read().decode())
            hb, up = beats.get("heartbeatList") or {}, beats.get("uptimeList") or {}
            with self.lock:
                ids = list(self.nodes)
            node_for = kc.get("map") or {}
            monitors = []
            for g in page.get("publicGroupList") or []:
                for m in g.get("monitorList") or []:
                    last = (hb.get(str(m["id"])) or [None])[-1] or {}
                    name = m.get("name") or ""
                    owner = node_for.get(name) or next((i for i in ids if i in name), None) or self.hub
                    monitors.append({
                        "id": m["id"], "name": name, "group": g.get("name"), "type": m.get("type"),
                        "status": KUMA_STATUS.get(last.get("status"), "unknown"), "ping": last.get("ping"),
                        "time": last.get("time"), "msg": short(last.get("msg") or "", 140),
                        "uptime24": up.get(f"{m['id']}_24"), "node": owner,
                    })
            with self.lock:
                prev = {m["id"]: m for m in self.kuma["monitors"]}
                self.kuma = {"at": now(), "monitors": monitors, "error": None, "url": f"{base}/status/{kc['slug']}"}
            if not prev:
                down = [m["name"] for m in monitors if m["status"] == "down"]
                self.emit("KUMA", f"{len(monitors)} monitors · down {len(down)}" + (": " + ", ".join(down[:3]) if down else ""),
                          "warn" if down else "info")
            for m in monitors:
                o = prev.get(m["id"])
                if o and o["status"] != m["status"] and m["status"] in ("up", "down"):
                    self.emit("KUMA", f"{m['name']} {o['status']} → {m['status']}", "ok" if m["status"] == "up" else "warn", m["node"])
        except Exception as exc:  # noqa: BLE001
            with self.lock:
                self.kuma["error"] = short(str(exc))
            self.emit("KUMA", f"reading the Kuma status page failed: {short(str(exc))}", "error")

    # ---------- status history ----------
    def node_online(self, n):
        if n["inTailnet"]:
            p = self.ts_peers.get(n["id"])
            return None if p is None else int(bool(p["online"]))
        if n["collected"]:
            r = self.results.get(n["id"])
            return None if not r else int(bool(r.get("ok")) or r.get("fails", 0) < 2)
        pings = [e for e in self.latency["edges"] if e.get("route") == "icmp" and e["dst"] == n["id"]]
        return int(any(e["ms"] is not None for e in pings)) if pings else None

    def record_status(self):
        ts = now()
        with self.lock:
            rows = [(ts, n["id"], self.node_online(n)) for n in self.nodes.values()]
        rows = [r for r in rows if r[2] is not None]
        if rows:
            with self.store.db() as c:
                c.executemany("INSERT INTO status VALUES (?,?,?)", rows)

    # ---------- loops ----------
    def node_round(self):
        self.discover()
        self.collect_kuma()
        with self.lock:
            targets = [n for n in self.nodes.values() if n["collected"]]
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(self.collect_node, targets))
        self.record_status()

    def latency_round(self):
        if self.hub:
            self.collect_latency()
        self.store.prune()

    def loop(self, fn, every, name):
        while True:
            t0 = now()
            try:
                fn()
            except Exception:  # noqa: BLE001
                self.emit("SYS", f"{name} crashed: {short(traceback.format_exc(limit=1))}", "error")
            time.sleep(max(5, every - (now() - t0)))

    def start(self):
        self.emit("SYS", f"collector started · nodes every {self.col['interval']}s · latency every "
                         f"{self.col['latency_interval']}s", "info")
        self.discover()   # so the first page load already has a node list
        threading.Thread(target=self.loop, args=(self.node_round, self.col["interval"], "node round"), daemon=True).start()
        threading.Thread(target=self.loop, args=(self.latency_round, self.col["latency_interval"], "latency round"),
                         daemon=True).start()

    # ---------- API payloads ----------
    def public_config(self):
        nodes = [dict({k: n[k] for k in PUBLIC_NODE_KEYS if k in n},
                      inTailnet=n["inTailnet"], collected=n["collected"]) for n in self.nodes.values()]
        nodes.sort(key=lambda n: (not n.get("self"), n.get("external", False), n["id"]))
        locs = {}
        for k, v in self.locations.items():
            if any(n["loc"] == k for n in self.nodes.values()):
                locs[k] = {"name": v["name"], "code": v["code"], "lat": v["lat"], "lon": v["lon"],
                           "approx": bool(v.get("derp"))}
        disp = self.cfg["display"]
        return {"title": disp["title"], "subtitle": disp["subtitle"], "hub": self.hub, "locations": locs, "nodes": nodes,
                "tailnet": self.ts_meta.get("tailnet", ""),
                "intervals": {"node": self.col["interval"], "latency": self.col["latency_interval"]}}

    def spark_for_hub(self, points=40):
        out = {}
        with self.store.db() as c:
            rows = c.execute("SELECT dst, ts, ms FROM latency WHERE src=? AND ts>? ORDER BY ts",
                             (self.hub, now() - 6 * 3600)).fetchall()
        for dst, ts, ms in rows:
            out.setdefault(dst, []).append([round(ts), ms])
        return {k: v[-points:] for k, v in out.items()}

    def api_state(self):
        with self.lock:
            nodes = {}
            for nid in self.nodes:
                r = self.results.get(nid) or {}
                data = r.get("data") or {}
                p = self.ts_peers.get(nid)
                nodes[nid] = {
                    "collect": {k: r.get(k) for k in ("ok", "at", "elapsed", "error", "stale", "fails", "dataAt")} if r else None,
                    "tailscale": {"online": p["online"], "lastSeen": p["lastSeen"], "relay": p["relay"],
                                  "self": p["self"], "active": p["active"], "os": p["os"]} if p else None,
                    "sys": data.get("sys"), "docker": data.get("docker"), "services": data.get("services"),
                    "kuma": [m for m in self.kuma["monitors"] if m["node"] == nid],
                }
            payload = {
                "now": now(), "startedAt": self.started, "config": self.public_config(), "nodes": nodes,
                "extraNodes": [],
                "tailscale": {"at": self.ts_meta["at"], "error": self.ts_meta["error"]},
                "latency": {k: self.latency[k] for k in ("at", "edges", "error", "elapsed", "running")},
                "kuma": {k: self.kuma[k] for k in ("at", "error", "url")},
                "events": list(self.events)[-150:],
            }
        payload["spark"] = self.spark_for_hub() if self.hub else {}
        return payload

    def api_history(self, node, hours):
        since = now() - hours * 3600
        bucket = max(120, int(hours * 3600 / 240))
        with self.store.db() as c:
            out_rows = c.execute("SELECT dst, ts, ms FROM latency WHERE src=? AND ts>?", (node, since)).fetchall()
            in_rows = c.execute("SELECT src, ts, ms FROM latency WHERE dst=? AND ts>?", (node, since)).fetchall()
            m_rows = c.execute("SELECT ts, cpu, mem FROM metrics WHERE node=? AND ts>? ORDER BY ts", (node, since)).fetchall()
            s_rows = c.execute("SELECT ts, online FROM status WHERE node=? AND ts>?", (node, since)).fetchall()
        latency = bucketize(out_rows, bucket)
        for k, v in bucketize(in_rows, bucket).items():   # nodes that never ping use what others measured to them
            latency.setdefault(k, v)
        return {"node": node, "hours": hours, "bucket": bucket, "latency": latency,
                "cpu": bucketize([("c", ts, v) for ts, v, _ in m_rows], bucket).get("c", []),
                "mem": bucketize([("m", ts, v) for ts, _, v in m_rows], bucket).get("m", []),
                "status": bucketize([("s", ts, v) for ts, v in s_rows], bucket).get("s", [])}

    def api_uptime(self, hours, nb):
        since = now() - hours * 3600
        size = hours * 3600 / nb
        with self.store.db() as c:
            rows = c.execute("SELECT node, ts, online FROM status WHERE ts>?", (since,)).fetchall()
        agg = {}
        for node, ts, on in rows:
            a = agg.setdefault(node, {"n": 0, "up": 0, "b": {}})
            a["n"] += 1
            a["up"] += on
            b = a["b"].setdefault(min(nb - 1, int((ts - since) // size)), [0, 0])
            b[0] += 1
            b[1] += on
        first = min((ts for _, ts, _ in rows), default=None)
        return {"hours": hours, "buckets": nb, "since": since, "size": size, "first": first,
                "nodes": {node: {"pct": round(100.0 * a["up"] / a["n"], 2), "samples": a["n"],
                                 "strip": [round(a["b"][i][1] / a["b"][i][0], 3) if i in a["b"] else None for i in range(nb)]}
                          for node, a in agg.items()}}

    def api_events(self, node, levels, limit, before):
        sql, args = "SELECT id, ts, kind, level, msg, node FROM events WHERE 1=1", []
        if node:
            sql += " AND node=?"
            args.append(node)
        if levels:
            sql += f" AND level IN ({','.join('?' * len(levels))})"
            args += levels
        if before:
            sql += " AND id<?"
            args.append(before)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        with self.store.db() as c:
            rows = c.execute(sql, args).fetchall()
        return {"events": [dict(zip(("id", "ts", "kind", "level", "msg", "node"), r)) for r in rows]}


def edge(src, dst, times, route, derp, via):
    ok = bool(times)
    return {"src": src, "dst": dst, "ms": round(sum(times) / len(times), 1) if ok else None,
            "min": min(times) if ok else None, "max": max(times) if ok else None,
            "state": "ok" if ok else "unreachable", "route": route if ok or via == "icmp" else None,
            "derp": derp, "via": via}


def run_local(cmd, timeout=30, stdin=None):
    r = subprocess.run(cmd, input=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")


def cmd_error(stderr, rc):
    lines = [ln for ln in (stderr or "").splitlines() if ln.strip() and not ln.startswith("Warning: Permanently added")]
    return short(lines[-1] if lines else f"exit {rc}")
