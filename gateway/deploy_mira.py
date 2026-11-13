#!/usr/bin/env python3
"""Add /gateway/ to the existing Mira application server, without new public ports.

Edits only the managed nginx location block and a user-level application unit.
Never recreates containers or changes published ports, firewall, routes or Mihomo.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from serve_mira import ROOT, bridge_address, frontend_info

BEGIN = "    # BEGIN MIRAGE GATEWAY (application route only)"
END = "    # END MIRAGE GATEWAY"
CONTAINER = "mira-frontend"
RUNTIME_CONF = "/etc/nginx/conf.d/default.conf"


def check_session(body: bytes, content_type: str) -> None:
    """A SPA fallback also returns 200: require the actual gateway protocol."""
    if content_type.split(";", 1)[0] != "application/json":
        raise ValueError("Gateway API returned a page instead of JSON")
    session = json.loads(body)
    if not isinstance(session, dict) or any(type(session.get(k)) is not bool for k in ("authenticated", "configured")):
        raise ValueError("Gateway API returned an unexpected session response")


def check_route(opener) -> None:
    with opener.open("http://192.168.188.3:8086/gateway/api/session", timeout=3) as response:
        check_session(response.read(), response.headers.get("Content-Type", ""))
    with opener.open("http://192.168.188.3:8086/gateway/", timeout=3) as response:
        if response.read() != (ROOT / "gateway/frontend/dist/index.html").read_bytes():
            raise ValueError("Gateway URL did not return the deployed gateway page")


def render_route(original: str, bridge: str) -> str:
    if BEGIN in original:
        start = original.index(BEGIN)
        finish = original.index(END, start) + len(END)
        original = original[:start] + original[finish:].lstrip("\n")
    marker = "    location / {"
    if original.count(marker) != 1:
        raise ValueError("Cannot safely identify Mira's existing application route")
    block = f"""{BEGIN}
    location = /gateway {{
        absolute_redirect off;
        return 302 /gateway/;
    }}
    location ^~ /gateway/api/ {{
        proxy_pass http://{bridge}:8091/api/;
        proxy_http_version 1.1;
        proxy_set_header Host $http_host;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_read_timeout 20s;
    }}
    location ^~ /gateway/ {{
        try_files $uri $uri/ /gateway/index.html;
        add_header Cache-Control "no-store, max-age=0, must-revalidate" always;
    }}
{END}

