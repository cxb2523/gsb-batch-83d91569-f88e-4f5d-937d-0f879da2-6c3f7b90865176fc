from typing import List, Optional, Union
from uuid import uuid4

from pydantic import BaseModel, Field

from mineru_html.constants import ItemDisposition
from mineru_html.exceptions import MinerUHTMLError

DEFALUT_MODEL = "opendatalab/MinerU-HTML-v1.1-qwen3.5-0.8B-compact"


class MinerUHTMLBase(BaseModel):
    uid: str = Field(default_factory=lambda: str(uuid4()))


class MinerUHTMLInput(MinerUHTMLBase):
    raw_html: str
    url: Optional[str] = None


class MinerUHTMLOutput(MinerUHTMLBase):
    main_html: str
    main_content: Optional[str] = None


class MinerUHTMLGenerateInput(MinerUHTMLBase):
    full_prompt: str


class MinerUHTMLGenerateOutput(MinerUHTMLBase):
    response: str


class MinerUHTMLProcessData(MinerUHTMLBase):
    simpled_html: str
    map_html: str


class MinerUHTMLParseResult(MinerUHTMLBase):
    item_label: dict[str, str]


class MinerUHTMLItemRecord(BaseModel):
    """Per-segment account of what happened to one simplified-HTML segment.

    Attributes:
        item_id: The ``_item_id`` of the segment in the simplified HTML,
            as a string.
        label: The label the model gave for this item id ('main' or 'other'),
            or None when the model gave no usable label for it.
        disposition: Final disposition of the segment. See
            :class:`~mineru_html.constants.ItemDisposition`.
    """

    item_id: str
    label: Optional[str] = None
    disposition: ItemDisposition


class MinerUHTMLAudit(BaseModel):
    """Per-segment account of one extraction case.

    Attributes:
        items: One record per segment of the simplified HTML, in ascending
            ``_item_id`` order, each carrying the model label (if any) and
            the final disposition.
        invalid_item_ids: Item ids that appeared in the model response but
            do not exist in the simplified HTML.
        parse_failed: True when no valid label could be parsed from the model
            response at all. In that case the case is handled by the
            configured fallback (trafilatura/bypass/empty).
        fallback_used: Name of the configured fallback that produced
            ``output_data.main_html`` ('trafilatura', 'bypass' or 'empty'),
            or None when the normal extraction path succeeded.
        build_error: Set only in the defensive case where the account itself
            could not be built from the case state; ``items`` is then empty.
    """

    items: List[MinerUHTMLItemRecord] = Field(default_factory=list)
    invalid_item_ids: List[str] = Field(default_factory=list)
    parse_failed: bool = False
    fallback_used: Optional[str] = None
    build_error: Optional[str] = None

    def disposition_map(self) -> dict[str, ItemDisposition]:
        """Return a mapping of item_id -> disposition for all segments."""
        return {item.item_id: item.disposition for item in self.items}

    def label_map(self) -> dict[str, str]:
        """Return a mapping of item_id -> label for segments that got a label."""
        return {
            item.item_id: item.label for item in self.items if item.label is not None
        }


class MinerUHTMLCase:
    def __init__(self, input_data: MinerUHTMLInput):
        self.case_id: str = str(uuid4())
        self.input_data: MinerUHTMLInput = input_data
        self.process_data: Union[MinerUHTMLProcessData, None] = None
        self.generate_input: Union[MinerUHTMLGenerateInput, None] = None
        self.generate_output: Union[MinerUHTMLGenerateOutput, None] = None
        self.parse_result: Union[MinerUHTMLParseResult, None] = None
        self.output_data: Union[MinerUHTMLOutput, None] = None
        self.audit: Union[MinerUHTMLAudit, None] = None
        # Name of the fallback handler that produced output_data.main_html,
        # set by extract_main_html_fallback.
        self.fallback_used: Optional[str] = None
        # True when the model response yielded no usable label for any real
        # segment; such cases are handed to the configured fallback.
        self.parse_failed: bool = False
        self.error: Union[MinerUHTMLError, None] = None

    def set_error(self, error: MinerUHTMLError):
        self.error = error

    def is_parse_failure(self) -> bool:
        """Whether the model response yielded no usable label at all."""
        return self.parse_failed

    @property
    def main_html(self) -> Union[str, None]:
        if self.output_data is None:
            return None
        return self.output_data.main_html
