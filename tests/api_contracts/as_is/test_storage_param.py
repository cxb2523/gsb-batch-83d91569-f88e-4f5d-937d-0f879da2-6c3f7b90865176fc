"""
Storage parameter contract tests.

Validates that the storage parameter is accepted on scrape requests and
that storage is parsed correctly from scrape responses.
"""

from __future__ import annotations

import pytest

from olostep.models.request import ScrapeStorage, ScrapeUrlBodyParams
from olostep.models.response import CreateScrapeResponse, ScrapeStorageResponse


class TestScrapeStorageModel:
    """Validate the ScrapeStorage request model."""

    def test_valid_expires_in_7d(self):
        s = ScrapeStorage(expires_in="7d")
        assert s.expires_in == "7d"

    def test_valid_expires_in_never(self):
        s = ScrapeStorage(expires_in="never")
        assert s.expires_in == "never"

    @pytest.mark.parametrize("value", ["7d", "10d", "30d", "60d", "90d", "180d", "365d", "never"])
    def test_all_allowed_values(self, value: str):
        s = ScrapeStorage(expires_in=value)
        assert s.expires_in == value

    def test_invalid_expires_in_raises(self):
        with pytest.raises(Exception):
            ScrapeStorage(expires_in="3d")

    def test_invalid_expires_in_int_raises(self):
        with pytest.raises(Exception):
            ScrapeStorage(expires_in="1y")


class TestScrapeUrlBodyParamsStorage:
    """Validate storage field on ScrapeUrlBodyParams."""

    def test_storage_defaults_to_none(self):
        params = ScrapeUrlBodyParams(url_to_scrape="https://example.com")  # type: ignore[call-arg]
        assert params.storage is None

    def test_body_params_storage_present(self):
        from olostep.models.request import ScrapeUrlBodyParams

        body = ScrapeUrlBodyParams(url_to_scrape="https://example.com")  # type: ignore[call-arg]
        assert body.storage is None

    def test_body_params_storage_set(self):
        body = ScrapeUrlBodyParams(  # type: ignore[call-arg]
            url_to_scrape="https://example.com",
            storage=ScrapeStorage(expires_in="30d"),
        )
        assert body.storage is not None
        assert body.storage.expires_in == "30d"

    def test_storage_included_in_model_dump(self):
        body = ScrapeUrlBodyParams(  # type: ignore[call-arg]
            url_to_scrape="https://example.com",
            storage=ScrapeStorage(expires_in="never"),
        )
        dumped = body.model_dump(exclude_none=True)
        assert "storage" in dumped
        assert dumped["storage"]["expires_in"] == "never"

    def test_storage_excluded_from_dump_when_none(self):
        body = ScrapeUrlBodyParams(url_to_scrape="https://example.com")  # type: ignore[call-arg]
        dumped = body.model_dump(exclude_none=True)
        assert "storage" not in dumped


class TestScrapeStorageResponse:
    """Validate storage field on scrape response models."""

    BASE_RESPONSE = {
        "id": "scrape_abc123",
        "object": "scrape",
        "created": 1760327323,
        "retrieve_id": "abc123",
        "url": "https://example.com",
        "result": {},
        "credits_consumed": 1,
    }

    def test_response_without_storage_field(self):
        r = CreateScrapeResponse.model_validate(self.BASE_RESPONSE)
        assert r.storage is None

    def test_response_with_storage_7d(self):
        r = CreateScrapeResponse.model_validate({
            **self.BASE_RESPONSE,
            "storage": {"expires_in": "7d"},
        })
        assert r.storage is not None
        assert r.storage.expires_in == "7d"

    def test_response_with_storage_never(self):
        r = CreateScrapeResponse.model_validate({
            **self.BASE_RESPONSE,
            "storage": {"expires_in": "never"},
        })
        assert r.storage is not None
        assert r.storage.expires_in == "never"

    def test_storage_response_default(self):
        s = ScrapeStorageResponse()
        assert s.expires_in == "7d"


class TestScrapeStorageExport:
    """Verify ScrapeStorage is exported from the package root."""

    def test_importable_from_root(self):
        from olostep import ScrapeStorage as SS  # noqa: F401
        assert SS is ScrapeStorage
