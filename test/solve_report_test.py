import asyncio
import unittest
from unittest import mock

from capmonstercloudclient import CapMonsterClient, ClientOptions
from capmonstercloudclient import CapMonsterCloudClient as client_module
from capmonstercloudclient.GetResultTimeouts import GetResultTimeouts
from capmonstercloudclient.exceptions import (
    GetResultError,
    GetTaskError,
    UnknownRequestInstanceError,
)
from capmonstercloudclient.requests import RecaptchaV2Request
from capmonstercloudclient.solveReport import SolveReport, SolveStatus


API_KEY = 'test-api-key'
TASK_ID = 'fake-task-id'


class _FakeJsonResponse:
    def __init__(self, status, payload):
        self.status = status
        self._payload = payload

    async def json(self, content_type=None):
        return self._payload


class _FakeRequestContext:
    def __init__(self, coro_factory):
        self._coro_factory = coro_factory

    async def __aenter__(self):
        return await self._coro_factory()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeAiohttpSession:
    '''Minimal stand-in for ``aiohttp.ClientSession`` used by the client.

    ``handler`` is called with (url, body) and must return either a
    ``_FakeJsonResponse`` or an awaitable resolving to one.
    '''

    calls = []

    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def post(self, url, json=None, timeout=None, headers=None, proxy=None):
        self.calls.append((url, json))
        type(self).calls.append((url, json))
        return _FakeRequestContext(lambda: self._respond(url, json))

    async def _respond(self, url, body):
        result = self.handler(url, body)
        if asyncio.iscoroutine(result) or asyncio.isfuture(result):
            result = await result
        return result


def _fake_session_factory(handler):
    def factory(*args, **kwargs):
        return FakeAiohttpSession(handler)

    return factory


def _make_request():
    return RecaptchaV2Request(
        websiteUrl='https://example.test/captcha',
        websiteKey='fake-site-key',
    )


def _tiny_timeouts(first_delay=0.0, interval=0.001, timeout=0.05):
    return GetResultTimeouts(
        firstRequestDelay=first_delay,
        firstRequestNoCacheDelay=first_delay,
        requestsInterval=interval,
        timeout=timeout,
    )


