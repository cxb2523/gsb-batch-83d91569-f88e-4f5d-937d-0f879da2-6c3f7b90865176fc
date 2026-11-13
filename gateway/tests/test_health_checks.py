import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).parents[1]))
from health_checks import CHECK_URL, ProbeManager


class ProbeTests(unittest.IsolatedAsyncioTestCase):
    async def test_bounded_scope_duplicates_expected_status_and_cooldown(self):
        in_flight = peak = 0
        calls = []

        async def handler(request):
            nonlocal in_flight, peak
            calls.append(request)
            if request.url.path.endswith('/healthcheck'):
                in_flight += 1
                peak = max(peak, in_flight)
                self.assertEqual(request.url.params['url'], CHECK_URL)
                self.assertEqual(request.url.params['expected'], '204')
                await asyncio.sleep(.01)
                in_flight -= 1
                return httpx.Response(200, json={'delay': 42})
            good = not request.url.path.endswith('node-0')
            return httpx.Response(200, json={'alive': True, 'history': [{'delay': 42}],
                'extra': {CHECK_URL: {'alive': good, 'history': [{'delay': 42 if good else 0}]}}})

        async with httpx.AsyncClient(base_url='http://controller', transport=httpx.MockTransport(handler)) as client:
            manager = ProbeManager(client)
            rows = [('managed-primary', f'node-{i}') for i in range(7)]
            with patch('health_checks.COOLDOWN', 60):
                manager.start(rows, 'page')
                task = manager.task
                self.assertEqual(manager.start(rows, 'page')['total'], 7)
                self.assertIs(manager.task, task)
                await task
                status = manager.public()
                self.assertEqual(status['status'], 'done')
                self.assertEqual(status['completed'], 7)
                self.assertEqual(status['passed'], 6)
                self.assertEqual(status['failed'], 1)
                self.assertLessEqual(peak, 4)
                self.assertGreater(peak, 1)
                self.assertEqual(sum(r.url.path.endswith('/healthcheck') for r in calls), 7)
                with self.assertRaises(ValueError):
                    manager.start(rows, 'all')

    async def test_controller_outage_is_incomplete_not_all_nodes_failed(self):
        async def handler(request):
            raise httpx.ConnectError('sensitive details', request=request)
        async with httpx.AsyncClient(base_url='http://controller', transport=httpx.MockTransport(handler)) as client:
            manager = ProbeManager(client)
            manager.start([('managed-primary', 'node')], 'current')
            await manager.task
            status = manager.public()
            self.assertEqual(status['status'], 'error')
            self.assertEqual(status['completed'], 0)
            self.assertEqual(status['failed'], 0)
            self.assertNotIn('sensitive', status['error'])

    async def test_shutdown_cancels_background_work(self):
        started = asyncio.Event()
        async def handler(request):
            started.set()
            await asyncio.Event().wait()
        async with httpx.AsyncClient(base_url='http://controller', transport=httpx.MockTransport(handler)) as client:
            manager = ProbeManager(client)
            manager.start([('managed-primary', 'node')], 'current')
            await started.wait()
            await manager.close()
            self.assertTrue(manager.task.done())
            self.assertEqual(manager.public()['status'], 'cancelled')
