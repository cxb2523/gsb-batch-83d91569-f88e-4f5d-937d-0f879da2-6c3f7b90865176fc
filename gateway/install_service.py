#!/usr/bin/env python3
"""Install only WebMirage's user-level console service; never edit Mira."""
from __future__ import annotations

import argparse
import ipaddress
import os
import subprocess
import sys
import time
from pathlib import Path

from check_console import check

ROOT = Path(__file__).resolve().parent.parent
UNIT = "mirage-gateway-api.service"


def main(host: str) -> None:
    address = ipaddress.ip_address(host)
    if not address.is_private or address.is_unspecified or address.version != 4:
        raise ValueError("Choose a specific private IPv4 address on this server")
    # Do not replace a working service with a build for the retired Mira path.
    index = (ROOT / "gateway/frontend/dist/index.html").read_text()
    if '/gateway/assets/' in index or '/assets/' not in index:
        raise RuntimeError("Build first with VITE_APP_BASE=/")
    unit = Path.home() / ".config/systemd/user" / UNIT
    old = unit.read_text() if unit.exists() else None
    unit.parent.mkdir(parents=True, exist_ok=True)
    revision = ROOT / "gateway/artifacts/standalone" / time.strftime("%Y%m%d-%H%M%S")
    revision.mkdir(parents=True, exist_ok=True)
    if old is not None:
        (revision / "api.service.before").write_text(old)
    executable = str(Path(sys.executable).absolute()).replace('%', '%%')
    root = str(ROOT).replace('%', '%%')
    if any(c in root + executable for c in '\n\r"'):
        raise ValueError("Unsupported installation path")
    content = f'''[Unit]
Description=WebMirage independent gateway and platform management console

[Service]
Type=simple
WorkingDirectory={root}
Environment=GATEWAY_HOST={host}
ExecStart="{executable}" "{root}/gateway/serve.py"
Restart=on-failure
RestartSec=5
UMask=0077

[Install]
WantedBy=default.target
'''
    candidate = revision / UNIT
    candidate.write_text(content)
    subprocess.run(["systemd-analyze", "--user", "verify", str(candidate)], check=True)
    # Retire the old task that rewrites Mira's /gateway/ route. Leave Mira's
    # source, static files and running containers entirely alone.
    subprocess.run(["systemctl", "--user", "disable", "--now", "mirage-gateway-page.timer"], check=True)
    temp = unit.with_suffix('.tmp')
    temp.write_text(content)
    os.replace(temp, unit)
    try:
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "--user", "enable", UNIT], check=True)
        subprocess.run(["systemctl", "--user", "restart", UNIT], check=True)
        for attempt in range(20):
            try:
                check(f"http://{host}:8091")
                break
            except (OSError, ValueError):
                if attempt == 19:
                    raise RuntimeError("Independent console HTTP verification failed") from None
                time.sleep(.5)
    except Exception:
        if old is not None:
            unit.write_text(old)
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
            subprocess.run(["systemctl", "--user", "restart", UNIT], check=True)
        raise
    print(f"WebMirage console: http://{host}:8091/")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, help="Existing private IP, e.g. 192.168.188.3")
    main(parser.parse_args().host)
