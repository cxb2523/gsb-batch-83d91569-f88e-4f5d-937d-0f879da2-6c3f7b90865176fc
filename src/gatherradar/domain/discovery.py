from __future__ import annotations

from enum import StrEnum


class DiscoveryType(StrEnum):
    """What one source observation turned out to be.

    A typed vocabulary rather than free-form strings, so the classification cannot
    drift as it travels from a provider through the service into run reporting.
    `OTHER` means meaningful content was analyzed and found unrelated; content that
    was never analyzed is reported as a skipped outcome instead, not as `OTHER`.
    """

    EVENT = "event"
    PLACE = "place"
    OTHER = "other"