class SolveReportTestCase(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.client = CapMonsterClient(ClientOptions(api_key=API_KEY))
        self.request = _make_request()
        FakeAiohttpSession.calls = []

    def _patch_timeouts(self, timeouts):
        # Only replace the timeout source for the test; production values in
        # GetResultTimeouts are untouched.
        return mock.patch.object(
            client_module,
            '_instance_config',
            (((RecaptchaV2Request,), lambda: timeouts),),
        )

    def _patch_session(self, handler):
        return mock.patch(
            'aiohttp.ClientSession',
            side_effect=_fake_session_factory(handler),
        )

    async def test_success_reports_status_count_and_solution(self):
        poll_sequence = [
            {'errorId': 0, 'status': 'processing'},
            {'errorId': 0, 'status': 'processing'},
            {'errorId': 0, 'status': 'ready', 'solution': {'gRecaptchaResponse': 'token'}},
        ]
        polls = {'n': 0}

        def handler(url, body):
            if url.endswith('/createTask'):
                return _FakeJsonResponse(200, {'errorId': 0, 'taskId': TASK_ID})
            payload = poll_sequence[min(polls['n'], len(poll_sequence) - 1)]
            polls['n'] += 1
            return _FakeJsonResponse(200, payload)

        with self._patch_timeouts(_tiny_timeouts()), self._patch_session(handler):
            report = await self.client.solve_captcha_with_report(self.request)

        self.assertIsInstance(report, SolveReport)
        self.assertEqual(report.status, SolveStatus.SUCCESS)
        self.assertEqual(report.task_id, TASK_ID)
        self.assertEqual(report.requests_count, 3)
        self.assertEqual(report.solution, {'gRecaptchaResponse': 'token'})
        self.assertIsNone(report.error_id)
        self.assertIsNone(report.error_code)
        self.assertIsNone(report.error_description)
        self.assertGreaterEqual(report.elapsed, 0.0)

    async def test_first_query_ready_counts_one(self):
        def handler(url, body):
            if url.endswith('/createTask'):
                return _FakeJsonResponse(200, {'errorId': 0, 'taskId': TASK_ID})
            return _FakeJsonResponse(
                200, {'errorId': 0, 'status': 'ready', 'solution': {'token': 'x'}}
            )

        with self._patch_timeouts(_tiny_timeouts()), self._patch_session(handler):
            report = await self.client.solve_captcha_with_report(self.request)

        self.assertEqual(report.status, SolveStatus.SUCCESS)
        self.assertEqual(report.requests_count, 1)

    async def test_create_task_failure_report(self):
        def handler(url, body):
            return _FakeJsonResponse(
                200,
                {
                    'errorId': 1,
                    'errorCode': 'ERROR_KEY_DOES_NOT_EXIST',
                    'errorDescription': 'Account authorization key not found',
                },
            )

        with self._patch_timeouts(_tiny_timeouts()), self._patch_session(handler):
            report = await self.client.solve_captcha_with_report(self.request)

        self.assertEqual(report.status, SolveStatus.TASK_FAILED)
        self.assertEqual(report.requests_count, 0)
        self.assertEqual(report.error_id, 1)
        self.assertEqual(report.error_code, 'ERROR_KEY_DOES_NOT_EXIST')
        self.assertEqual(report.error_description, 'Account authorization key not found')
        self.assertEqual(report.error_source, 'createTask')

    async def test_get_result_failure_report(self):
        def handler(url, body):
            if url.endswith('/createTask'):
                return _FakeJsonResponse(200, {'errorId': 0, 'taskId': TASK_ID})
            return _FakeJsonResponse(
                200,
                {
                    'errorId': 12,
                    'errorCode': 'ERROR_CAPTCHA_UNSOLVABLE',
                    'errorDescription': 'Captcha could not be solved',
                },
            )

        with self._patch_timeouts(_tiny_timeouts()), self._patch_session(handler):
            report = await self.client.solve_captcha_with_report(self.request)

        self.assertEqual(report.status, SolveStatus.TASK_FAILED)
        self.assertEqual(report.requests_count, 1)
        self.assertEqual(report.error_id, 12)
        self.assertEqual(report.error_code, 'ERROR_CAPTCHA_UNSOLVABLE')
        self.assertEqual(report.error_description, 'Captcha could not be solved')
        self.assertEqual(report.error_source, 'getTaskResult')

    async def test_timeout_report_keeps_poll_count(self):
        def handler(url, body):
            if url.endswith('/createTask'):
                return _FakeJsonResponse(200, {'errorId': 0, 'taskId': TASK_ID})
            return _FakeJsonResponse(200, {'errorId': 0, 'status': 'processing'})

        with self._patch_timeouts(
            _tiny_timeouts(interval=0.005, timeout=0.05)
        ), self._patch_session(handler):
            report = await self.client.solve_captcha_with_report(self.request)

        self.assertEqual(report.status, SolveStatus.TIMEOUT)
        self.assertEqual(report.task_id, TASK_ID)
        self.assertGreaterEqual(report.requests_count, 1)
        self.assertEqual(
            report.requests_count,
            sum(1 for url, _ in FakeAiohttpSession.calls if url.endswith('/getTaskResult')),
        )
        self.assertLess(report.elapsed, 5.0)
        self.assertIsNone(report.solution)

    async def test_cancel_propagates_and_keeps_partial_report(self):
        never = asyncio.Event()

        async def handler(url, body):
            if url.endswith('/createTask'):
                return _FakeJsonResponse(200, {'errorId': 0, 'taskId': TASK_ID})
            await never.wait()
            return _FakeJsonResponse(200, {'errorId': 0, 'status': 'processing'})

        with self._patch_timeouts(
            _tiny_timeouts(interval=0.005, timeout=30)
        ), self._patch_session(handler):
            task = asyncio.ensure_future(
                self.client.solve_captcha_with_report(self.request)
            )
            # Wait until the first getTaskResult request is in flight.
            for _ in range(200):
                await asyncio.sleep(0.005)
                if any(u.endswith('/getTaskResult') for u, _ in FakeAiohttpSession.calls):
                    break
            task.cancel()
            with self.assertRaises(asyncio.CancelledError) as ctx:
                await task

        report = getattr(ctx.exception, 'report', None)
        self.assertIsInstance(report, SolveReport)
        self.assertEqual(report.status, SolveStatus.CANCELLED)
        self.assertEqual(report.task_id, TASK_ID)
        self.assertEqual(report.requests_count, 1)
        self.assertLess(report.elapsed, 5.0)

    async def test_cancel_during_create_task_keeps_zero_count(self):
        started = asyncio.Event()
        never = asyncio.Event()

        async def handler(url, body):
            started.set()
            await never.wait()
            return _FakeJsonResponse(200, {'errorId': 0, 'taskId': TASK_ID})

        with self._patch_timeouts(
            _tiny_timeouts(interval=0.005, timeout=30)
        ), self._patch_session(handler):
            task = asyncio.ensure_future(
                self.client.solve_captcha_with_report(self.request)
            )
            await asyncio.wait_for(started.wait(), timeout=2)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError) as ctx:
                await task

        report = getattr(ctx.exception, 'report', None)
        self.assertIsInstance(report, SolveReport)
        self.assertEqual(report.status, SolveStatus.CANCELLED)
        self.assertEqual(report.task_id, None)
        self.assertEqual(report.requests_count, 0)

    async def test_unknown_request_instance_still_raises(self):
        with self.assertRaises(UnknownRequestInstanceError):
            await self.client.solve_captcha_with_report('not-a-request')


