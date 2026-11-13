import tempfile
import unittest
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock
from types import SimpleNamespace

from gatherradar.collectors.instagram_evidence import (
    InstagramMediaEvidenceAcquirer, MediaCaptureResult, PlaywrightMediaPageDriver,
    capture_post_artifacts, capture_reel_artifacts, sample_reel_timestamps,
)
from gatherradar.collectors.instagram_browser import CHECKPOINT_MESSAGE, InstagramCheckpointError
from gatherradar.orchestration.collection_run import find_source
from gatherradar.domain import MediaKind, RawItem, SourceType
from gatherradar.storage import MediaArtifactStore


def raw_item(content_type='image'):
    return RawItem(
        id='instagram:source:ABC', source_id='source',
        source_type=SourceType.INSTAGRAM, external_id='ABC',
        content_type=content_type, content_url='https://www.instagram.com/p/ABC/',
        raw_text='', captured_at=datetime(2026, 9, 21, tzinfo=timezone.utc),
        content_hash='a' * 64,
    )


class FakeDriver:
    def __init__(self, visuals=(), duration=5000, fail_at=()):
        self.visuals = list(visuals)
        self.index = 0
        self.duration = duration
        self.fail_at = set(fail_at)
        self.frame_calls = []

    def capture_current_visual(self):
        if self.index in self.fail_at:
            raise ValueError('broken slide')
        return self.visuals[self.index]

    def advance_carousel(self):
        if self.index + 1 >= len(self.visuals):
            return False
        self.index += 1
        return True

    def has_next_carousel(self):
        return self.index + 1 < len(self.visuals)

    def video_duration_ms(self):
        return self.duration

    def capture_frame(self, timestamp):
        self.frame_calls.append(timestamp)
        if timestamp in self.fail_at:
            raise ValueError('broken frame')
        return self.visuals[timestamp % len(self.visuals)]


class MediaStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = MediaArtifactStore(self.temp.name, 'instagram', 'source')

    def test_paths_are_deterministic_and_below_data_root(self):
        first = self.store.write(raw_item(), MediaKind.IMAGE, b'image')
        second = self.store.write(raw_item(), MediaKind.IMAGE, b'image')
        self.assertEqual(first.artifact.local_path, second.artifact.local_path)
        self.assertTrue(first.artifact.local_path.is_relative_to(Path(self.temp.name)))
        self.assertTrue(first.created)
        self.assertFalse(second.created)

    def test_hash_is_sha256_and_part_of_identity(self):
        one = self.store.write(raw_item(), MediaKind.IMAGE, b'one').artifact
        two = self.store.write(raw_item(), MediaKind.IMAGE, b'two').artifact
        self.assertEqual(len(one.asset_hash), 64)
        self.assertNotEqual(one.artifact_id, two.artifact_id)
        self.assertNotEqual(one.local_path, two.local_path)

    def test_position_is_part_of_carousel_path_and_identity(self):
        one = self.store.write(
            raw_item(), MediaKind.CAROUSEL_SLIDE, b'same', slide_index=0
        ).artifact
        two = self.store.write(
            raw_item(), MediaKind.CAROUSEL_SLIDE, b'same', slide_index=1
        ).artifact
        self.assertNotEqual(one.artifact_id, two.artifact_id)
        self.assertIn('slide-000', one.local_path.name)


class CarouselCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = MediaArtifactStore(self.temp.name, 'instagram', 'source')

    def test_one_visual_is_an_image(self):
        result = capture_post_artifacts(FakeDriver([b'one']), raw_item(), self.store)
        self.assertEqual([item.kind for item in result.artifacts], [MediaKind.IMAGE])

    def test_carousel_preserves_slide_order(self):
        result = capture_post_artifacts(
            FakeDriver([b'one', b'two', b'three']), raw_item(), self.store
        )
        self.assertEqual([item.slide_index for item in result.artifacts], [0, 1, 2])

    def test_maximum_slide_bound_is_enforced(self):
        result = capture_post_artifacts(
            FakeDriver([b'one', b'two', b'three']), raw_item(), self.store,
            max_slides=2,
        )
        self.assertEqual(len(result.artifacts), 2)
        self.assertEqual(result.failures[0].category, 'slide_limit')
        self.assertEqual(result.failures[0].slide_index, 2)

    def test_duplicate_visual_stops_the_carousel(self):
        result = capture_post_artifacts(
            FakeDriver([b'one', b'two', b'two', b'three']), raw_item(), self.store
        )
        self.assertEqual([item.slide_index for item in result.artifacts], [0, 1])

    def test_one_slide_failure_is_isolated(self):
        result = capture_post_artifacts(
            FakeDriver([b'one', b'two', b'three'], fail_at={1}), raw_item(), self.store
        )
        self.assertEqual([item.slide_index for item in result.artifacts], [0])
        self.assertEqual(len(result.failures), 1)
        self.assertEqual(result.failures[0].retry_count, 2)
        self.assertEqual(result.failures[0].slide_index, 1)

    def test_capture_errors_do_not_echo_browser_details(self):
        driver = FakeDriver([b'one'])
        with mock.patch.object(
            driver, 'capture_current_visual',
            side_effect=RuntimeError('synthetic-session-detail'),
        ):
            result = capture_post_artifacts(driver, raw_item(), self.store)
        self.assertEqual(len(result.failures), 1)
        self.assertIn('visual capture failed', result.failures[0].reason)
        self.assertNotIn('synthetic-session-detail', result.failures[0].reason)


class ReelCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = MediaArtifactStore(self.temp.name, 'instagram', 'source')

    def test_timestamps_are_deterministic_and_bounded(self):
        timestamps = sample_reel_timestamps(10_000, 4)
        self.assertEqual(timestamps, sample_reel_timestamps(10_000, 4))
        self.assertEqual(len(timestamps), 4)
        self.assertEqual(timestamps[0], 0)
        self.assertLess(timestamps[-1], 10_000)

    def test_missing_video_duration_is_reported(self):
        result = capture_reel_artifacts(
            FakeDriver([b'frame'], duration=None), raw_item('reel'), self.store
        )
        self.assertEqual(result.artifacts, ())
        self.assertIn('duration', result.failures[0].reason)

    def test_duplicate_frames_are_skipped(self):
        driver = FakeDriver([b'same'], duration=5000)
        result = capture_reel_artifacts(driver, raw_item('reel'), self.store, max_frames=4)
        self.assertEqual(len(result.artifacts), 1)
        self.assertLessEqual(len(driver.frame_calls), 4)

    def test_one_frame_failure_does_not_discard_other_frames(self):
        timestamps = sample_reel_timestamps(5000, 3)
        driver = FakeDriver([b'a', b'b', b'c'], duration=5000, fail_at={timestamps[1]})
        result = capture_reel_artifacts(driver, raw_item('reel'), self.store, max_frames=3)
        self.assertGreaterEqual(len(result.artifacts), 1)
        self.assertEqual(len(result.failures), 1)


class AcquirerFailureTests(unittest.TestCase):
    def test_checkpoint_stops_navigation_and_keeps_prior_artifacts(self):
        with tempfile.TemporaryDirectory() as folder:
            store = MediaArtifactStore(folder, 'instagram', 'source')
            first = raw_item()
            items = (first, replace(first, id='second'), replace(first, id='third'))
            artifact = store.write(first, MediaKind.IMAGE, b'image').artifact
            page = SimpleNamespace(url=first.content_url)

            @contextmanager
            def browser(*args):
                yield SimpleNamespace(page=page, context=object())

            module = 'gatherradar.collectors.instagram_evidence.'
            source = find_source('davvvat_instagram', Path(__file__).resolve().parents[1] / 'config/sources.yaml')
            with (
                mock.patch(module + 'open_authenticated_browser', browser),
                mock.patch(module + '_goto') as navigate,
                mock.patch(module + '_ensure_location_allowed', side_effect=[
                    None, InstagramCheckpointError(CHECKPOINT_MESSAGE),
                ]),
                mock.patch(module + 'has_instagram_session_cookie', return_value=True),
                mock.patch(module + '_wait_for_optional'),
                mock.patch(module + 'capture_post_artifacts', return_value=MediaCaptureResult((artifact,))),
            ):
                result = InstagramMediaEvidenceAcquirer(data_dir=folder).acquire(items, source, store)
            self.assertEqual(navigate.call_count, 2)
            self.assertEqual(result.artifacts, (artifact,))
            self.assertEqual(result.failures[0].reason, CHECKPOINT_MESSAGE)


