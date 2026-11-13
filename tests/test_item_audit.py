"""Offline tests for the per-segment extraction audit.

The simplified HTML is injected directly (rather than derived from raw HTML)
and the model response is a canned string, so these tests run without a model
or network. They cover:

1. a complete model response,
2. a response missing some item ids,
3. a response containing ids that do not exist in the simplified HTML,
4. a response that cannot be parsed at all.
"""

import re
from typing import Dict, List

import pytest

from mineru_html.api import MinerUHTMLConfig, MinerUHTMLGeneric
from mineru_html.base import (MinerUHTMLCase, MinerUHTMLGenerateInput,
                              MinerUHTMLGenerateOutput, MinerUHTMLProcessData)
from mineru_html.inference.base_backend import InferenceBackend, ModelResponse

# Fixed simplified HTML with four segments: 1 is a page title, 2 and 3 are body
# paragraphs, 4 is a footer.
SIMPLIFIED_HTML = (
    '<html><head><meta charset="utf-8"></head><body>'
    '<h1 _item_id="1">Example News</h1>'
    '<p _item_id="2">First body paragraph.</p>'
    '<p _item_id="3">Second body paragraph.</p>'
    '<div _item_id="4">Copyright footer.</div>'
    '</body></html>'
)


class FakeBackend(InferenceBackend):
    """Inference backend returning canned responses; never loads a model."""

    def __init__(self, response: str = ''):
        super().__init__(max_context_window=1024 * 1024, response_format='compact')
        self.response = response
        self.prompts: List[str] = []

    def setup_llm(self):
        pass

    def get_tokenizer(self):
        class _Tokenizer:

            def encode(self, text: str) -> List[int]:
                return [0] * (len(text) // 4 + 1)

        return _Tokenizer()

    def generate(self, prompt_list: list[str], **kwargs) -> list[ModelResponse]:
        raise AssertionError('process() is overridden by the fake backend')

    def process(self, generate_input_map: Dict[str, MinerUHTMLGenerateInput]):
        self.prompts = [item.full_prompt for item in generate_input_map.values()]
        return (
            {
                case_id: MinerUHTMLGenerateOutput(response=self.response)
                for case_id in generate_input_map
            },
            {},
        )


def inject_fixed_process_data(
    monkeypatch,
    simplified_html: str = SIMPLIFIED_HTML,
    map_html: str = None,
):
    """Make the pipeline use a fixed simplified HTML instead of simplifying."""
    map_html = simplified_html if map_html is None else map_html

    def _simplify(input_case: MinerUHTMLCase) -> MinerUHTMLCase:
        input_case.process_data = MinerUHTMLProcessData(
            simpled_html=simplified_html, map_html=map_html
        )
        return input_case

    monkeypatch.setattr(
        'mineru_html.api.simplify_single_input', _simplify
    )


def make_extractor(response: str, fallback: str = 'bypass') -> MinerUHTMLGeneric:
    return MinerUHTMLGeneric(
        llm=FakeBackend(response),
        config=MinerUHTMLConfig(
            use_fall_back=fallback,
            early_load=False,
            prompt_version='short_compact',
            response_format='compact',
            output_format='none',
        ),
    )


def run_case(monkeypatch, response: str, fallback: str = 'bypass') -> MinerUHTMLCase:
    inject_fixed_process_data(monkeypatch)
    return make_extractor(response, fallback).process([SIMPLIFIED_HTML])[0]


def dispositions(case: MinerUHTMLCase) -> Dict[str, str]:
    return {item.item_id: item.disposition.value for item in case.audit.items}


def labels(case: MinerUHTMLCase) -> Dict[str, object]:
    return {item.item_id: item.label for item in case.audit.items}


def test_complete_response_keeps_main_and_removes_other(monkeypatch):
    case = run_case(monkeypatch, '1main2main3main4other')

    assert case.error is None
    assert case.audit is not None
    assert case.audit.parse_failed is False
    assert case.audit.fallback_used is None
    assert case.audit.invalid_item_ids == []
    assert [item.item_id for item in case.audit.items] == ['1', '2', '3', '4']
    assert labels(case) == {'1': 'main', '2': 'main', '3': 'main', '4': 'other'}
    assert dispositions(case) == {
        '1': 'kept',
        '2': 'kept',
        '3': 'kept',
        '4': 'removed_other',
    }
    assert 'First body paragraph.' in case.output_data.main_html
    assert 'Second body paragraph.' in case.output_data.main_html
    assert 'Copyright footer.' not in case.output_data.main_html


def test_partial_response_records_missing_segments_and_still_extracts(monkeypatch):
    case = run_case(monkeypatch, '1main3main4other')

    assert case.error is None
    assert case.audit.parse_failed is False
    assert case.audit.invalid_item_ids == []
    assert labels(case) == {'1': 'main', '2': None, '3': 'main', '4': 'other'}
    assert dispositions(case) == {
        '1': 'kept',
        '2': 'missing',
        '3': 'kept',
        '4': 'removed_other',
    }
    # Partial labels must not trigger a whole-page fallback: the labeled
    # segments are extracted normally from this page.
    assert case.audit.fallback_used is None
    assert 'Example News' in case.output_data.main_html
    assert 'Second body paragraph.' in case.output_data.main_html
    assert 'Copyright footer.' not in case.output_data.main_html
    # The unlabeled segment is dropped by the normal clipping rules; the
    # audit is the only place saying it went missing rather than "other".
    assert 'First body paragraph.' not in case.output_data.main_html


def test_invalid_item_ids_are_reported_not_silently_ignored(monkeypatch):
    case = run_case(monkeypatch, '1main2other9main4other')

    assert case.error is None
    assert case.audit.parse_failed is False
    assert case.audit.invalid_item_ids == ['9']
    # The real segments keep their own dispositions; the invalid id is not
    # attributed to any segment.
    assert [item.item_id for item in case.audit.items] == ['1', '2', '3', '4']
    assert dispositions(case) == {
        '1': 'kept',
        '2': 'removed_other',
        '3': 'missing',
        '4': 'removed_other',
    }
    assert 'First body paragraph.' not in case.output_data.main_html
    assert 'Second body paragraph.' not in case.output_data.main_html


def test_json_response_with_invalid_ids_and_missing_segments(monkeypatch):
    # The same rules hold for the JSON response format.
    case = run_case(monkeypatch, '{"1": "main", "3": "other", "7": "main", "8": "other"}')

    assert case.error is None
    assert case.audit.parse_failed is False
    assert case.audit.invalid_item_ids == ['7', '8']
    assert labels(case) == {'1': 'main', '2': None, '3': 'other', '4': None}
    assert dispositions(case) == {
        '1': 'kept',
        '2': 'missing',
        '3': 'removed_other',
        '4': 'missing',
    }


@pytest.mark.parametrize('response', ['', 'I cannot help with that.', '{}', 'garbage'])
def test_unparseable_response_falls_back_without_raising(monkeypatch, response):
    case = run_case(monkeypatch, response, fallback='bypass')

    # The case must not raise an uncaught exception; it carries an error and
    # is handled by the configured fallback.
    assert case.error is not None
    assert case.audit is not None
    assert case.audit.parse_failed is True
    assert case.audit.fallback_used == 'bypass'
    # Every segment is accounted for as missing: none got a usable label.
    assert dispositions(case) == {
        '1': 'missing',
        '2': 'missing',
        '3': 'missing',
        '4': 'missing',
    }
    assert all(item.label is None for item in case.audit.items)
    # Bypass fallback returns the raw HTML unchanged.
    assert case.output_data.main_html == SIMPLIFIED_HTML


def test_unparseable_response_uses_configured_empty_fallback(monkeypatch):
    case = run_case(monkeypatch, 'no json here', fallback='empty')

    assert case.audit.parse_failed is True
    assert case.audit.fallback_used == 'empty'
    assert case.output_data.main_html == ''


def test_response_with_only_invalid_ids_records_them_then_falls_back(monkeypatch):
    # No usable label for any real segment => parse failure and fallback, but
    # the invented ids must still show up in the account.
    case = run_case(monkeypatch, '9main10other', fallback='bypass')

    assert case.audit.parse_failed is True
    assert case.audit.fallback_used == 'bypass'
    assert case.audit.invalid_item_ids == ['9', '10']
    assert dispositions(case) == {
        '1': 'missing',
        '2': 'missing',
        '3': 'missing',
        '4': 'missing',
    }


def test_process_preserves_input_order(monkeypatch):
    pages = {
        'MARKER_A': (
            '<html><body><p _item_id="1">MARKER_A</p></body></html>'
        ),
        'MARKER_B': (
            '<html><body><p _item_id="1">MARKER_B</p></body></html>'
        ),
    }
    responses = {'MARKER_A': '1main', 'MARKER_B': '1other'}

    def _simplify(input_case: MinerUHTMLCase) -> MinerUHTMLCase:
        page = input_case.input_data.raw_html
        input_case.process_data = MinerUHTMLProcessData(
            simpled_html=page, map_html=page
        )
        return input_case

    class _PerPageBackend(FakeBackend):

        def process(self, generate_input_map):
            output_map = {}
            for case_id, generate_input in generate_input_map.items():
                marker = re.search(r'MARKER_[A-Z]', generate_input.full_prompt)
                output_map[case_id] = MinerUHTMLGenerateOutput(
                    response=responses[marker.group(0)]
                )
            return output_map, {}

    monkeypatch.setattr('mineru_html.api.simplify_single_input', _simplify)
    extractor = MinerUHTMLGeneric(
        llm=_PerPageBackend(),
        config=MinerUHTMLConfig(
            use_fall_back='bypass', early_load=False, output_format='none'
        ),
    )
    cases = extractor.process([pages['MARKER_B'], pages['MARKER_A']])

    assert [case.audit.items[0].disposition.value for case in cases] == [
        'removed_other',
        'kept',
    ]
    assert 'MARKER_A' in cases[1].output_data.main_html
    assert 'MARKER_B' not in cases[0].output_data.main_html


def test_invalid_input_does_not_break_audit(monkeypatch):
    inject_fixed_process_data(monkeypatch)
    extractor = make_extractor('1main')
    cases = extractor.process([123, SIMPLIFIED_HTML])

    # The bad entry keeps its error and an empty account; the good entry is
    # still processed and its position in the result is unchanged.
    assert isinstance(cases[0].error, Exception)
    assert cases[0].audit.items == []
    assert cases[1].audit.items != []


RAW_HTML = (
    '<html><body>'
    '<div class="nav"><a href="/">Home</a></div>'
    '<div class="article"><h1>Title</h1>'
    '<p>Para one long enough to be meaningful text here.</p>'
    '<p>Para two also long enough to be retained by the simplifier.</p></div>'
    '<div class="footer">Footer links</div>'
    '</body></html>'
)


def test_audit_on_real_simplification_pipeline():
    # No fixed simplified HTML here: the real simplifier assigns the ids and
    # builds the mapped HTML, so the audit must line up with what was clipped.
    extractor = make_extractor('1main2main4other')
    case = extractor.process([RAW_HTML])[0]

    assert case.error is None
    assert case.audit.parse_failed is False
    item_ids = [item.item_id for item in case.audit.items]
    assert item_ids == ['1', '2', '3', '4']
    assert dispositions(case) == {
        '1': 'kept',
        '2': 'kept',
        '3': 'missing',
        '4': 'removed_other',
    }
    # Kept segments are present; the explicitly-other and missing ones are not.
    assert 'Title' in case.output_data.main_html
    assert 'Para one' in case.output_data.main_html
    assert 'Para two' not in case.output_data.main_html
    assert 'Footer links' not in case.output_data.main_html
