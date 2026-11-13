#!/usr/bin/env python3
"""Run WebMirage's own management console, independently of Mira."""
from __future__ import annotations

import ipaddress
import os
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parent.parent


def configure() -> tuple[str, int]:
    # Require an explicit local address to publish beyond loopback. No Docker
    # discovery, proxy-server reconfiguration, or system network changes.
    host = os.environ.get("GATEWAY_HOST", "127.0.0.1")
    address = ipaddress.ip_address(host)
    if not address.is_private or address.is_unspecified:
        raise ValueError("GATEWAY_HOST must be a specific private or loopback IP")
    port = int(os.environ.get("GATEWAY_PORT", "8091"))
    if not 1024 <= port <= 65535:
        raise ValueError("GATEWAY_PORT must be between 1024 and 65535")
    static = ROOT / "gateway/frontend/dist"
    if '/assets/' not in (static / "index.html").read_text() or '/gateway/assets/' in (static / "index.html").read_text():
        raise RuntimeError("Build the standalone frontend with VITE_APP_BASE=/")
    data = ROOT / "mihomo/data"
    os.environ.update({
        "MIHOMO_CONTROLLER": "http://127.0.0.1:9090",
        "MIHOMO_API_SECRET": (data / "API_SECRET").read_text().strip(),
        "GATEWAY_ADMIN_PASSWORD_FILE": str(data / "gateway-admin-password"),
        "GATEWAY_CONFIG": str(data / "config.yaml"),
        "GATEWAY_STATIC_DIR": str(static),
        "GATEWAY_COOKIE_PATH": "/",
        "GATEWAY_PLATFORM_BRIDGE": "1",
    })
    return host, port


def main() -> None:
    host, port = configure()
    uvicorn.run("app:app", host=host, port=port, proxy_headers=False, server_header=False)


if __name__ == "__main__":
    main()
