from __future__ import annotations

from typing import Protocol

from .models import DiscoveryFacts, ExtractionInput


class ExtractionError(Exception):
    """Base class for failures at the discovery provider boundary."""


class ProviderExtractionError(ExtractionError):
    """The provider could not produce a result, e.g. it was unavailable or refused.

    Provider adapters translate their own library and transport errors into this type
    so they never leak into the rest of GatherRadar. Messages must not contain secrets.
    """


class InvalidExtractionOutputError(ExtractionError):
    """The provider's output violates the DiscoveryFacts contract."""


class DiscoveryProvider(Protocol):
    """Semantic interpretation of one source observation in a single operation.

    `discover` decides what the input is — an event, a place, or neither — and
    returns the source-supported facts together. The interface is deliberately
    neutral about how that decision is reached: the shipped implementation is a
    deterministic, free rule engine, and any future implementation must satisfy the
    same contract. Implementations raise only ProviderExtractionError or
    InvalidExtractionOutputError. `name` identifies the provider for run reporting;
    it never affects candidate identity.
    """

    name: str

    def discover(self, extraction_input: ExtractionInput) -> DiscoveryFacts: ...
