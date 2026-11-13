#!/usr/bin/env python3
"""Read-only HTTP check: reject a different application's SPA fallback."""
from __future__ import annotations

import argparse
import json
import re
import urllib.request
from pathlib import Path


def check(base: str) -> None:
    base = base.rstrip("/")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(base + "/api/session", timeout=5) as response:
        if response.headers.get_content_type() != "application/json":
            raise ValueError("Session API returned HTML instead of gateway JSON")
        data = json.load(response)
        if any(type(data.get(key)) is not bool for key in ("authenticated", "configured")):
            raise ValueError("Session API returned a different application's response")
    expected = (Path(__file__).parent / "frontend/dist/index.html").read_bytes()
    with opener.open(base + "/", timeout=5) as response:
        if response.read() != expected:
            raise ValueError("URL did not return the current WebMirage console")
    for path in re.findall(r'(?:src|href)="(/assets/[^\"]+)"', expected.decode()):
        with opener.open(base + path, timeout=5) as response:
            if response.headers.get_content_type() not in ("text/javascript", "application/javascript", "text/css"):
                raise ValueError("Frontend asset returned an unexpected content type")
    print("PASS: WebMirage page, session protocol and frontend assets")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    check(parser.parse_args().url)