class LegacySolveCaptchaTestCase(unittest.IsolatedAsyncioTestCase):
    '''solve_captcha must keep its original return value and exceptions.'''

    def setUp(self):
        self.client = CapMonsterClient(ClientOptions(api_key=API_KEY))
        self.request = _make_request()

    def _patch_session(self, handler):
        return mock.patch(
            'aiohttp.ClientSession',
            side_effect=_fake_session_factory(handler),
        )

    def _patch_timeouts(self, timeouts):
        return mock.patch.object(
            client_module,
            '_instance_config',
            (((RecaptchaV2Request,), lambda: timeouts),),
        )

    async def test_returns_solution_dict(self):
        def handler(url, body):
            if url.endswith('/createTask'):
                return _FakeJsonResponse(200, {'errorId': 0, 'taskId': TASK_ID})
            return _FakeJsonResponse(
                200, {'errorId': 0, 'status': 'ready', 'solution': {'a': 'b'}}
            )

        with self._patch_timeouts(_tiny_timeouts()), self._patch_session(handler):
            solution = await self.client.solve_captcha(self.request)
        self.assertEqual(solution, {'a': 'b'})

    async def test_raises_get_task_error(self):
        def handler(url, body):
            return _FakeJsonResponse(
                200, {'errorId': 1, 'errorCode': 'ERROR_KEY_DOES_NOT_EXIST',
                      'errorDescription': 'bad key'}
            )

        with self._patch_timeouts(_tiny_timeouts()), self._patch_session(handler):
            with self.assertRaises(GetTaskError) as ctx:
                await self.client.solve_captcha(self.request)
        self.assertIn('ERROR_KEY_DOES_NOT_EXIST', str(ctx.exception))

    async def test_raises_get_result_error(self):
        def handler(url, body):
            if url.endswith('/createTask'):
                return _FakeJsonResponse(200, {'errorId': 0, 'taskId': TASK_ID})
            return _FakeJsonResponse(
                200, {'errorId': 12, 'errorCode': 'ERROR_CAPTCHA_UNSOLVABLE',
                      'errorDescription': 'cannot solve'}
            )

        with self._patch_timeouts(_tiny_timeouts()), self._patch_session(handler):
            with self.assertRaises(GetResultError) as ctx:
                await self.client.solve_captcha(self.request)
        self.assertIn('ERROR_CAPTCHA_UNSOLVABLE', str(ctx.exception))

    async def test_raises_timeout_error(self):
        def handler(url, body):
            if url.endswith('/createTask'):
                return _FakeJsonResponse(200, {'errorId': 0, 'taskId': TASK_ID})
            return _FakeJsonResponse(200, {'errorId': 0, 'status': 'processing'})

        with self._patch_timeouts(
            _tiny_timeouts(interval=0.005, timeout=0.03)
        ), self._patch_session(handler):
            with self.assertRaises(TimeoutError):
                await self.client.solve_captcha(self.request)

    async def test_unknown_instance(self):
        with self.assertRaises(UnknownRequestInstanceError):
            await self.client.solve_captcha(object())


if __name__ == '__main__':
    unittest.main()
