#!/usr/bin/env python3
"""Configure independent subscription providers and native automatic failover.

Default: prepare and validate a candidate. --apply also reloads and verifies it.
URLs are read from the environment/.env, never passed on the command line.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import copy
import fcntl
import hashlib
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml

from merge_subscription import normalize_short_ids

ROOT = Path(__file__).resolve().parent.parent
CHECK_URL = "https://www.gstatic.com/generate_204"
HEALTH_TIMEOUT_MS = 20000
LATENCY_TOLERANCE_MS = 30
FULL_CHECK_INTERVAL = 900
EXIT_CHECK_INTERVAL = 120
MAX_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True)
class Source:
    name: str
    url: str


def settings(env_file: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and not key.startswith("#"):
                values[key.strip()] = value.strip().strip("\"'")
    values.update(os.environ)
    return values


def sources_from(values: dict[str, str]) -> list[Source]:
    result = [Source("primary", values.get("MIHOMO_SUBSCRIPTION_URL", ""))]
    keys = [k for k in values if re.fullmatch(r"MIHOMO_BACKUP_SUBSCRIPTION_URL(?:_(?:[2-9]|[1-9][0-9]+))?", k)]
    keys.sort(key=lambda k: int(k.rsplit("_", 1)[-1]) if k.rsplit("_", 1)[-1].isdigit() else 1)
    for key in keys:
        if values[key]:
            suffix = key.rsplit("_", 1)[-1]
            result.append(Source("backup" + (suffix if suffix.isdigit() else "1"), values[key]))
    if len(result) < 2 or not result[0].url:
        raise ValueError("configure a primary and at least one backup subscription")
    if len({s.url for s in result}) != len(result):
        raise ValueError("subscription URLs must be different")
    if any(not s.url.startswith(("https://", "http://")) for s in result):
        raise ValueError("subscriptions must be HTTP(S) Clash/Mihomo YAML URLs")
    return result


def provider_payload(body: bytes) -> dict[str, Any]:
    if len(body) > MAX_BYTES:
        raise ValueError("subscription exceeds size limit")
    try:
        data = yaml.safe_load(body)
    except yaml.YAMLError:
        raise ValueError("subscription is not valid YAML") from None
    nodes = data.get("proxies") if isinstance(data, dict) else None
    if not isinstance(nodes, list) or not nodes:
        raise ValueError("subscription contains no proxies")
    names: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get("name"), str) or not node["name"]:
            raise ValueError("subscription contains an unnamed proxy")
        if node["name"] in names:
            raise ValueError("duplicate proxy names within one source")
        names.add(node["name"])
        if node.get("dialer-proxy") not in (None, "DIRECT"):
            raise ValueError("subscription proxy dependencies require explicit migration")
    try:
        normalize_short_ids(nodes)
    except ValueError:
        raise ValueError("subscription contains an invalid REALITY short-id") from None
    payload = {"proxies": nodes}
    # Native providers ignore subscription DNS. Retain only node-resolution
    # metadata so the compiler can scope it to this source's server hostnames.
    dns = data.get('dns')
    if isinstance(dns, dict):
        node_dns = {k: copy.deepcopy(dns[k]) for k in
                    ('proxy-server-nameserver', 'proxy-server-nameserver-policy') if k in dns}
        if node_dns:
            payload['dns'] = node_dns
    return payload


def download(source: Source, proxy_url: str) -> dict[str, Any]:
    # Direct first: recovering/updating subscriptions must not require a working proxy.
    for proxies in ({}, {"http": proxy_url, "https": proxy_url}):
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler(proxies))
            req = urllib.request.Request(source.url, headers={"User-Agent": "clash.meta"})
            with opener.open(req, timeout=15) as response:
                body = response.read(MAX_BYTES + 1)
            return provider_payload(body)
        except Exception:
            # urllib/YAML exceptions may contain credentials; never log them.
            continue
    raise ValueError(f"{source.name}: download/parse failed")


def cached_payload(base: dict[str, Any], data_dir: Path, source: Source) -> dict[str, Any] | None:
    provider = (base.get("proxy-providers") or {}).get("managed-" + source.name, {})
    if provider.get("url") == source.url and provider.get("path"):
        path = (data_dir / provider["path"]).resolve()
        if path.is_relative_to(data_dir.resolve()) and path.is_file():
            return provider_payload(path.read_bytes())
    # Unattributed inline nodes belong only to rescue, never to an unverified URL.
    return None


def write_private(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        os.fchmod(stream.fileno(), 0o600)
        yaml.safe_dump(value, stream, allow_unicode=True, sort_keys=False, width=4096)


def rescue_payload(base: dict[str, Any], data_dir: Path) -> dict[str, Any] | None:
    """Retain currently working inline nodes when moving to managed subscriptions."""
    if base.get("proxies"):
        return provider_payload(yaml.safe_dump({"proxies": base["proxies"], 'dns': base.get('dns', {})}).encode())
    provider = base.get("proxy-providers", {}).get("managed-rescue", {})
    if provider.get("path"):
        path = (data_dir / provider["path"]).resolve()
        if path.is_relative_to(data_dir.resolve()) and path.is_file():
            payload = provider_payload(path.read_bytes())
            if not payload.get('dns'):
                original_dns = base.get('dns', {})
                original = original_dns.get('proxy-server-nameserver')
                policies = original_dns.get('proxy-server-nameserver-policy') or {}
                retained = {str(n.get('server', '')).lower().rstrip('.'): copy.deepcopy(policies[str(n.get('server', '')).lower().rstrip('.')])
                            for n in payload['proxies'] if str(n.get('server', '')).lower().rstrip('.') in policies}
                if original or retained:
                    payload['dns'] = {'proxy-server-nameserver': copy.deepcopy(original or []),
                                      'proxy-server-nameserver-policy': retained}
            return payload
    return None


def overlapping_nodes(payloads: list[dict[str, Any]]) -> int:
    identities = []
    for payload in payloads:
        identities.append({hashlib.sha256(json.dumps({k: v for k, v in node.items() if k != "name"},
                                                     sort_keys=True).encode()).hexdigest()
                           for node in payload["proxies"]})
    return len(set.intersection(*identities)) if len(identities) > 1 else 0


def configure_node_dns(config: dict[str, Any], payloads: list[dict[str, Any]],
                       rescue: dict[str, Any] | None = None) -> int:
    """Keep each source's node resolver on its own exact server hostnames.

    A provider-private DoH often returns no answers for other providers. Using it
    globally silently makes otherwise working nodes unreachable. Application DNS,
    routes, listeners and ports are deliberately left alone.
    """
    dns = config.setdefault('dns', {})
    if not dns.get('enable'):
        return 0
    general = []
    for item in dns.get('default-nameserver') or []:
        try:
            ipaddress.ip_address(item)
            general.append(item)
        except ValueError:
            continue
    general = general or ['223.5.5.5', '119.29.29.29']
    policies = copy.deepcopy(dns.get('proxy-server-nameserver-policy') or {})
    owners: dict[str, list[str]] = {}

    def add(payload, is_rescue=False):
        source_dns = payload.get('dns') or {}
        resolvers = source_dns.get('proxy-server-nameserver') or general
        if not isinstance(resolvers, list) or not all(isinstance(v, str) and v for v in resolvers):
            raise ValueError('invalid source node DNS resolver list')
        source_policy = source_dns.get('proxy-server-nameserver-policy') or {}
        for node in payload['proxies']:
            host = str(node.get('server') or '').lower().rstrip('.')
            if not host:
                continue
            try:
                ipaddress.ip_address(host)
                continue
            except ValueError:
                pass
            chosen = source_policy.get(host, resolvers)
            if isinstance(chosen, str):
                chosen = [chosen]
            if not isinstance(chosen, list) or not all(isinstance(v, str) and v for v in chosen):
                raise ValueError('invalid source node DNS policy')
            if not is_rescue and host in owners and owners[host] != chosen:
                raise ValueError('sources require conflicting DNS policies for the same node hostname')
            if not is_rescue:
                owners[host] = chosen
            policies[host] = copy.deepcopy(chosen)

    # Explicit current subscriptions take precedence over legacy rescue metadata.
    if rescue:
        add(rescue, is_rescue=True)
    for payload in payloads:
        add(payload)
    dns['proxy-server-nameserver'] = general
    dns['proxy-server-nameserver-policy'] = policies
    return len(policies)


def configure_auto_policy(config: dict[str, Any]) -> None:
    """Prioritize subscriptions, then optimize latency inside each subscription."""
    providers = list(config['proxy-providers'])
    common = {"url": CHECK_URL, "interval": FULL_CHECK_INTERVAL, "timeout": HEALTH_TIMEOUT_MS,
              "lazy": False, "expected-status": 204, "max-failed-times": 2,
              "interrupt-existing-connections": False}
    pools = [{"name": '优选-' + provider.removeprefix('managed-'), "type": "url-test",
              "use": [provider], **copy.deepcopy(common), "tolerance": LATENCY_TOLERANCE_MS}
             for provider in providers]
    config.setdefault('profile', {})['store-selected'] = True
    config['proxy-groups'] = [
        {"name": "XFLTD", "type": "select", "proxies": ["自动故障转移", "手动节点"],
         "interrupt-existing-connections": False},
        {"name": "自动故障转移", "type": "fallback", "proxies": [p['name'] for p in pools],
         **copy.deepcopy(common), "interval": EXIT_CHECK_INTERVAL},
        {"name": "手动节点", "type": "select", "use": providers,
         "interrupt-existing-connections": False},
        # Preserve existing rule targets with the same combined automatic policy.
        *[{"name": alias, "type": "select", "proxies": ["自动故障转移"],
           "interrupt-existing-connections": False} for alias in ('故障转移', '自动选择')],
        *pools,
    ]


def build_config(base: dict[str, Any], sources: list[Source], revision: str) -> dict[str, Any]:
    if base.get("mode", "rule") != "rule":
        raise ValueError("automatic failover requires rule mode")
    supported = {"DIRECT", "REJECT", "REJECT-DROP", "PASS", "XFLTD", "自动选择", "故障转移"}
    for rule in base.get("rules", []):
        fields = str(rule).split(",")
        target = fields[-2] if fields[-1] == "no-resolve" else fields[-1]
        if target not in supported:
            raise ValueError("custom routing targets require explicit migration")
    if any(not key.startswith("managed-") for key in base.get("proxy-providers", {})):
        raise ValueError("existing custom providers require explicit migration")
    config = copy.deepcopy(base)
    config["proxies"] = []
    providers = {}
    for source in sources:
        providers["managed-" + source.name] = {
            "type": "http", "url": source.url,
            "path": f"./managed-providers/{revision}/{source.name}.yaml",
            "interval": 3600, "proxy": "DIRECT", "size-limit": MAX_BYTES,
            "header": {"User-Agent": ["clash.meta"]},
            "override": {"additional-prefix": f"[{source.name}] "},
            "health-check": {
                "enable": True, "url": CHECK_URL, "interval": FULL_CHECK_INTERVAL,
                "timeout": HEALTH_TIMEOUT_MS, "lazy": False, "expected-status": 204,
            },
        }
    if base.get("proxies") or "managed-rescue" in base.get("proxy-providers", {}):
        providers["managed-rescue"] = {
            "type": "file", "path": f"./managed-providers/{revision}/rescue.yaml",
            "override": {"additional-prefix": "[rescue] "},
            "health-check": {"enable": True, "url": CHECK_URL, "interval": FULL_CHECK_INTERVAL,
                             "timeout": HEALTH_TIMEOUT_MS, "lazy": False, "expected-status": 204},
        }
    config["proxy-providers"] = providers
    configure_auto_policy(config)
    return config


def api(base_url: str, secret: str, path: str, payload: dict | None = None) -> dict:
    request = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Authorization": "Bearer " + secret, "Content-Type": "application/json"},
        method="PUT" if payload is not None else "GET",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=10) as response:
        return json.loads(response.read() or "{}")


def verify(base_url: str, secret: str, proxy_url: str, provider_names: list[str]) -> bool:
    try:
        providers = api(base_url, secret, "/providers/proxies").get("providers", {})
        if any(not providers.get(name, {}).get("proxies") for name in provider_names):
            print('Verification: a subscription has not loaded its cached nodes.')
            return False
        groups = api(base_url, secret, "/proxies").get("proxies", {})
        root = groups.get("XFLTD", {})
        if root.get("type") != "Selector" or groups.get("自动故障转移", {}).get("type") != "Fallback":
            print('Verification: automatic selector groups are not ready.')
            return False
        if root.get("now") not in {"自动故障转移", "手动节点"}:
            print('Verification: root selector is not using an approved mode.')
            return False
        for url in [CHECK_URL, "https://www.youtube.com/generate_204"]:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({"https": proxy_url}))
            with opener.open(url, timeout=25) as response:
                if response.status != 204:
                    print('Verification: HTTPS check returned status', response.status)
                    return False
        return True
    except Exception as exc:
        # Never log exception text: HTTP errors may embed subscription secrets.
        print('Verification: controller/HTTPS request failed:', type(exc).__name__)
        return False


def validate_mount(data_dir: Path) -> None:
    """Never validate one directory in Docker and publish a different host directory."""
    result = subprocess.run(["docker", "compose", "-f", str(ROOT / "docker-compose.yml"),
                             "ps", "-q", "mihomo"], capture_output=True, text=True, check=True, timeout=15)
    container = result.stdout.strip()
    if not container:
        raise ValueError("Mihomo container is not running")
    result = subprocess.run(["docker", "inspect", "--format", "{{json .Mounts}}", container],
                            capture_output=True, text=True, check=True, timeout=15)
    mounted = next((m.get("Source") for m in json.loads(result.stdout)
                    if m.get("Destination") == "/root/.config/mihomo" and m.get("Type") == "bind"), None)
    if not mounted or Path(mounted).resolve() != data_dir.resolve():
        raise ValueError("data directory does not match the running container mount")


def apply_candidate(data_dir: Path, candidate: Path, controller: str, secret: str, proxy: str,
                    provider_names: list[str]) -> None:
    current = data_dir / "config.yaml"
    backup = data_dir / ("config.yaml.backup." + time.strftime("%Y%m%d-%H%M%S") + "." + uuid.uuid4().hex[:6])
    shutil.copy2(current, backup)
    os.chmod(backup, 0o600)
    before = api(controller, secret, '/proxies').get('proxies', {})
    before_root = before.get('XFLTD', {}).get('now')
    before_manual = before.get('手动节点', {}).get('now')
    leaf = 'XFLTD'
    seen = set()
    while leaf in before and before[leaf].get('now') and leaf not in seen:
        seen.add(leaf)
        leaf = before[leaf]['now']

    def select(group, node):
        api(controller, secret, '/proxies/' + quote(group, safe=''), {'name': node})

    def restore_selection():
        # Restore auto before resetting its inactive manual selector, so an old
        # failed manual selection never replaces the temporary working backup.
        if before_root in ('自动选择', '自动故障转移'):
            select('XFLTD', before_root)
            if before_manual:
                select('手动节点', before_manual)
        elif before_root == '手动节点' and before_manual:
            select('手动节点', before_manual)
            select('XFLTD', before_root)

    held = before_root in ('自动选择', '自动故障转移') and leaf not in before and bool(before_manual)
    published = False
    reload_payload = {"path": "/root/.config/mihomo/config.yaml"}
    try:
        if held:
            select('手动节点', leaf)
            select('XFLTD', '手动节点')
        os.replace(candidate, current)
        published = True
        api(controller, secret, "/configs?force=true", reload_payload)
        if held:
            # Native selection cache may flush asynchronously; enforce the hold
            # after reload as well, then let the first provider checks complete.
            select('手动节点', leaf)
            select('XFLTD', '手动节点')
        elif before_root == '手动节点':
            restore_selection()
        for _ in range(4):
            if verify(controller, secret, proxy, provider_names):
                break
            time.sleep(3)
        else:
            raise RuntimeError("post-reload verification failed")
        if held:
            # Providers load asynchronously. URLTest can cache COMPATIBLE for
            # ten seconds if it was queried before its provider loaded. Keep
            # the working manual exit until the entire auto chain is usable.
            deadline = time.monotonic() + HEALTH_TIMEOUT_MS / 1000 + 15
            while time.monotonic() < deadline:
                providers = api(controller, secret, '/providers/proxies').get('providers', {})
                healthy = {n.get('name') for name, provider in providers.items() if name.startswith('managed-')
                           for n in provider.get('proxies', []) if n.get('alive') and n.get('history')}
                groups = api(controller, secret, '/proxies').get('proxies', {})
                auto_leaf, visited = '自动故障转移', set()
                while auto_leaf in groups and groups[auto_leaf].get('now') and auto_leaf not in visited:
                    visited.add(auto_leaf)
                    auto_leaf = groups[auto_leaf]['now']
                if auto_leaf in healthy:
                    break
                time.sleep(1)
            else:
                raise RuntimeError('automatic groups have not finished loading; working exit retained')
            restore_selection()
            if not verify(controller, secret, proxy, provider_names):
                raise RuntimeError('verification failed after restoring automatic mode')
        print("Applied: original selection mode restored; all providers loaded; HTTPS checks passed.")
        return
    except Exception:
        # Restore the file atomically, then restore runtime state as well.
        if published:
            rollback = data_dir / "config.rollback.yaml"
            shutil.copy2(backup, rollback)
            os.replace(rollback, current)
        try:
            if published:
                api(controller, secret, "/configs?force=true", reload_payload)
            restore_selection()
        except Exception:
            raise RuntimeError("verification failed; previous file restored but controller reload failed") from None
        raise RuntimeError("verification failed; previous configuration reloaded") from None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--data-dir", type=Path, default=Path(os.environ.get("MIHOMO_DATA_DIR", ROOT / "mihomo/data")))
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--controller", default="http://127.0.0.1:9090")
    parser.add_argument("--proxy", default="http://127.0.0.1:7890")
    args = parser.parse_args()
    values = settings(args.env_file)
    sources = sources_from(values)
    data_dir = args.data_dir.resolve()
    validate_mount(data_dir)
    with (data_dir / ".failover.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        base = yaml.safe_load((data_dir / "config.yaml").read_text())
        secret = (data_dir / "API_SECRET").read_text().strip()
        if not secret:
            raise ValueError("controller secret file is empty")
        revision = uuid.uuid4().hex[:12]
        config = build_config(base, sources, revision)
        config["secret"] = secret
        (data_dir / "managed-providers").mkdir(mode=0o700, exist_ok=True)
        os.chmod(data_dir / "managed-providers", 0o700)
        payloads = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            pending = {s: pool.submit(download, s, args.proxy) for s in sources}
            for source, future in pending.items():
                try:
                    payload = future.result()
                    status = "downloaded"
                except ValueError:
                    payload = cached_payload(base, data_dir, source)
                    if payload is None:
                        raise ValueError(f"{source.name}: unavailable and no valid cache") from None
                    status = "using last known cache"
                write_private(data_dir / f"managed-providers/{revision}/{source.name}.yaml", payload)
                payloads.append(payload)
                print(f"{source.name}: {len(payload['proxies'])} nodes, {status}")
        overlap = overlapping_nodes(payloads)
        if overlap:
            print(f"Note: {overlap} node configurations overlap; subscription sources are retained separately.")
        rescue = rescue_payload(base, data_dir)
        if rescue:
            write_private(data_dir / f"managed-providers/{revision}/rescue.yaml", rescue)
            print(f"rescue: retained {len(rescue['proxies'])} existing nodes as a local fallback")
        scoped = configure_node_dns(config, payloads, rescue)
        print(f'Node DNS scoped to {scoped} hostnames; probe timeout {HEALTH_TIMEOUT_MS // 1000}s.')
        candidate = data_dir / "config.failover.candidate.yaml"
        write_private(candidate, config)
        cmd = ["docker", "compose", "-f", str(ROOT / "docker-compose.yml"), "exec", "-T", "mihomo",
               "/mihomo", "-t", "-d", "/root/.config/mihomo", "-f", "/root/.config/mihomo/" + candidate.name]
        checked = subprocess.run(cmd, capture_output=True, timeout=120)
        if checked.returncode:
            raise ValueError("Mihomo rejected candidate; running configuration unchanged")
        print("Candidate validated by running Mihomo version.")
        if args.apply:
            apply_candidate(data_dir, candidate, args.controller, secret, args.proxy,
                            list(config["proxy-providers"]))
        else:
            print("Prepared only; use --apply to publish and verify.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError, yaml.YAMLError):
        # Some OS/subprocess errors embed request details or file contents.
        print("Failover setup failed; inspect configuration locally. No subscription URLs were logged.", file=sys.stderr)
        raise SystemExit(1)
