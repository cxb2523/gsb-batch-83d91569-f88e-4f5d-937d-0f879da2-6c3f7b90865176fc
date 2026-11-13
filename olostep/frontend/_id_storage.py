from __future__ import annotations

import json
from pathlib import Path

from .client_state import RetrievableID


def _get_retrievable_ids_storage_path() -> Path:
    """Get the path to store retrievable IDs across machines."""
    # Use user's home directory with a hidden folder for cross-machine compatibility
    home = Path.home()
    storage_dir = home / ".olostep"
    storage_dir.mkdir(exist_ok=True)
    return storage_dir / "retrievable_ids.jsonl"


def _load_retrievable_ids() -> list[RetrievableID]:
    """Load retrievable IDs from local storage."""
    storage_path = _get_retrievable_ids_storage_path()
    if not storage_path.exists():
        return []

    ids = []
    try:
        with open(storage_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    data = json.loads(line)
                    ids.append(
                        RetrievableID(
                            id=data["id"],
                            type=data["type"],
                            timestamp=data["timestamp"],
                        )
                    )
    except (json.JSONDecodeError, KeyError, FileNotFoundError):
        # If file is corrupted, return empty list
        return []

    return ids


def _save_retrievable_id(retrievable_id: RetrievableID) -> None:
    """Save a retrievable ID to local storage."""
    storage_path = _get_retrievable_ids_storage_path()

    # Append to JSONL file
    with open(storage_path, "a", encoding="utf-8") as f:
        json.dump(
            {
                "id": retrievable_id.id,
                "type": retrievable_id.type,
                "timestamp": retrievable_id.timestamp,
            },
            f,
        )
        f.write("\n")


def _cleanup_expired_ids(retention_days: int = 7) -> None:
    """Remove expired IDs from local storage."""
    storage_path = _get_retrievable_ids_storage_path()
    if not storage_path.exists():
        return

    # Load all IDs
    all_ids = _load_retrievable_ids()

    # Filter out expired ones
    valid_ids = [
        retrievable_id
        for retrievable_id in all_ids
        if not retrievable_id.is_expired(retention_days)
    ]

    # Rewrite file with only valid IDs
    with open(storage_path, "w", encoding="utf-8") as f:
        for retrievable_id in valid_ids:
            json.dump(
                {
                    "id": retrievable_id.id,
                    "type": retrievable_id.type,
                    "timestamp": retrievable_id.timestamp,
                },
                f,
            )
            f.write("\n")
