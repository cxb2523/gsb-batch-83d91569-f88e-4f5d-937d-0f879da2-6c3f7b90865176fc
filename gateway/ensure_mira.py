#!/usr/bin/env python3
"""Restore only an already installed gateway page after Mira container replacement.

Does not rebuild/recreate containers, change listeners, ports, firewall or Mihomo.
An upstream API outage reports failure without rewriting nginx or restarting Mira.
"""
from __future__ import annotations

import hashlib
import subprocess
import urllib.request
from pathlib import Path

from deploy_mira import BEGIN, CONTAINER, RUNTIME_CONF, check_route, docker, main as deploy, render_route
from serve_mira import ROOT, bridge_address, frontend_info


def expected_files(static: Path) -> dict[str, str]:
    return {
        "/usr/share/nginx/html/gateway/" + path.relative_to(static).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(static.rglob("*")) if path.is_file()
    }


def files_match(output: str, expected: dict[str, str]) -> bool:
    actual = {}
    for line in output.splitlines():
        digest, separator, path = line.partition("  ")
        if not separator:
            return False
        actual[path] = digest
    return bool(expected) and actual == expected


def main() -> None:
    info = frontend_info(CONTAINER)
    if not info["State"]["Running"]:
        raise RuntimeError("Mira is stopped; waiting for its own deployment to start it")
    deploy_dir = Path(info["Config"]["Labels"]["com.docker.compose.project.working_dir"])
    if BEGIN not in (deploy_dir / "nginx.standalone.conf").read_text() or not (deploy_dir.parent / "public/gateway/.mirage-managed").is_file():
        raise RuntimeError("No owned gateway integration found; refusing automatic installation")
    conf = docker("exec", CONTAINER, "cat", RUNTIME_CONF).stdout
    route_missing = render_route(conf, bridge_address(info)) != conf
    expected = expected_files(ROOT / "gateway/frontend/dist")
    if not expected:
        raise RuntimeError("Gateway build is missing; refusing automatic repair")
    # Missing assets are expected after container replacement; inspect without mutation.
    result = subprocess.run(["docker", "exec", CONTAINER, "sha256sum", *expected],
                            capture_output=True, text=True, timeout=20)
    assets_missing = result.returncode != 0 or not files_match(result.stdout, expected)
    if route_missing or assets_missing:
        print("Gateway route or static files lost during Mira release; restoring the owned page.", flush=True)
        deploy(repair_only=True)
    else:
        # A failure here is an API outage, not grounds to rewrite working page files.
        check_route(urllib.request.build_opener(urllib.request.ProxyHandler({})))
        print("Gateway page and session API are healthy; no changes.")


if __name__ == "__main__":
    main()
