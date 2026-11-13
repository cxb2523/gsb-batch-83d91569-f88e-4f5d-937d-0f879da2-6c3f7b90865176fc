"""Deterministic Playwright doubles: no browser, network, timers or live session."""
from tempfile import TemporaryDirectory
from unittest import TestCase, mock

from test_media_evidence import FakeDriver, raw_item
from gatherradar.collectors.instagram_evidence import (
    PlaywrightMediaPageDriver, VisualCaptureError, capture_post_artifacts,
)
from gatherradar.storage import MediaArtifactStore


def visual(tag='IMG', source='image-a'):
    node = mock.Mock()
    node.evaluate.side_effect = lambda code: tag if code == '(el) => el.tagName' else source if 'currentSrc ||' in code else 200000
    node.bounding_box.return_value = {'x': 100, 'y': 20, 'width': 450, 'height': 600}
    return node


class CarouselRecoveryTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = MediaArtifactStore(self.temp.name, 'instagram', 'source')

    def test_transient_screenshot_failure_retries_same_slide_then_recovers(self):
        page = mock.Mock()
        node = visual()
        page.wait_for_function.return_value.as_element.return_value = node
        page.screenshot.side_effect = [TimeoutError(), b'one', b'two']
        driver = PlaywrightMediaPageDriver(page)
        with mock.patch.object(driver, 'advance_carousel', side_effect=[True, False]) as advance:
            result = capture_post_artifacts(driver, raw_item(), self.store)
        self.assertEqual([a.slide_index for a in result.artifacts], [0, 1])
        self.assertEqual(result.failures, ())
        self.assertEqual(page.screenshot.call_count, 3)
        self.assertEqual(advance.call_count, 2)

    def test_persistent_readiness_failure_retains_success_and_never_advances_again(self):
        page = mock.Mock()
        page.wait_for_function.side_effect = [mock.Mock(as_element=lambda: visual()), TimeoutError(), TimeoutError(), TimeoutError()]
        page.screenshot.return_value = b'one'
        driver = PlaywrightMediaPageDriver(page)
        with mock.patch.object(driver, 'advance_carousel', return_value=True) as advance:
            result = capture_post_artifacts(driver, raw_item(), self.store)
        self.assertEqual([a.slide_index for a in result.artifacts], [0])
        advance.assert_called_once()
        failure = result.failures[0]
        self.assertEqual((failure.source_id, failure.raw_item_id, failure.slide_index, failure.retry_count),
                         ('source', raw_item().id, 1, 2))
        self.assertEqual(failure.category, 'visual_readiness_TimeoutError')
        self.assertIn('remaining slides unconfirmed', failure.report())

    def test_changing_source_during_screenshot_is_discarded_then_recaptured(self):
        page = mock.Mock()
        changing, stable = visual(), visual(source='final')
        changing.evaluate.side_effect = ['old-src', 'IMG', 200000, 'changed-src']
        page.wait_for_function.side_effect = [mock.Mock(as_element=lambda: changing), mock.Mock(as_element=lambda: stable)]
        page.screenshot.side_effect = [b'wrong', b'correct']
        driver = PlaywrightMediaPageDriver(page)
        with mock.patch.object(driver, 'advance_carousel', return_value=False):
            result = capture_post_artifacts(driver, raw_item(), self.store)
        self.assertEqual(len(result.artifacts), 1)
        self.assertEqual(result.artifacts[0].local_path.read_bytes(), b'correct')
        from pathlib import Path
        self.assertEqual(len(list(Path(self.temp.name).rglob('*.png'))), 1)

    def test_duplicate_images_are_accounted_for_without_duplicate_artifacts(self):
        driver = FakeDriver([b'one', b'one', b'three'])
        result = capture_post_artifacts(driver, raw_item(), self.store)
        self.assertEqual(len(result.artifacts), 1)
        self.assertEqual(driver.index, 1)
        self.assertEqual((result.failures[0].category, result.failures[0].retry_count), ('duplicate_visual', 2))

    def test_partial_recovery_keeps_prior_captures_across_runs_without_new_files(self):
        first = capture_post_artifacts(FakeDriver([b'one', b'two'], fail_at={1}), raw_item(), self.store)
        second = capture_post_artifacts(FakeDriver([b'one', b'two']), raw_item(), self.store)
        self.assertEqual(first.artifacts[0], second.artifacts[0])
        self.assertEqual([a.slide_index for a in second.artifacts], [0, 1])
        self.assertEqual(second.failures, ())

    def test_navigation_requires_new_identity_and_no_fixed_sleep(self):
        page = mock.Mock()
        node = visual()
        page.wait_for_function.return_value.as_element.return_value = node
        page.screenshot.return_value = b'one'
        page.locator.return_value.count.return_value = 1
        driver = PlaywrightMediaPageDriver(page)
        driver.capture_current_visual()
        self.assertTrue(driver.advance_carousel())
        page.wait_for_function.side_effect = TimeoutError()
        with self.assertRaises(VisualCaptureError):
            driver.capture_current_visual()
        args = page.wait_for_function.call_args.kwargs['arg']
        self.assertIs(args['previous'], node)
        self.assertEqual(args['source'], 'image-a')
        self.assertTrue(args['advanced'])
        page.wait_for_timeout.assert_not_called()
        self.assertEqual(page.screenshot.call_count, 1)

    def test_mixed_carousel_video_is_paused_and_seeked_before_capture(self):
        page = mock.Mock()
        page.wait_for_function.return_value.as_element.return_value = visual('VIDEO', 'video-b')
        page.screenshot.return_value = b'video frame zero'
        driver = PlaywrightMediaPageDriver(page)
        calls = []
        with mock.patch.object(driver, '_seek_video', side_effect=lambda *a: calls.append('seek_zero')) as seek:
            page.screenshot.side_effect = lambda **k: (calls.append('capture') or b'video frame zero')
            self.assertEqual(driver.capture_current_visual(), b'video frame zero')
        self.assertEqual(calls, ['seek_zero', 'capture'])
        self.assertEqual(seek.call_args.args[1], 0)

    def test_navigation_failure_keeps_capture_but_never_guesses_next_index(self):
        driver = FakeDriver([b'one', b'two'])
        with mock.patch.object(driver, 'advance_carousel', side_effect=TimeoutError()) as advance:
            result = capture_post_artifacts(driver, raw_item('carousel'), self.store)
        self.assertEqual([a.slide_index for a in result.artifacts], [0])
        self.assertEqual(result.failures[0].category, 'navigation_failed')
        advance.assert_called_once()
