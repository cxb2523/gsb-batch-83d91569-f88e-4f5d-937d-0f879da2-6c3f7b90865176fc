import json
import unittest
from datetime import datetime
from pathlib import Path

from gatherradar.domain import RawItem, SourceType


FIXTURES = Path(__file__).parent / "fixtures"


class FixtureTests(unittest.TestCase):
    def test_raw_item_fixtures_match_contract(self) -> None:
        for fixture_path in FIXTURES.glob("*.json"):
            payload = json.loads(fixture_path.read_text(encoding="utf-8"))
            item = RawItem(
                id=payload["id"],
                source_id=payload["source_id"],
                source_type=SourceType(payload["source_type"]),
                external_id=payload["external_id"],
                content_type=payload["content_type"],
                content_url=payload["content_url"],
                raw_text=payload["raw_text"],
                captured_at=datetime.fromisoformat(payload["captured_at"]),
                published_at=(
                    datetime.fromisoformat(payload["published_at"])
                    if payload.get("published_at")
                    else None
                ),
                author=payload.get("author"),
            )
            self.assertEqual(item.id, payload["id"])


if __name__ == "__main__":
    unittest.main()
