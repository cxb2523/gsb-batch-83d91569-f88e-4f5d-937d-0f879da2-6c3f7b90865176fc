"""Bounded, on-demand checks; status reads never initiate network probes."""
from __future__ import annotations

import asyncio
import math
import time
from urllib.parse import quote

import httpx

CHECK_URL = 'https://www.gstatic.com/generate_204'
TIMEOUT_MS = 20000
CONCURRENCY = 4
COOLDOWN = 60


def probe_history(raw: dict) -> tuple[list, bool]:
    # Per-URL state includes the expected HTTP status, unlike generic alive.
    state = (raw.get('extra') or {}).get(CHECK_URL)
    if state is not None:
        return state.get('history') or [], bool(state.get('alive'))
    return raw.get('history') or [], bool(raw.get('alive'))


class ProbeManager:
    def __init__(self, client):
        self.client = client
        self.task = None
        self.finished = None
        self.state = {'status': 'idle', 'scope': None, 'total': 0, 'completed': 0,
                      'passed': 0, 'failed': 0, 'started_at': None, 'finished_at': None, 'error': None}

    def public(self):
        remaining = max(0, COOLDOWN - (time.monotonic() - self.finished)) if self.finished is not None else 0
        return {**self.state, 'cooldown_seconds': math.ceil(remaining), 'concurrency': CONCURRENCY}

    def start(self, nodes: list[tuple[str, str]], scope: str):
        if self.task and not self.task.done():
            return self.public()
        if self.public()['cooldown_seconds']:
            raise ValueError('请等待冷却结束后再检测，避免重复请求')
        self.state = {'status': 'running', 'scope': scope, 'total': len(nodes), 'completed': 0,
                      'passed': 0, 'failed': 0, 'started_at': time.time(), 'finished_at': None, 'error': None}
        self.task = asyncio.create_task(self._run(nodes))
        return self.public()

    async def _run(self, nodes):
        queue = asyncio.Queue()
        for item in nodes:
            queue.put_nowait(item)

        async def worker():
            while not queue.empty() and not self.state['error']:
                provider, name = queue.get_nowait()
                path = '/providers/proxies/' + quote(provider, safe='') + '/' + quote(name, safe='')
                try:
                    response = await self.client.get(path + '/healthcheck',
                                                     params={'url': CHECK_URL, 'timeout': TIMEOUT_MS, 'expected': '204'},
                                                     timeout=TIMEOUT_MS / 1000 + 5)
                    if response.status_code not in (200, 503, 504):
                        response.raise_for_status()
                    # Read actual health state, including expected-status failures.
                    result = await self.client.get(path)
                    result.raise_for_status()
                    history, alive = probe_history(result.json())
                    passed = alive and bool(history) and history[-1].get('delay', 0) > 0
                    self.state['passed' if passed else 'failed'] += 1
                    self.state['completed'] += 1
                except (httpx.HTTPError, ValueError):
                    self.state['error'] = '控制器连接异常，部分节点未完成检测；保留已有检测记录'
                    return
                await asyncio.sleep(.25)

        try:
            await asyncio.gather(*(worker() for _ in range(min(CONCURRENCY, len(nodes)))))
            self.state['status'] = 'error' if self.state['error'] else 'done'
        except asyncio.CancelledError:
            self.state['status'] = 'cancelled'
            raise
        finally:
            self.finished = time.monotonic()
            self.state['finished_at'] = time.time()

    async def close(self):
        if self.task and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
