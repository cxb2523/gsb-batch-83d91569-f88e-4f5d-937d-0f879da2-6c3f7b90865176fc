"""Bounded Persian day ordinals for date grammar, never source-text rewriting."""
from __future__ import annotations

import re

DAY_ORDINALS = {name: day for day, name in enumerate((
    'یکم', 'دوم', 'سوم', 'چهارم', 'پنجم', 'ششم', 'هفتم', 'هشتم', 'نهم', 'دهم',
    'یازدهم', 'دوازدهم', 'سیزدهم', 'چهاردهم', 'پانزدهم', 'شانزدهم', 'هفدهم',
    'هجدهم', 'نوزدهم', 'بیستم',
), 1)}
DAY_ORDINALS['اول'] = 1
DAY_ORDINALS.update({'بیست و ' + name: 20 + day for name, day in list(DAY_ORDINALS.items()) if day < 10})
DAY_ORDINALS.update({'سی ام': 30, 'سی و یکم': 31, 'سی و اول': 31})

# fold() has already converted ZWNJ to space. Optional whitespace supports both
# بیست‌ویکم and بیست و یکم without replacing unrelated ordinal words in prose.
DAY_PATTERN = '(?:' + '|'.join(re.escape(name).replace(r'\ ', r'\s*')
                             for name in sorted(DAY_ORDINALS, key=len, reverse=True)) + ')'
_COMPACT = {re.sub(r'\s+', '', name): day for name, day in DAY_ORDINALS.items()}


def parse_day(value: str) -> int:
    if value.isascii() and value.isdigit():
        return int(value)
    return _COMPACT[re.sub(r'\s+', '', value)]
