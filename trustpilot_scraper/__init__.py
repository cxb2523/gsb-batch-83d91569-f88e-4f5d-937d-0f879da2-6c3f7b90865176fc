"""trustpilot_scraper: scrape public Trustpilot reviews into plain Python dicts."""

from importlib.metadata import PackageNotFoundError, version

from .scraper import (
    TrustpilotBlockedError,
    TrustpilotCollectionResult,
    TrustpilotError,
    TrustpilotParseError,
    collect_trustpilot_reviews,
    get_reviews_from_page,
    iter_trustpilot_reviews,
    normalize_review,
    normalize_url,
    parse_next_data,
    parse_reviews_html,
    scrape_trustpilot_reviews,
)

try:
    __version__ = version("trustpilot_scraper")
except PackageNotFoundError:  # pragma: no cover - running from a source checkout
    __version__ = "1.1.0"

__all__ = [
    "TrustpilotBlockedError",
    "TrustpilotCollectionResult",
    "TrustpilotError",
    "TrustpilotParseError",
    "__version__",
    "collect_trustpilot_reviews",
    "get_reviews_from_page",
    "iter_trustpilot_reviews",
    "normalize_review",
    "normalize_url",
    "parse_next_data",
    "parse_reviews_html",
    "scrape_trustpilot_reviews",
]
