from __future__ import annotations

import asyncio
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from app.config import Settings
from app.services.screenshots import (
    BROWSER_SCREENSHOT_USER_AGENT,
    ScreenshotResult,
    ScreenshotService,
)

# Generous bound for "the capture returned at all"; the real budgets used by the
# service in these tests are an order of magnitude smaller.
_BOUNDED_TEST_TIMEOUT = 1.0


class ScreenshotConfigurationTests(unittest.TestCase):
    def test_browser_screenshot_user_agent_is_not_service_bot(self) -> None:
        self.assertIn("Mozilla/5.0", BROWSER_SCREENSHOT_USER_AGENT)
        self.assertNotIn("Argus", BROWSER_SCREENSHOT_USER_AGENT)

    def test_browser_disabled_writes_fallback_png(self) -> None:
        with TemporaryDirectory() as tmp:
            settings = Settings(
                evidence_dir=Path(tmp) / "evidence",
                browser_screenshots_enabled=False,
                screenshot_fallback_enabled=True,
            )
            service = ScreenshotService(settings)

            result = asyncio.run(
                service.capture(
                    "https://example.com/login",
                    7,
                    title="Example",
                    html_path="evidence/example.html",
                    status_code=200,
                )
            )

            self.assertEqual(result.path, "evidence/screenshots/run_7_example.com.png")
            self.assertIsNotNone(result.error)
            self.assertTrue((settings.evidence_dir / "screenshots" / "run_7_example.com.png").exists())


class ScreenshotDeadlineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.settings = Settings(
            evidence_dir=Path(self.tmp.name) / "evidence",
            screenshot_timeout_seconds=0.08,
            screenshot_settle_ms=0,
            screenshot_fallback_enabled=False,
        )
        self.service = ScreenshotService(self.settings)
        self.service._capture_result = Mock(
            side_effect=lambda output, rel_path: ScreenshotResult(path=rel_path)
        )
        self.rel_path = "evidence/screenshots/run_7_example.com.png"
        self.page = Mock(
            goto=AsyncMock(),
            wait_for_load_state=AsyncMock(),
            screenshot=AsyncMock(),
        )
        self.cdp = SimpleNamespace(send=AsyncMock())
        self.context = SimpleNamespace(
            new_page=AsyncMock(return_value=self.page),
            new_cdp_session=AsyncMock(return_value=self.cdp),
            close=AsyncMock(),
        )
        self.browser = SimpleNamespace(
            new_context=AsyncMock(return_value=self.context),
            close=AsyncMock(),
        )
        self.playwright = SimpleNamespace(chromium=SimpleNamespace(launch=AsyncMock(return_value=self.browser)))
        self.manager = MagicMock()
        self.manager.start = AsyncMock(return_value=self.playwright)
        self.manager.__aenter__ = AsyncMock(return_value=self.playwright)
        self.manager.__aexit__ = AsyncMock()
        self.playwright_patch = patch("playwright.async_api.async_playwright", return_value=self.manager)
        self.playwright_patch.start()
        self.addCleanup(self.playwright_patch.stop)
        self.cleanup_patch = patch("app.services.screenshots._CLEANUP_TIMEOUT_SECONDS", 0.02)
        self.cleanup_patch.start()
        self.addCleanup(self.cleanup_patch.stop)
        self.cancel_grace_patch = patch("app.services.screenshots._CANCELLATION_GRACE_SECONDS", 0.02)
        self.cancel_grace_patch.start()
        self.addCleanup(self.cancel_grace_patch.stop)

    @staticmethod
    async def _hang(*args, **kwargs):  # noqa: ANN002, ANN003
        await asyncio.Event().wait()

    async def _bounded_capture(self, service: ScreenshotService | None = None) -> ScreenshotResult:
        """Run a capture that must return (or raise) well within the test bound."""
        task = asyncio.create_task((service or self.service).capture("https://example.com", 7))
        done, _ = await asyncio.wait({task}, timeout=_BOUNDED_TEST_TIMEOUT)
        if not done:
            task.cancel()
            await asyncio.wait({task}, timeout=_BOUNDED_TEST_TIMEOUT)
            self.fail("Screenshot capture exceeded its total deadline or hung in cleanup")
        return task.result()

    def _assert_slot_released(self, service: ScreenshotService | None = None) -> None:
        slots = (service or self.service)._browser_slots
        self.assertTrue(slots.acquire(blocking=False), "Screenshot slot leaked")
        slots.release()

    async def _assert_no_pending_tasks(self) -> None:
        # Let cancelled child tasks run their cancellation handling.
        for _ in range(5):
            await asyncio.sleep(0)
        pending = [
            task
            for task in asyncio.all_tasks()
            if task is not asyncio.current_task() and not task.done()
        ]
        self.assertEqual(pending, [], "Background asyncio task leaked from capture")

    # -- happy path and preserved behaviour ---------------------------------

    async def test_successful_capture_returns_relative_evidence_path(self) -> None:
        result = await self._bounded_capture()

        self.assertEqual(result.path, self.rel_path)
        self.assertIsNone(result.error)
        self.page.screenshot.assert_awaited()
        self.context.close.assert_awaited_once()
        self.browser.close.assert_awaited_once()
        self.manager.__aexit__.assert_awaited_once()
        self._assert_slot_released()
        await self._assert_no_pending_tasks()

    async def test_blank_screenshot_is_deleted_and_reported(self) -> None:
        from PIL import Image

        async def write_blank(*args, **kwargs):  # noqa: ANN002, ANN003
            Image.new("RGB", (16, 16), "#ffffff").save(kwargs["path"])

        service = ScreenshotService(self.settings)
        self.page.screenshot.side_effect = write_blank

        result = await self._bounded_capture(service)

        self.assertIsNone(result.path)
        self.assertIn("blank", result.error.lower())
        self.assertFalse((self.settings.screenshots_dir / "run_7_example.com.png").exists())
        self._assert_slot_released(service)

    async def test_timeout_writes_fallback_png_when_enabled(self) -> None:
        fallback_settings = replace(self.settings, screenshot_fallback_enabled=True)
        fallback_service = ScreenshotService(fallback_settings)
        self.playwright.chromium.launch.side_effect = self._hang

        result = await self._bounded_capture(fallback_service)

        self.assertEqual(result.path, self.rel_path)
        self.assertIn("timed out", result.error.lower())
        self.assertTrue((fallback_settings.evidence_dir / "screenshots" / "run_7_example.com.png").exists())
        self._assert_slot_released(fallback_service)
        await self._assert_no_pending_tasks()

    # -- every blocking step is bounded by the total timeout ----------------

    async def test_hanging_browser_launch_obeys_total_deadline(self) -> None:
        self.playwright.chromium.launch.side_effect = self._hang

        result = await self._bounded_capture()

        self.assertIsNone(result.path)
        self.assertIn("timed out", result.error.lower())
        self.manager.__aexit__.assert_awaited_once()
        self._assert_slot_released()
        await self._assert_no_pending_tasks()

    async def test_hanging_driver_start_obeys_total_deadline(self) -> None:
        self.manager.start.side_effect = self._hang

        result = await self._bounded_capture()

        self.assertIsNone(result.path)
        self.assertIn("timed out", result.error.lower())
        self.playwright.chromium.launch.assert_not_awaited()
        self.manager.__aexit__.assert_awaited_once()
        self._assert_slot_released()
        await self._assert_no_pending_tasks()

    async def test_waiting_for_browser_slot_obeys_total_deadline(self) -> None:
        self.service._browser_slots.acquire()
        try:
            result = await self._bounded_capture()
        finally:
            self.service._browser_slots.release()

        self.assertIsNone(result.path)
        self.assertIn("timed out", result.error.lower())
        self.manager.start.assert_not_awaited()
        self._assert_slot_released()
        await self._assert_no_pending_tasks()

    async def test_hanging_cdp_fallback_obeys_total_deadline(self) -> None:
        # Both native screenshot attempts fail fast so the CDP fallback runs;
        # the CDP call itself then hangs until the capture deadline.
        self.page.screenshot.side_effect = [
            RuntimeError("browser screenshot failed"),
            RuntimeError("browser screenshot retry failed"),
        ]
        self.cdp.send.side_effect = self._hang

        result = await self._bounded_capture()

        self.assertIsNone(result.path)
        self.assertIn("timed out", result.error.lower())
        self.cdp.send.assert_awaited()
        self.context.close.assert_awaited_once()
        self.browser.close.assert_awaited_once()
        self.manager.__aexit__.assert_awaited_once()
        self._assert_slot_released()
        await self._assert_no_pending_tasks()

    async def test_hanging_context_close_cannot_prevent_success_or_leak_slot(self) -> None:
        self.context.close.side_effect = self._hang

        result = await self._bounded_capture()

        self.assertEqual(result.path, self.rel_path)
        self.browser.close.assert_awaited_once()
        self.manager.__aexit__.assert_awaited_once()
        self._assert_slot_released()
        await self._assert_no_pending_tasks()

    async def test_hanging_driver_shutdown_cannot_prevent_success_or_leak_slot(self) -> None:
        self.manager.__aexit__.side_effect = self._hang

        result = await self._bounded_capture()

        self.assertEqual(result.path, self.rel_path)
        self.context.close.assert_awaited_once()
        self.browser.close.assert_awaited_once()
        self._assert_slot_released()
        await self._assert_no_pending_tasks()

    async def test_all_teardown_steps_attempted_with_no_grace_remaining(self) -> None:
        with patch("app.services.screenshots._CLEANUP_TIMEOUT_SECONDS", 0):
            await self.service._cleanup_browser(self.context, self.browser, self.manager)

        self.manager.__aexit__.assert_awaited_once()
        self.context.close.assert_awaited_once()
        self.browser.close.assert_awaited_once()
        await self._assert_no_pending_tasks()

    # -- external cancellation ----------------------------------------------

    async def test_external_cancellation_closes_resources_and_releases_slot(self) -> None:
        reached = asyncio.Event()

        async def hanging_screenshot(*args, **kwargs):  # noqa: ANN002, ANN003
            reached.set()
            await self._hang()

        self.page.screenshot.side_effect = hanging_screenshot
        self.context.close.side_effect = self._hang
        task = asyncio.create_task(self.service.capture("https://example.com", 7))
        await asyncio.wait_for(reached.wait(), timeout=_BOUNDED_TEST_TIMEOUT)
        task.cancel()

        done, _ = await asyncio.wait({task}, timeout=_BOUNDED_TEST_TIMEOUT)
        self.assertTrue(done, "Cancellation was not handled within the test bound")
        with self.assertRaises(asyncio.CancelledError):
            await task

        self.context.close.assert_awaited_once()
        self.browser.close.assert_awaited_once()
        self.manager.__aexit__.assert_awaited_once()
        self._assert_slot_released()
        await self._assert_no_pending_tasks()

    async def test_cancellation_during_browser_launch_releases_slot(self) -> None:
        reached = asyncio.Event()

        async def hanging_launch(*args, **kwargs):  # noqa: ANN002, ANN003
            reached.set()
            await self._hang()

        self.playwright.chromium.launch.side_effect = hanging_launch
        task = asyncio.create_task(self.service.capture("https://example.com", 7))
        await asyncio.wait_for(reached.wait(), timeout=_BOUNDED_TEST_TIMEOUT)
        task.cancel()

        done, _ = await asyncio.wait({task}, timeout=_BOUNDED_TEST_TIMEOUT)
        self.assertTrue(done, "Cancellation was not handled within the test bound")
        with self.assertRaises(asyncio.CancelledError):
            await task

        self.manager.__aexit__.assert_awaited_once()
        self._assert_slot_released()
        await self._assert_no_pending_tasks()


if __name__ == "__main__":
    unittest.main()