class MediaPageDriverTests(unittest.TestCase):
    def test_main_layout_selects_rendered_slide_not_clipped_or_unrelated_images(self):
        active, clipped, avatar, thumbnail = (mock.Mock() for _ in range(4))
        for image, area in ((active, 200000), (clipped, 0), (avatar, 0), (thumbnail, 0)):
            image.is_visible.return_value = True
            image.evaluate.return_value = area
        active.bounding_box.return_value = {'x': 222.9, 'y': 29.6, 'width': 483.1875, 'height': 599.95}
        page = mock.Mock()
        page.screenshot.return_value = b'active slide'
        page.wait_for_function.return_value.as_element.return_value = active
        active.evaluate.side_effect = lambda script: ('IMG' if script == '(el) => el.tagName'
            else 'source-a' if 'currentSrc ||' in script else 200000)
        self.assertEqual(PlaywrightMediaPageDriver(page).capture_current_visual(), b'active slide')
        args = page.wait_for_function.call_args.kwargs['arg']
        self.assertIn('main video', args['selector'])
        self.assertIn('box.width * .98', page.wait_for_function.call_args.args[0])
        active.wait_for_element_state.assert_called_once_with('stable', timeout=5000)
        active.scroll_into_view_if_needed.assert_not_called()
        page.screenshot.assert_called_once_with(
            type='png', timeout=5000, clip={'x': 223, 'y': 30, 'width': 483, 'height': 599}
        )
        for image in (clipped, avatar, thumbnail):
            image.screenshot.assert_not_called()

    def test_main_carousel_next_control_is_supported(self):
        page = mock.Mock()
        page.locator.return_value.count.return_value = 1
        control = page.locator.return_value.nth.return_value
        control.is_visible.return_value = control.is_enabled.return_value = True
        self.assertTrue(PlaywrightMediaPageDriver(page).advance_carousel())
        self.assertIn('main button[aria-label=Next]', page.locator.call_args.args[0])
        control.click.assert_called_once()

    def test_frame_capture_pauses_before_seeking_and_screenshot(self):
        calls = []

        class Video:
            def evaluate(self, script, *args):
                if args:
                    self_test.assertEqual(calls, ['pause'])
                    self_test.assertEqual(args, (1.5,))
                    calls.append('seek')
                else:
                    self_test.assertIn('pause()', script)
                    calls.append('pause')

            def screenshot(self, **kwargs):
                self_test.assertEqual(calls, ['pause', 'seek'])
                return b'paused frame'

        self_test = self
        driver = PlaywrightMediaPageDriver(None)
        with mock.patch.object(driver, '_video', return_value=Video()):
            self.assertEqual(driver.capture_frame(1500), b'paused frame')

    def test_failed_seek_never_captures_a_mislabeled_frame(self):
        video = mock.Mock()
        video.evaluate.side_effect = [None, RuntimeError('seek timed out')]
        driver = PlaywrightMediaPageDriver(None)
        with mock.patch.object(driver, '_video', return_value=video):
            with self.assertRaises(RuntimeError):
                driver.capture_frame(1500)
        video.screenshot.assert_not_called()

    def test_unloaded_or_nonfinite_duration_is_unavailable(self):
        driver = PlaywrightMediaPageDriver(None)
        video = mock.Mock()
        with mock.patch.object(driver, '_video', return_value=video):
            for duration in (None, float('nan'), float('inf'), 0):
                video.evaluate.return_value = duration
                self.assertIsNone(driver.video_duration_ms())


if __name__ == '__main__':
    unittest.main()
