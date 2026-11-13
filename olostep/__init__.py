# Core clients
# Error hierarchy
from . import errors
from .clients.async_client import AsyncOlostep
from .clients.sync_client import Olostep
from .config import VERSION as __version__

# Stateful result objects
from .frontend.client_state import (
    BatchItemResult,
    Crawl,
    CrawlInfo,
    CrawlPage,
    MonitorDeleteResult,
    MonitorEventResult,
    MonitorListResult,
    MonitorResult,
    ScrapeResult,
    Sitemap,
)

# Type system
from .models.common import Country
from .models.request import (
    ClickAction,
    FillInputAction,
    Format,
    LinksOnPage,
    LLMExtract,
    Parser,
    RetrieveFormat,
    ScrapeStorage,
    ScreenSize,
    ScrollAction,
    Transformer,
    WaitAction,
)

# Configuration
from .retry_strategy import RetryStrategy

# Get all error classes dynamically and expose on package for "from olostep import Olostep_BaseError"
_error_classes = [
    name for name in dir(errors) if not name.startswith("_") and name.endswith("Error")
]
for _name in _error_classes:
    globals()[_name] = getattr(errors, _name)

__all__ = [
    # Clients
    "AsyncOlostep",
    "Olostep",
    # Configuration
    "RetryStrategy",
    # Result objects
    "ScrapeResult",
    "BatchItemResult",
    "CrawlPage",
    "Crawl",
    "CrawlInfo",
    "Sitemap",
    "MonitorResult",
    "MonitorListResult",
    "MonitorEventResult",
    "MonitorDeleteResult",
    # Types
    "Format",
    "Country",
    "RetrieveFormat",
    "WaitAction",
    "ClickAction",
    "FillInputAction",
    "ScrollAction",
    "Parser",
    "LLMExtract",
    "LinksOnPage",
    "ScrapeStorage",
    "ScreenSize",
    "Transformer",
    # Error classes
    *_error_classes,
    # Version
    "__version__",
]
