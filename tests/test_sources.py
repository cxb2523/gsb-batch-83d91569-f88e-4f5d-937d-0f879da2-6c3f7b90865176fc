import os

# The suite never reads the owner's local registry overlay (config/sources.local.json);
# tests that need an overlay point GATHERRADAR_SOURCE_OVERLAY at a temporary file.
os.environ.setdefault('GATHERRADAR_SOURCE_OVERLAY', 'none')

import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from gatherradar.config import load_sources
from gatherradar.domain import SourceType


ROOT = Path(__file__).resolve().parents[1]


class SourceConfigTests(unittest.TestCase):
    def test_evenza_uses_generic_collection_and_publisher_coverage(self):
        from unittest.mock import Mock
        from types import SimpleNamespace
        from gatherradar.acquisition.strategies import InstagramProfileStrategy
        from gatherradar.acquisition.coverage import publisher_coverage
        from gatherradar.orchestration.collection_run import find_source, instagram_output_path
        from gatherradar.collectors.instagram import map_post_to_raw_item
        from test_instagram_collector import make_post, CAPTURED_AT
        config = ROOT / 'config/sources.yaml'
        source = find_source('evenza_platform_instagram', config)
        self.assertTrue(source.enabled)
        self.assertEqual(source.publisher_key, 'evenza_platform')
        self.assertEqual(source.username, 'evenza.platform')
        self.assertEqual(source.url, 'https://www.instagram.com/evenza.platform/')
        self.assertEqual(instagram_output_path(source, 'data').name, 'evenza.platform.jsonl')
        item = map_post_to_raw_item(make_post(shortcode='EVENZA'), source, CAPTURED_AT)
        self.assertEqual(item.content_url, 'https://www.instagram.com/p/EVENZA/')
        self.assertFalse(urlparse(item.content_url).query)
        collect = Mock(return_value=SimpleNamespace(observed_items=(item,), failed=0,
                                                    new=1, changed=0, already_existing=0))
        result = InstagramProfileStrategy(collect).acquire(source, config_path=config, data_dir='data', limit=5)
        collect.assert_called_once_with(source.id, config_path=config, data_dir='data', limit=5)
        coverage = publisher_coverage((result,))[0]
        self.assertEqual(coverage.publisher_key, 'evenza_platform')
        self.assertTrue(coverage.covered)
        self.assertEqual(coverage.covered_by, (source.id,))

    def test_initial_registry_loads_all_sources(self) -> None:
        sources = load_sources(ROOT / "config" / "sources.yaml")
        self.assertEqual(len(sources), 10)
        self.assertEqual(len({source.id for source in sources}), 10)

    def test_instagram_urls_are_canonical_and_have_usernames(self) -> None:
        sources = load_sources(ROOT / "config" / "sources.yaml")
        instagram_sources = [s for s in sources if s.source_type is SourceType.INSTAGRAM]
        self.assertEqual(len(instagram_sources), 6)
        for source in instagram_sources:
            self.assertIsNotNone(source.username)
            self.assertNotIn("igsi", source.url)
            self.assertFalse(urlparse(source.url).query)

    def test_tracking_parameters_are_not_committed(self) -> None:
        sources = load_sources(ROOT / "config" / "sources.yaml")
        for source in sources:
            query = parse_qs(urlparse(source.url).query)
            self.assertNotIn("utm_source", query)
            self.assertNotIn("utm_medium", query)
            self.assertNotIn("fbclid", query)


if __name__ == "__main__":
    unittest.main()
