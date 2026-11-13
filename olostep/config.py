from __future__ import annotations

import os
from typing import Final

# SDK version
VERSION: Final[str] = "1.2.3"

# Base API URL (can be overridden via env)
BASE_API_URL: Final[str] = os.getenv(
    "OLOSTEP_BASE_API_URL", "https://api.olostep.com/v1"
)

# User-Agent header built from version
USER_AGENT: Final[str] = f"olostep-python-sdk/{VERSION}"

API_TIMEOUT: Final[int] = int(os.getenv("OLOSTEP_API_TIMEOUT", 150))

# Environment variable names to try for API key (first hit wins)
API_KEY_ENV: Final[str] | None = os.getenv("OLOSTEP_API_KEY")

# IO logging configuration
IO_LOG_PATH: Final[str] = os.getenv("OLOSTEP_IO_LOG_PATH", ".runtime/io_logs")

SERVER_RETRIEVE_ID_RETENTION_DAYS: Final[int] = 7
