#!/usr/bin/env python3
"""Install only the private Reddit browser worker; no network/firewall changes."""
import argparse
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent
UNIT = 'mirage-reddit-browser.service'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser', required=True, help='Existing Chrome/Chromium executable')
    args = parser.parse_args()
    browser = Path(args.browser).resolve(strict=True)
    node = Path(shutil.which('node')).resolve(strict=True)
    if not (ROOT / 'node_modules/@jackwener/opencli/dist/src/main.js').exists():
        raise SystemExit('Run npm ci --ignore-scripts in browser-worker first')
    import hashlib
    import json
    lock = json.loads((ROOT / 'reddit-source-lock.json').read_text())
    for name, digest in lock['files'].items():
        source = ROOT / 'node_modules/@jackwener/opencli/clis/reddit' / name
        if not source.exists() or hashlib.sha256(source.read_bytes()).hexdigest() != digest:
            raise SystemExit('Run prepare_runtime.py to verify reviewed adapters first')
    if any(c in str(ROOT) + str(browser) + str(node) for c in '\n\r"%'):
        raise SystemExit('Unsupported path')
    unit = Path.home() / '.config/systemd/user' / UNIT
    unit.parent.mkdir(parents=True, exist_ok=True)
    content = f'''[Unit]
Description=WebMirage private Reddit browser worker

[Service]
Type=simple
WorkingDirectory={ROOT}
ExecStart="{node}" "{ROOT}/worker.mjs"
Environment="REDDIT_BROWSER_EXECUTABLE={browser}"
Environment="REDDIT_BROWSER_PROXY=http://127.0.0.1:7890"
Restart=on-failure
RestartSec=5
TimeoutStopSec=15
KillMode=control-group
UMask=0077

[Install]
WantedBy=default.target
'''
    candidate = ROOT.parent / 'gateway/artifacts/reddit-browser' / UNIT
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_text(content)
    subprocess.run(['systemd-analyze', '--user', 'verify', str(candidate)], check=True)
    unit.write_text(content)
    subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', '--user', 'enable', '--now', UNIT], check=True)
    print('Private Reddit browser worker enabled; browser starts on demand')


if __name__ == '__main__':
    main()
