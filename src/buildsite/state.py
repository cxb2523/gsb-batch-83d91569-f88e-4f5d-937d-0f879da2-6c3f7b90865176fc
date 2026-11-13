"""Evolution state persistence, reconciliation, and schema migration for BuildSite.

Manages saving, loading, verifying, and migrating the user's property state,
ensuring non-destructive updates, duplicate run detection, and deterministic history.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from buildsite.models import ConstructionMilestone, PropertyState

logger = logging.getLogger(__name__)

DEFAULT_STATE_FILENAME = "buildsite_state.json"
CURRENT_SCHEMA_VERSION = 1


class StateError(Exception):
    """Raised when loading or writing state fails."""


def _safe_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_state(state_file_path: Path) -> Optional[PropertyState]:
    """Load and migrate existing PropertyState from disk.

    Returns None if file does not exist or cannot be parsed as a JSON object.
    """
    if not state_file_path.is_file():
        return None

    try:
        with open(state_file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        logger.warning("Could not read existing state file %s: %s", state_file_path, exc)
        return None

    if not isinstance(data, dict):
        logger.warning("Expected JSON object in state file %s, got %s", state_file_path, type(data).__name__)
        return None

    # Handle schema migration if needed
    schema_ver = _safe_int(data.get("schema_version", 1), 1)
    if schema_ver > CURRENT_SCHEMA_VERSION:
        logger.warning(
            "State file has newer schema version %d than supported %d",
            schema_ver,
            CURRENT_SCHEMA_VERSION
        )

    try:
        milestone_str = data.get("milestone", ConstructionMilestone.PLOT.value)
        milestone = ConstructionMilestone(milestone_str)
    except ValueError:
        milestone = ConstructionMilestone.PLOT

    raw_layers = data.get("active_layers", [])
    raw_unlocked = data.get("unlocked_features", [])

    return PropertyState(
        schema_version=CURRENT_SCHEMA_VERSION,
        user_id=_safe_int(data.get("user_id", 0)),
        login=str(data.get("login", "") or ""),
        seed=str(data.get("seed", "") or ""),
        total_contributions=_safe_int(data.get("total_contributions", 0)),
        active_days=_safe_int(data.get("active_days", 0)),
        milestone=milestone,
        progress_ratio=_safe_float(data.get("progress_ratio", 0.0)),
        active_layers=list(raw_layers) if isinstance(raw_layers, list) else [],
        unlocked_features=list(raw_unlocked) if isinstance(raw_unlocked, list) else [],
        variation=data.get("variation"),
        last_updated=str(data.get("last_updated", "") or ""),
        last_contribution_count=_safe_int(data.get("last_contribution_count", 0)),
        hash_signature=str(data.get("hash_signature", "") or "")
    )


def save_state(state: PropertyState, state_file_path: Path) -> None:
    """Save PropertyState to disk atomically."""
    state_file_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "schema_version": state.schema_version,
        "user_id": state.user_id,
        "login": state.login,
        "seed": state.seed,
        "total_contributions": state.total_contributions,
        "active_days": state.active_days,
        "milestone": state.milestone.value,
        "progress_ratio": state.progress_ratio,
        "active_layers": state.active_layers,
        "unlocked_features": state.unlocked_features,
        "variation": state.variation,
        "last_updated": state.last_updated,
        "last_contribution_count": state.last_contribution_count,
        "hash_signature": state.hash_signature,
    }

    # Write to temporary file then replace atomically
    tmp_path = state_file_path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
    tmp_path.replace(state_file_path)


def has_state_changed(previous_state: Optional[PropertyState], new_state: PropertyState) -> bool:
    """Check if the new state has meaningful changes requiring asset regeneration."""
    if previous_state is None:
        return True
    return previous_state.hash_signature != new_state.hash_signature
