"""Per-segment accounting for the main-content extraction pipeline.

The simplified HTML handed to the model is a list of segments, each carrying
an ``_item_id``. The model is supposed to return a label for every one of
them, but real responses can omit ids, invent ids that were never in the
simplified HTML, or be unparseable altogether. Historically the first two
cases were silent (missing segments were just dropped) and the last one
aborted the whole page. :func:`build_audit` makes all of that observable.
"""

from typing import Dict, List, Optional

from mineru_html.base import (MinerUHTMLAudit, MinerUHTMLCase,
                              MinerUHTMLItemRecord)
from mineru_html.constants import ItemDisposition, TagType, normalize_tag_label
from mineru_html.utils import get_segment_ids


def get_invalid_item_ids(
    item_label: Optional[Dict[str, str]], segment_ids: List[str]
) -> List[str]:
    """Return model-returned item ids that do not exist in the simplified HTML.

    Args:
        item_label: Parsed mapping of item_id -> raw label from the model.
        segment_ids: Item ids actually present in the simplified HTML.

    Returns:
        Invalid item ids, in the order they appear in the model response.
    """
    if not item_label:
        return []
    segment_id_set = set(segment_ids)
    invalid_ids = []
    for raw_item_id in item_label:
        item_id = str(raw_item_id).strip()
        if item_id not in segment_id_set and item_id not in invalid_ids:
            invalid_ids.append(item_id)
    return invalid_ids


def build_audit(
    input_case: MinerUHTMLCase, fallback_used: Optional[str] = None
) -> MinerUHTMLAudit:
    """Build the per-segment account for one extraction case.

    Each segment of the simplified HTML gets exactly one record. A segment is:

    * ``kept`` when the model labeled it ``main``,
    * ``removed_other`` when the model explicitly labeled it ``other``,
    * ``missing`` when the model gave no usable label for it — either because
      the id was absent from the response or because the response could not be
      parsed at all.

    Explicitly labeled ``other`` and unlabeled segments are kept apart on
    purpose; only the latter indicate information lost to an incomplete model
    response.

    Args:
        input_case: Case to describe, after extraction (and fallback) ran.
        fallback_used: Name of the fallback handler that produced the output,
            if any.

    Returns:
        The audit object for the case.
    """
    audit = MinerUHTMLAudit(
        parse_failed=input_case.is_parse_failure(),
        fallback_used=fallback_used,
    )

    segment_ids = (
        get_segment_ids(input_case.process_data.simpled_html)
        if input_case.process_data is not None
        else []
    )
    item_label = (
        input_case.parse_result.item_label
        if input_case.parse_result is not None
        else None
    )
    audit.invalid_item_ids = get_invalid_item_ids(item_label, segment_ids)

    segment_id_set = set(segment_ids)
    normalized_labels: Dict[str, Optional[str]] = {}
    if item_label:
        for raw_item_id, raw_label in item_label.items():
            item_id = str(raw_item_id).strip()
            # Only labels of real segments matter here; invalid ids are
            # reported separately above.
            if item_id in segment_id_set:
                normalized_labels[item_id] = normalize_tag_label(raw_label)

    records: List[MinerUHTMLItemRecord] = []
    for item_id in segment_ids:
        label = normalized_labels.get(item_id)
        if label == TagType.Main.value:
            disposition = ItemDisposition.Kept
        elif label == TagType.Other.value:
            disposition = ItemDisposition.RemovedOther
        else:
            label = None
            disposition = ItemDisposition.Missing
        records.append(
            MinerUHTMLItemRecord(
                item_id=item_id, label=label, disposition=disposition
            )
        )
    audit.items = records

    return audit


def attach_audit(input_case: MinerUHTMLCase) -> MinerUHTMLCase:
    """Build and attach the per-segment account to a case.

    Never raises: an accounting problem must not turn a usable extraction into
    a failed case. If the account cannot be built, the case simply gets an
    empty one plus the reason.

    Args:
        input_case: Case to describe.

    Returns:
        The same case with ``audit`` set.
    """
    try:
        input_case.audit = build_audit(
            input_case, fallback_used=input_case.fallback_used
        )
    except Exception as e:  # pragma: no cover - defensive
        input_case.audit = MinerUHTMLAudit(
            parse_failed=input_case.is_parse_failure(),
            fallback_used=input_case.fallback_used,
            build_error=f'{type(e).__name__}: {e}',
        )
    return input_case
