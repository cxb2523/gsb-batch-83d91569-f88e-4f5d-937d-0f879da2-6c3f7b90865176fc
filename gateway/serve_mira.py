#!/usr/bin/env python3
"""Serve the gateway only on Mira's existing internal Docker bridge interface.

No container/port mappings, firewall, routes, or proxy configuration are modified.
"""
from __future__ import annotations

import ipaddress
import json
import os
import subprocess
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parent.parent


def frontend_info(name: str = "mira-frontend") -> dict:
    result = subprocess.run(["docker", "inspect", name], capture_output=True, text=True,
                            check=True, timeout=10)
    return json.loads(result.stdout)[0]


def bridge_address(info: dict) -> str:
    networks = info["NetworkSettings"]["Networks"]
    if len(networks) != 1:
        raise RuntimeError("Mira must have one known network; inspect its application deployment first")
    address = next(iter(networks.values()))["Gateway"]
    value = ipaddress.ip_address(address)
    if not value.is_private or value.is_loopback or value.is_unspecified:
        raise RuntimeError("Refusing to listen on a non-private bridge address")
    return address


def main() -> None:
    host = bridge_address(frontend_info())
    data = ROOT / "mihomo/data"
    os.environ.update({
        "MIHOMO_CONTROLLER": "http://127.0.0.1:9090",
        "MIHOMO_API_SECRET": (data / "API_SECRET").read_text().strip(),
        "GATEWAY_ADMIN_PASSWORD_FILE": str(data / "gateway-admin-password"),
        "GATEWAY_CONFIG": str(data / "config.yaml"),
        "GATEWAY_STATIC_DIR": str(ROOT / "gateway/frontend/dist"),
        "GATEWAY_COOKIE_PATH": "/gateway/",
        "GATEWAY_PLATFORM_BRIDGE": "1",
    })
    uvicorn.run("app:app", host=host, port=8091, proxy_headers=False, server_header=False)


if __name__ == "__main__":
    main()
