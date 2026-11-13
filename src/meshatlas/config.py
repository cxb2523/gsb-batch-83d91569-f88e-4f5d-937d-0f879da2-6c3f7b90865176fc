"""Configuration: every key is optional. Without a config file MeshAtlas discovers the tailnet by itself."""

import copy
import json
import os
from pathlib import Path

try:  # Python 3.11+
    import tomllib
except ImportError:  # pragma: no cover - older Pythons get the tomli backport (installed automatically)
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None

DEFAULTS = {
    "server": {
        "host": "auto",          # auto = this machine's Tailscale IPv4, falling back to 127.0.0.1
        "port": 8765,
        "token": "",             # optional shared secret (?token=... once, then a cookie)
    },
    "collect": {
        "interval": 120,         # seconds between node rounds (tailscale status + SSH collection)
        "latency_interval": 120, # seconds between latency rounds
        "ping_count": 3,
        "mesh": True,            # nodes with SSH also ping every other node -> full latency matrix
        "collect_self": True,    # read docker / systemd / system stats on the machine running MeshAtlas
        "ssh_timeout": 30,
        "keep_days": 7,
    },
    "display": {
        "title": "MESHATLAS",
        "subtitle": "TAILNET OPS",
        "hide_offline_after_days": 30,
        "hide": [],
    },
    "locations": {},             # key -> {name, code, lat, lon}
    "nodes": {},                 # node id -> overrides {location, role, where, notes, ssh, statsEvery, hidden, parent}
    "external": [],              # servers outside the tailnet, watched with ICMP ping
    "kuma": {},                  # optional Uptime Kuma status page {url, slug}
}

SEARCH_PATHS = [
    "meshatlas.toml",
    "meshatlas.json",
    "~/.config/meshatlas/meshatlas.toml",
    "~/.config/meshatlas/meshatlas.json",
    "/etc/meshatlas/meshatlas.toml",
]


class ConfigError(Exception):
    pass


def _merge(base, extra):
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict) and k not in ("locations", "nodes"):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def find_config(explicit=None):
    if explicit:
        p = Path(explicit).expanduser()
        if not p.exists():
            raise ConfigError(f"config file not found: {p}")
        return p
    env = os.environ.get("MESHATLAS_CONFIG")
    if env:
        return find_config(env)
    for cand in SEARCH_PATHS:
        p = Path(cand).expanduser()
        if p.exists():
            return p
    return None


def parse_file(path):
    text = Path(path).read_text(encoding="utf-8")
    if str(path).endswith(".toml"):
        if tomllib is None:
            raise ConfigError("reading TOML on Python < 3.11 needs the tomli package (pip install tomli), or use a .json config")
        try:
            return tomllib.loads(text)
        except Exception as exc:
            raise ConfigError(f"{path}: {exc}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from exc


def validate(cfg):
    for key, loc in cfg["locations"].items():
        for f in ("lat", "lon"):
            if not isinstance(loc.get(f), (int, float)):
                raise ConfigError(f"[locations.{key}] needs numeric lat and lon")
    for i, ext in enumerate(cfg["external"]):
        if not ext.get("id") or not ext.get("address"):
            raise ConfigError(f"[[external]] #{i + 1} needs id and address")
    kuma = cfg["kuma"]
    if kuma and (not kuma.get("url") or not kuma.get("slug")):
        raise ConfigError("[kuma] needs both url and slug")
    return cfg


def load(path=None):
    """Return (config dict, path or None)."""
    found = find_config(path)
    raw = parse_file(found) if found else {}
    unknown = set(raw) - set(DEFAULTS)
    if unknown:
        raise ConfigError(f"unknown top-level section(s): {', '.join(sorted(unknown))}")
    return validate(_merge(DEFAULTS, raw)), found
