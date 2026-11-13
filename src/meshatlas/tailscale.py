"""Thin wrapper around the ``tailscale`` CLI. Only read-only commands are used: ``status --json`` and ``ping``."""

import json
import os
import re
import shutil
import subprocess

MAC_APP_CLI = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"

KIND = {"linux": "linux", "macos": "mac", "darwin": "mac", "windows": "windows", "ios": "ios", "android": "android",
        "freebsd": "linux", "openbsd": "linux", "tvos": "ios", "illumos": "linux"}

# "pong from <host> (<ip>) via <DERP(xxx) | ip:port | peer-relay(...)> in 12ms" — host names may contain spaces
PONG_RE = re.compile(r"pong from .+? \(([0-9a-fA-F.:]+)\) via (.+?) in ([\d.]+)ms")


def cli_path():
    env = os.environ.get("MESHATLAS_TAILSCALE")
    if env:
        return env
    found = shutil.which("tailscale")
    if found:
        return found
    if os.path.exists(MAC_APP_CLI):
        return MAC_APP_CLI
    return None


def run(args, timeout=20):
    exe = cli_path()
    if not exe:
        raise RuntimeError("tailscale CLI not found: install Tailscale or set MESHATLAS_TAILSCALE")
    r = subprocess.run([exe, *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
                       universal_newlines=True)
    return r.returncode, r.stdout, r.stderr


def node_id(p):
    """Stable, URL-safe id: the MagicDNS label (``name`` in ``name.tailnet.ts.net``), else a slug of the host name."""
    dns = (p.get("DNSName") or "").rstrip(".")
    if dns:
        return dns.split(".")[0]
    host = (p.get("HostName") or "node").lower()
    return re.sub(r"[^a-z0-9-]+", "-", host).strip("-") or "node"


def _peer(p, is_self):
    ips = p.get("TailscaleIPs") or []
    ip4 = next((ip for ip in ips if "." in ip), ips[0] if ips else None)
    last = p.get("LastSeen")
    if last and last.startswith("0001-"):
        last = None
    os_name = p.get("OS") or ""
    return {
        "id": node_id(p),
        "host": p.get("HostName") or "",
        "dns": (p.get("DNSName") or "").rstrip("."),
        "ip": ip4,
        "os": os_name,
        "kind": KIND.get(os_name.lower(), "linux" if not os_name else os_name.lower()),
        "online": True if is_self else bool(p.get("Online")),
        "lastSeen": last,
        "relay": (p.get("Relay") or "").lower(),
        "tags": p.get("Tags") or [],
        "self": is_self,
        "active": bool(p.get("Active")),
        "exitNode": bool(p.get("ExitNode")),
        "peerRelay": p.get("PeerRelay") or "",
    }


def parse_status(data):
    """Turn ``tailscale status --json`` into {"self": node, "peers": [node, ...], "tailnet": name}."""
    me = _peer(data.get("Self") or {}, True)
    peers = [_peer(p, False) for p in (data.get("Peer") or {}).values()]
    # MagicDNS labels are unique inside a tailnet, but make sure anyway
    seen = {me["id"]}
    for p in peers:
        base, n = p["id"], 2
        while p["id"] in seen:
            p["id"] = f"{base}-{n}"
            n += 1
        seen.add(p["id"])
    tailnet = (data.get("CurrentTailnet") or {}).get("Name") or data.get("MagicDNSSuffix") or ""
    return {"self": me, "peers": peers, "tailnet": tailnet}


def status():
    rc, out, err = run(["status", "--json"], timeout=20)
    if rc != 0:
        raise RuntimeError((err or out).strip()[:200] or f"tailscale status exited {rc}")
    return parse_status(json.loads(out))


def derp_map():
    """{region code: (name, lat or None, lon or None)} from ``tailscale debug derp-map`` (works without root).

    Official regions carry coordinates; custom (self-hosted) regions usually do not."""
    rc, out, err = run(["debug", "derp-map"], timeout=20)
    if rc != 0:
        raise RuntimeError((err or out).strip()[:200] or f"derp-map exited {rc}")
    regions = {}
    ids = {}
    for rid, r in (json.loads(out).get("Regions") or {}).items():
        code = (r.get("RegionCode") or "").lower()
        if not code:
            continue
        regions[code] = (r.get("RegionName") or code.upper(), r.get("Latitude"), r.get("Longitude"))
        ids[str(r.get("RegionID", rid))] = code
    return regions, ids


def nearest_regions(ids):
    """Region codes sorted by latency from this machine (``tailscale netcheck``), nearest first."""
    rc, out, err = run(["netcheck", "--format=json"], timeout=45)
    if rc != 0:
        raise RuntimeError((err or out).strip()[:200] or f"netcheck exited {rc}")
    lat = json.loads(out).get("RegionLatency") or {}
    return [ids[k] for k, _ in sorted(lat.items(), key=lambda kv: kv[1]) if k in ids]


def parse_ping(text):
    """Parse ``tailscale ping`` output -> {"times": [ms, ...], "route": direct|relay|None, "derp": label|None}."""
    times, via = [], None
    for m in PONG_RE.finditer(text or ""):
        times.append(float(m.group(3)))
        via = m.group(2).strip()
    route = derp = None
    if via:
        if via.upper().startswith("DERP("):
            route, derp = "relay", via
        elif "relay" in via.lower():
            route, derp = "relay", "peer relay"
        else:
            route = "direct"
    return {"times": times, "route": route, "derp": derp}


def ping_args(ip, count=3, timeout_s=3):
    return ["ping", "--c", str(count), "--until-direct=false", "--timeout", f"{timeout_s}s", ip]


def ping(ip, count=3, timeout_s=3):
    rc, out, err = run(ping_args(ip, count, timeout_s), timeout=count * (timeout_s + 1) + 5)
    return parse_ping(out + "\n" + err)


# Runs on SSH nodes (fed through stdin, nothing is written to disk) to measure latency from that node to the others.
# Must stay compatible with Python 3.8 and use only the standard library.
REMOTE_PING_SCRIPT = r'''
import json, os, re, shutil, subprocess, sys, threading
PONG = re.compile(r"pong from .+? \(([0-9a-fA-F.:]+)\) via (.+?) in ([\d.]+)ms")
exe = shutil.which("tailscale") or ("/Applications/Tailscale.app/Contents/MacOS/Tailscale"
      if os.path.exists("/Applications/Tailscale.app/Contents/MacOS/Tailscale") else None)
count = int(sys.argv[1]); targets = sys.argv[2:]; out = {}
def one(ip):
    try:
        r = subprocess.run([exe, "ping", "--c", str(count), "--until-direct=false", "--timeout", "3s", ip],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True,
                           timeout=count * 4 + 5)
        text = r.stdout
    except Exception as exc:
        text = str(exc)
    out[ip] = text
if exe:
    ts = [threading.Thread(target=one, args=(ip,)) for ip in targets]
    [t.start() for t in ts]; [t.join() for t in ts]
print(json.dumps({"ok": bool(exe), "raw": out}))
'''

# Plain ICMP ping, for servers outside the tailnet ("external" nodes in the config).
ICMP_SCRIPT = r'''
import json, re, subprocess, sys
out = {}
wait = "2000" if sys.platform == "darwin" else "2"   # -W is milliseconds on macOS, seconds on Linux
for target in sys.argv[1:]:
    r = subprocess.run(["ping", "-c", "3", "-W", wait, "-i", "0.3", target], stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, universal_newlines=True)
    out[target] = [float(x) for x in re.findall(r"time=([0-9.]+)", r.stdout)]
print(json.dumps(out))
'''
