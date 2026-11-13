import os
import sys
from pathlib import Path

# Make `app` package importable when running pytest from anywhere.
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Settings requires these at import time; provide harmless test defaults.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("LOG_LEVEL", "INFO")
os.environ.setdefault("MF_ENRICHMENT_ENABLED", "false")
