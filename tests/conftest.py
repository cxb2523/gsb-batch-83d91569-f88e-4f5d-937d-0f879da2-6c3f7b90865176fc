"""Make the repository root importable for the engine modules.

The project is a flat collection of standalone scripts (see pyproject.toml),
so the tests import them by name from the repo root rather than as a package.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
