from enum import Enum

# HTML attribute constants
ITEM_ID_ATTR = '_item_id'
TAIL_BLOCK_TAG = 'cc-alg-uc-text'
SELECT_ATTR = 'cc-select'
CLASS_ATTR = 'mark-selected'


class TagType(Enum):
    """Enumeration for HTML tag types in the extraction process."""

    Main = 'main'  # Main content tag
    Other = 'other'  # Other/non-main content tag


class ItemDisposition(str, Enum):
    """Final disposition of a simplified-HTML segment in one extraction case.

    The three states are deliberately kept apart: a segment explicitly labeled
    "other" by the model is not the same as a segment the model never labeled.
    """

    Kept = 'kept'  # Labeled "main" and kept in the extracted main HTML
    RemovedOther = 'removed_other'  # Explicitly labeled "other" and removed
    Missing = 'missing'  # Model gave no usable label for this item id


def normalize_tag_label(raw: object) -> str | None:
    """Normalize a raw model label into 'main', 'other' or None.

    Args:
        raw: Raw label value from the parsed model response.

    Returns:
        'main' or 'other' when the value is a usable label, otherwise None.
    """
    if not isinstance(raw, str):
        return None
    value = raw.strip().lower()
    if value in (TagType.Main.value, TagType.Other.value):
        return value
    return None