"""
    return original.replace(marker, block + marker, 1)


def docker(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], check=True, capture_output=True, text=True, timeout=20)


def runtime_write(content: str) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".conf") as temp:
        temp.write(content)
        temp.flush()
        docker("cp", temp.name, f"{CONTAINER}:{RUNTIME_CONF}")


def main(repair_only: bool = False) -> None:
    # The release command and periodic recovery must not mutate the app together.
    lock_path = ROOT / "gateway/artifacts/deploy.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        deploy(repair_only)


def deploy(repair_only: bool = False) -> None:
    info = frontend_info(CONTAINER)
    bridge = bridge_address(info)
    original_ports = info["HostConfig"]["PortBindings"]
    original_networks = info["NetworkSettings"]["Networks"]
    original_runtime = docker("exec", CONTAINER, "cat", RUNTIME_CONF).stdout
    deploy_dir = Path(info["Config"]["Labels"]["com.docker.compose.project.working_dir"])
    source = deploy_dir / "nginx.standalone.conf"
    original_source = source.read_text()
    static = ROOT / "gateway/frontend/dist"
    if not (static / "index.html").is_file() or '/gateway/assets/' not in (static / "index.html").read_text():
        raise RuntimeError("Build the Vue page with VITE_APP_BASE=/gateway/ first")
    public = deploy_dir.parent / "public/gateway"
    if repair_only and (BEGIN not in original_source or not (public / ".mirage-managed").is_file()):
        raise RuntimeError("Automatic repair requires the previously installed, owned Mira gateway integration")
    if public.exists() and not (public / ".mirage-managed").is_file():
        raise RuntimeError("Mira already has an unrelated /gateway/ page; refusing to overwrite")
    new_source = render_route(original_source, bridge)
    new_runtime = render_route(original_runtime, bridge)
    revision = ROOT / "gateway/artifacts/deployments" / time.strftime("%Y%m%d-%H%M%S")
    revision.mkdir(parents=True, exist_ok=True)
    (revision / "nginx.source.before.conf").write_text(original_source)
    (revision / "nginx.runtime.before.conf").write_text(original_runtime)
    (revision / "ports.before.json").write_text(json.dumps(original_ports, indent=2))
    had_public = public.exists()
    if had_public:
        shutil.copytree(public, revision / "public.before")
    had_runtime = subprocess.run(["docker", "exec", CONTAINER, "test", "-d", "/usr/share/nginx/html/gateway"],
                                 capture_output=True).returncode == 0
    if had_runtime:
        # Only replace a previous deployment of this app, never another page.
        docker("exec", CONTAINER, "test", "-f", "/usr/share/nginx/html/gateway/.mirage-managed")
        docker("cp", f"{CONTAINER}:/usr/share/nginx/html/gateway", str(revision / "runtime.before"))

    if not repair_only:
        install_services()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for attempt in range(20):
        try:
            with opener.open(f"http://{bridge}:8091/api/session", timeout=2) as response:
                check_session(response.read(), response.headers.get("Content-Type", ""))
                break
        except (OSError, ValueError):
            time.sleep(0.5)
    else:
        raise RuntimeError("Private application backend did not start; Mira unchanged")
    # Verify the existing nginx container can reach the private application backend first.
    check_session(docker("exec", CONTAINER, "wget", "-q", "-O", "-", f"http://{bridge}:8091/api/session").stdout.encode(), "application/json")
    try:
        public.mkdir(parents=True, exist_ok=True)
        shutil.copytree(static, public, dirs_exist_ok=True)
        (public / ".mirage-managed").write_text("Mirage gateway static page\n")
        docker("exec", CONTAINER, "mkdir", "-p", "/usr/share/nginx/html/gateway")
        docker("cp", str(public) + "/.", f"{CONTAINER}:/usr/share/nginx/html/gateway")
        runtime_write(new_runtime)
        docker("exec", CONTAINER, "nginx", "-t")
        if source.read_text() != original_source:
            raise RuntimeError("Mira source changed during deployment; refusing to overwrite it")
        if new_source != original_source:
            source.write_text(new_source)
        docker("exec", CONTAINER, "nginx", "-s", "reload")
        for attempt in range(10):
            try:
                check_route(opener)
                break
            except (OSError, ValueError):
                time.sleep(0.5)
        else:
            raise RuntimeError("New application route did not return the gateway page and session JSON")
        after = frontend_info(CONTAINER)
        if after["Id"] != info["Id"]:
            raise RuntimeError("Mira was replaced during gateway deployment")
        if after["HostConfig"]["PortBindings"] != original_ports or after["NetworkSettings"]["Networks"] != original_networks:
            raise RuntimeError("Unexpected deployment topology change")
    except Exception:
        # Do not write into a different container if another release raced this one.
        if frontend_info(CONTAINER)["Id"] != info["Id"]:
            raise RuntimeError("Mira was replaced concurrently; leaving the new release untouched")
        runtime_write(original_runtime)
        if source.read_text() == new_source and original_source != new_source:
            source.write_text(original_source)
        docker("exec", CONTAINER, "nginx", "-t")
        docker("exec", CONTAINER, "nginx", "-s", "reload")
        # Both paths were verified above to belong to this application.
        if public.exists():
            shutil.rmtree(public)
        if had_public:
            shutil.copytree(revision / "public.before", public)
        docker("exec", CONTAINER, "rm", "-rf", "/usr/share/nginx/html/gateway")
        if had_runtime:
            docker("cp", str(revision / "runtime.before"), f"{CONTAINER}:/usr/share/nginx/html/gateway")
        raise
    if not repair_only:
        subprocess.run(["systemctl", "--user", "enable", "--now", "mirage-gateway-page.timer"], check=True)
    print("Ready: http://192.168.188.3:8086/gateway/")
    print("Existing published ports and container networks are unchanged.")


def install_services() -> None:
    unit_dir = Path.home() / ".config/systemd/user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    unit = unit_dir / "mirage-gateway-api.service"
    unit.write_text(f"""[Unit]
Description=Mirage gateway application API for Mira /gateway/

[Service]
Type=simple
WorkingDirectory={ROOT}
ExecStart={ROOT}/gateway/.venv/bin/python {ROOT}/gateway/serve_mira.py
Restart=on-failure
RestartSec=5
UMask=0077

[Install]
WantedBy=default.target
""")
    (unit_dir / 'mirage-gateway-history.service').write_text(f"""[Unit]
Description=Persistent sampled connection and traffic history for Mirage

[Service]
Type=simple
WorkingDirectory={ROOT}
ExecStart={ROOT}/gateway/.venv/bin/python {ROOT}/gateway/collect_history.py
Restart=on-failure
RestartSec=5
UMask=0077

[Install]
WantedBy=default.target
""")
    (unit_dir / "mirage-gateway-page.service").write_text(f"""[Unit]
Description=Check and restore only Mira's installed gateway application page
After=mirage-gateway-api.service

[Service]
Type=oneshot
WorkingDirectory={ROOT}
ExecStart={ROOT}/gateway/.venv/bin/python {ROOT}/gateway/ensure_mira.py
TimeoutStartSec=90
UMask=0077
""")
    (unit_dir / "mirage-gateway-page.timer").write_text("""[Unit]
Description=Keep the gateway application page available across Mira releases

[Timer]
OnBootSec=45s
OnUnitActiveSec=60s
AccuracySec=5s

[Install]
WantedBy=timers.target
""")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", unit.name], check=True)
    subprocess.run(["systemctl", "--user", "restart", unit.name], check=True)
    subprocess.run(["systemctl", "--user", "enable", '--now', 'mirage-gateway-history.service'], check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repair-only", action="store_true", help="Restore a previously installed page without restarting the API or changing services")
    main(repair_only=parser.parse_args().repair_only)
