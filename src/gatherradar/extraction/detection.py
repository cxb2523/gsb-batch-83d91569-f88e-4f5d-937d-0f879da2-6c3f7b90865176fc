"""Context guards for individual activities, applied before resolving a title."""
from __future__ import annotations

import re

from .text import normalize

_PAST = re.compile(r'برگزار (?:شد|کرد)|دعوت کرد|رقم زد|took place|\bhosted\b|\brecap\b|گزارش تصویری')
_FUTURE = re.compile(r'برگزار می|برگزار خواهد|ثبت[\s‌]*نام|رزرو|خرید بلیت|بپیوند|منتظرت|\bregister\b|\bjoin us\b|\bnext\b')
_COLLECTION = re.compile(r'ایونت[\s‌]*های هفته|رویدادهایی رو گرد|کدوم اسلاید|برنامه[\s‌]*های این هفته|تقویم این هفته')
_SERIES = re.compile(r'هر [اآ]خر هفته.*فیلم.*کتاب.*روانشناس', re.DOTALL)
_SPECIFIC = re.compile(r'این هفته ایونت\s+فیلم\s+و\s+گفتگو')


def context_diagnostic(text: str) -> str | None:
    """A collection is not a single Event; vague promotions remain inspectable.

    These guards require several contextual signals. They never authorize an
    Event by themselves: the existing activity/attendance classifier still runs.
    """
    folded = normalize(text)
    if _COLLECTION.search(folded) and not re.search(r'(?:زمان|تاریخ)\s*:', folded):
        return 'needs_evidence: multi_event_collection'
    if _SERIES.search(folded) and not _SPECIFIC.search(folded):
        return 'needs_evidence: unspecified_series_activities'
    if (_PAST.search(folded) and not _FUTURE.search(folded)
            and not re.search(r'\b(?:19|20)\d{2}\b|\b14\d{2}\b', folded)):
        return 'non_event: retrospective_without_new_attendance'
    if (re.search(r'فروش محصول|خرید محصول|product sale|product advertisement', folded)
            and not re.search(r'شرکت[\s‌]*کن|آموزش|برگزار|ساعت|attend|workshop on', folded)):
        return 'non_event: product_promotion'
    return None


def historical_context(text: str) -> bool:
    folded = normalize(text)
    return bool(_PAST.search(folded) and not _FUTURE.search(folded))
