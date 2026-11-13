"""Verify invalid API key raises OlostepServerError_AuthFailed (not BlacklistedDomain).

TODO: This is not really a self-test (hits real API); move to integration/contract tests
      and align with auth-related tests below once 401→AuthFailed vs BlacklistedDomain is fixed.

Auth-related tests (extracted for TDD):
--------------------------------------
tests/api_contracts/as_is/test_general_endpoint_contracts.py::TestErrorDetection::test_real_api_key_authentication_succeeds
tests/api_contracts/as_is/test_general_endpoint_contracts.py::TestErrorDetection::test_fake_api_key_authentication_fails
tests/api_contracts/as_is/test_general_endpoint_contracts.py::TestErrorDetection::test_fake_endpoint_with_fake_key_raises_invalid_endpoint_error
tests/api_contracts/as_is/test_general_endpoint_contracts.py::TestErrorDetection::test_type_confusion_with_fake_key_raises_authentication_error
tests/api_contracts/as_is/test_general_endpoint_contracts.py::TestErrorDetection::test_api_validates_path_before_params_before_auth
tests/self_tests/test_invalid_key_raises_auth_failed.py::test_invalid_api_key_raises_auth_failed
tests/self_tests/test_invalid_key_raises_auth_failed.py::test_invalid_key_exception_is_base_error
tests/unit/backend/test_transport.py::TestHttpxTransportBasicFunctionality::test_authorization_header_set_correctly  (unit; header shape only)

Run (caller reverted: 401 -> BlacklistedDomain only):
  pytest ... (above 8 tests) -> 4 passed, 4 failed.
  PASSED: test_real_api_key_authentication_succeeds, test_fake_endpoint_with_fake_key_raises_invalid_endpoint_error,
         test_invalid_key_exception_is_base_error (raises BaseError subclass), test_authorization_header_set_correctly.
  FAILED: test_fake_api_key_authentication_fails, test_type_confusion_with_fake_key_raises_authentication_error,
         test_invalid_api_key_raises_auth_failed -> expect AuthFailed, got BlacklistedDomain (same 401, wrong mapping).
  FAILED: test_api_validates_path_before_params_before_auth -> API returned 500 for missing required param (not 401);
         test expects AuthFailed for fake_key + missing_required_body; may need to accept 500 or skip when API misbehaves.
"""

from __future__ import annotations

import pytest

from olostep import Olostep, Olostep_BaseError
from olostep.errors import OlostepServerError_AuthFailed


@pytest.mark.api
def test_invalid_api_key_raises_auth_failed() -> None:
    """SDK must raise AuthFailed for invalid key; 401 with invalid_api_key is auth, not blacklist."""
    client = Olostep(api_key="invalid_key_12345")
    with pytest.raises(OlostepServerError_AuthFailed) as exc_info:
        client.scrapes.create(url_to_scrape="https://example.com", formats=["markdown"])
    assert "invalid" in str(exc_info.value).lower() or "rejected" in str(exc_info.value).lower()


@pytest.mark.api
def test_invalid_key_exception_is_base_error() -> None:
    """AuthFailed is a subclass of Olostep_BaseError so 'except Olostep_BaseError' catches it."""
    client = Olostep(api_key="invalid_key_12345")
    with pytest.raises(Olostep_BaseError):
        client.scrapes.create(url_to_scrape="https://example.com", formats=["markdown"])
