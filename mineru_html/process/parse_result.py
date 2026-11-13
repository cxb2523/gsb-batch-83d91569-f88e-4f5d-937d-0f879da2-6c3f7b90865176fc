import json
import re
from typing import List

from mineru_html.base import MinerUHTMLCase, MinerUHTMLParseResult
from mineru_html.constants import normalize_tag_label
from mineru_html.exceptions import (MinerUHTMLError,
                                    MinerUHTMLResponseParseError)
from mineru_html.utils import get_segment_ids


def find_brace_pair(response: str) -> str:
    """Extract JSON content between first '{' and last '}'.

    Args:
        response: Response string that may contain JSON.

    Returns:
        String containing JSON content between braces.
    """
    first_brace_index = response.find('{')
    if first_brace_index == -1:
        raise MinerUHTMLResponseParseError('No left brace found.')
    last_brace_index = response.rfind('}')
    if last_brace_index == -1:
        return response[first_brace_index:]
    else:
        return response[first_brace_index : last_brace_index + 1]


def parse_json_by_remove_last_chars(response: str) -> dict:
    """Parse JSON by progressively removing characters from the end.

    This is a fallback method when the response is not valid JSON but may
    contain a valid JSON prefix.

    Args:
        response: Response string to parse.

    Returns:
        Parsed dictionary.
    """
    idx = len(response)
    while idx > 0:
        if idx <= 1:
            raise MinerUHTMLResponseParseError(
                'No valid prefix can be parsed as a json dict'
            )
        try:
            return json.loads(response[:idx] + '}')
        except Exception:
            idx -= 1


def parse_llm_response(response: str) -> dict[str, str]:
    """Parse LLM response into a dictionary of item_id -> label.

    Supports both JSON format and compact format (e.g., "1main2other").

    Args:
        response: Raw response string from LLM.

    Returns:
        Dictionary mapping item_id (as string) to label ("main" or "other").

    Raises:
        MinerUHTMLResponseParseError: If no labels can be parsed at all.
    """
    try:
        clean_response = find_brace_pair(response)
    except MinerUHTMLResponseParseError:
        pattern = r'(\d+)(main|other)'
        matches = [(m.group(1), m.group(2)) for m in re.finditer(pattern, response)]
        if len(matches) == 0:
            raise MinerUHTMLResponseParseError(
                f'Not valid response, the raw response is {response}'
            )
        pred_dict = {item_id: category for item_id, category in matches}
        return pred_dict
    else:
        try:
            parsed = json.loads(clean_response)
        except Exception:
            try:
                parsed = parse_json_by_remove_last_chars(clean_response)
            except Exception as e:
                raise MinerUHTMLResponseParseError(
                    f'Cannot parse JSON response, the raw response is {response}. Error: {e}'
                ) from e
        if not isinstance(parsed, dict):
            raise MinerUHTMLResponseParseError(
                f'Parsed response is not a JSON object, the raw response is {response}'
            )
        return {str(k): v for k, v in parsed.items()}


def has_usable_segment_label(
    item_label: dict[str, str] | None, segment_ids: List[str]
) -> bool:
    """Whether any segment of the simplified HTML got a usable main/other label.

    Args:
        item_label: Parsed mapping of item_id -> label.
        segment_ids: Item ids actually present in the simplified HTML.

    Returns:
        True if at least one real segment carries a "main" or "other" label.
    """
    if not item_label:
        return False
    segment_id_set = set(segment_ids)
    return any(
        str(item_id).strip() in segment_id_set
        and normalize_tag_label(label) is not None
        for item_id, label in item_label.items()
    )


def parse_result(input_case: MinerUHTMLCase) -> MinerUHTMLCase:
    """
    Parse result from generate output

    Args:
        input_case: input case
    Returns:
        input case
    """
    try:
        item_label = parse_llm_response(input_case.generate_output.response)
    except Exception as e:
        input_case.parse_failed = True
        if isinstance(e, MinerUHTMLError):
            e.set_case_id(input_case.case_id)
            raise e
        else:
            raise MinerUHTMLResponseParseError(
                f'Parse result failed: {str(e)}', case_id=input_case.case_id
            ) from e

    segment_ids = (
        get_segment_ids(input_case.process_data.simpled_html)
        if input_case.process_data is not None
        else []
    )
    if not has_usable_segment_label(item_label, segment_ids):
        # The response is well-formed enough to load but carries no usable
        # main/other label for any real segment (e.g. "{}", {"1": "unknown"}
        # or only ids that do not exist in the simplified HTML). Nothing can
        # be extracted from it, so treat it as a parse failure and let the
        # configured fallback handle the case. The parsed map is kept on the
        # case so the audit can still report invented ids instead of losing
        # them with the failed extraction.
        input_case.parse_result = MinerUHTMLParseResult(item_label=item_label)
        input_case.parse_failed = True
        raise MinerUHTMLResponseParseError(
            'No usable main/other label parsed for any segment of the '
            f'simplified HTML, the parsed response is {item_label}',
            case_id=input_case.case_id,
        )

    input_case.parse_result = MinerUHTMLParseResult(item_label=item_label)
    return input_case
