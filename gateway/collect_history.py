#!/usr/bin/env python3
"""Single independent history collector; reads Mihomo without changing its config."""
from __future__ import annotations

import fcntl
import logging
import os
import time
from pathlib import Path

import httpx

from history_store import HistoryStore, INTERVAL

ROOT = Path(__file__).resolve().parent.parent


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    logging.getLogger('httpx').setLevel(logging.WARNING)
    path = Path(os.environ.get('GATEWAY_HISTORY_DB', ROOT / 'gateway/data/history.sqlite3'))
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.with_suffix('.collector.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        secret = (ROOT / 'mihomo/data/API_SECRET').read_text().strip()
        store = HistoryStore(path, time.time())
        try:
            with httpx.Client(base_url='http://127.0.0.1:9090', timeout=5, trust_env=False,
                              headers={'Authorization': 'Bearer ' + secret}) as client:
                offline = False
                while True:
                    began = time.monotonic()
                    try:
                        response = client.get('/connections')
                        response.raise_for_status()
                        store.ingest(response.json(), time.time())
                        if offline:
                            logging.info('Connection history collection resumed; gap recorded.')
                        offline = False
                    except (httpx.HTTPError, ValueError, TypeError):
                        store.failed(time.time())
                        if not offline:
                            logging.warning('Mihomo unavailable; history coverage gap recorded.')
                        offline = True
                    time.sleep(max(0.05, INTERVAL - (time.monotonic() - began)))
        finally:
            store.close()


if __name__ == '__main__':
    main()
