"""Verify all public exports can be imported from olostep."""

from __future__ import annotations

import pytest


def test_all_exports_importable() -> None:
    """Every name in __all__ must be importable from olostep."""
    import olostep

    for name in olostep.__all__:
        assert hasattr(olostep, name), f"olostep.{name} missing"


def test_doc_imports_sync_client() -> None:
    """Docs: from olostep import Olostep."""
    from olostep import Olostep

    assert Olostep is not None


def test_doc_imports_async_client() -> None:
    """Docs: from olostep import AsyncOlostep."""
    from olostep import AsyncOlostep

    assert AsyncOlostep is not None


def test_doc_imports_base_error() -> None:
    """Docs: from olostep import Olostep_BaseError."""
    from olostep import Olostep_BaseError

    assert Olostep_BaseError is not None
    assert issubclass(Olostep_BaseError, Exception)


def test_doc_imports_combined() -> None:
    """Docs example: from olostep import Olostep, Olostep_BaseError."""
    from olostep import Olostep, Olostep_BaseError

    assert Olostep is not None
    assert Olostep_BaseError is not None
