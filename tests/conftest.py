import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def status_json():
    return json.loads((FIXTURES / "status.json").read_text())
