#!/usr/bin/env python3
"""Pin reviewed adapters separately from the npm runtime; never fetch main/latest."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, help='Optional verified local OpenCLI checkout')
    args = parser.parse_args()
    lock = json.loads((ROOT / 'reddit-source-lock.json').read_text())
    runtime = ROOT / 'node_modules/@jackwener/opencli'
    if json.loads((runtime / 'package.json').read_text())['version'] != lock['runtime']:
        raise SystemExit('Unexpected OpenCLI runtime version')
    verified = {}
    for name, digest in lock['files'].items():
        if args.source:
            data = (args.source / 'clis/reddit' / name).read_bytes()
        else:
            url = f"https://raw.githubusercontent.com/jackwener/opencli/{lock['commit']}/clis/reddit/{name}"
            with urllib.request.urlopen(url, timeout=30) as response:
                data = response.read(200_001)
        if len(data) > 200_000 or hashlib.sha256(data).hexdigest() != digest:
            raise SystemExit('Reviewed adapter integrity check failed: ' + name)
        verified[name] = data
    for name, data in verified.items():
        dest = runtime / 'clis/reddit' / name
        temporary = dest.with_suffix('.verified-tmp')
        temporary.write_bytes(data)
        temporary.replace(dest)
    print('Prepared reviewed Reddit adapters at ' + lock['commit'][:12])


if __name__ == '__main__':
    main()
