"""Verifiable outcome records for resumable RAW downloads.

The report produced here lets collection scripts explain, after an interrupted
run, whether a file was downloaded from scratch, resumed from a persisted
checkpoint, or had its old progress discarded.  Reports are attached to the
:class:`~base_api.modules.config.DownloadConfigRAW` instance, so the boolean
return value of ``download_raw`` keeps its existing meaning.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


class RawOutcome:
    """String constants for the terminal classification of a RAW download."""

    FRESH = "fresh"
    """No usable checkpoint existed; the transfer started from byte zero."""

    RESUMED = "resumed"
    """A valid checkpoint was loaded and the saved byte ranges were reused."""

    VALIDATOR_MISMATCH = "validator_mismatch"
    """A saved ETag/Last-Modified no longer matches; old progress was dropped."""

    RANGE_IGNORED = "range_ignored"
    """Linear mode requested a Range but the server answered 200, so it restarted."""

    CANCELLED = "cancelled"
    """The stop signal fired; :class:`DownloadCancelled` was raised."""

    INCOMPLETE = "incomplete"
    """A byte range/stream ended before every requested byte was received."""

    METADATA_FAILED = "metadata_failed"
    """HEAD (metadata) failed while a checkpoint existed; no fallback was attempted."""

    FAILURE_OUTCOMES = frozenset({INCOMPLETE, METADATA_FAILED})
    """Outcomes that represent a failed rather than completed transfer."""


@dataclass
class RawDownloadConclusion:
    """Auditable conclusion describing what happened during one RAW download.

    The same instance is attached to the configuration for every exit path of
    ``download_raw`` (normal return and raised exception alike).
    """

    output_path: str
    """Resolved path of the file being downloaded."""

    mode: str | None = None
    """Final transfer mode: ``"multipart"`` or ``"linear"`` (``None`` if undecided)."""

    reused_progress: bool = False
    """Whether persisted checkpoint progress was actually reused."""

    retained_bytes: int = 0
    """Bytes already kept from a previous run *before* this run transferred anything."""

    total_bytes: int = 0
    """Total expected size in bytes (0 when the server did not report one)."""

    outcome: str = RawOutcome.FRESH
    """Terminal classification, one of the :class:`RawOutcome` constants."""

    error: str | None = None
    """String form of the exception that terminated the run, if any."""

    def mark(self, outcome: str, **changes: Any) -> None:
        """Set the outcome, optionally updating other fields in one call."""
        self.outcome = outcome
        for name, value in changes.items():
            setattr(self, name, value)

    @property
    def failed(self) -> bool:
        """True when the outcome represents a failed (non-cancelled) transfer."""
        return self.outcome in RawOutcome.FAILURE_OUTCOMES

    def as_dict(self) -> dict[str, Any]:
        """Plain mapping suitable for logs or serialized reports."""
        return {
            "output_path": self.output_path,
            "mode": self.mode,
            "reused_progress": self.reused_progress,
            "retained_bytes": self.retained_bytes,
            "total_bytes": self.total_bytes,
            "outcome": self.outcome,
            "error": self.error,
        }

    def __str__(self) -> str:
        return (
            f"RAW conclusion outcome={self.outcome} mode={self.mode} "
            f"reused_progress={self.reused_progress} retained_bytes={self.retained_bytes} "
            f"total_bytes={self.total_bytes} output={self.output_path}"
        )


def make_conclusion(output: str | Path) -> RawDownloadConclusion:
    """Create a fresh conclusion for *output*."""
    return RawDownloadConclusion(output_path=str(Path(output).resolve()))
