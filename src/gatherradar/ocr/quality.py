"""An explainable usability decision for OCR text. Never a fact extractor.

Engine confidence is not comparable across engines, so this reads the text
itself: how much of it is letters, how fragmented it is, and whether short
Latin fragments are scattered through Persian text (a typical misread of
Persian posters). It only decides whether another available local engine
should be tried. It never edits text or supplies a missing date or title, and
missing event facts alone are not treated as an OCR failure.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Part of the evidence cache identity: a new policy re-examines old results.
QUALITY_POLICY = 'ocr-quality/1'
_TOKEN = re.compile(r'\S+')
_PERSIAN = re.compile(r'[؀-ۿ]')
_LATIN = re.compile(r'[A-Za-z]')


@dataclass(frozen=True)
class OcrQuality:
    usable: bool
    reason: str
    score: float  # 0..1, only for choosing between unusable hypotheses


def assess_text(text: str | None) -> OcrQuality:
    value = (text or '').strip()
    if not value:
        return OcrQuality(False, 'empty', 0.0)
    visible = [c for c in value if not c.isspace() and c not in '‌‎‏⁦⁧⁨⁩']
    letters = [c for c in visible if c.isalpha()]
    tokens = [t.strip('‎‏⁦⁧⁨⁩') for t in _TOKEN.findall(value)]
    tokens = [t for t in tokens if t]
    letter_ratio = len(letters) / len(visible) if visible else 0.0
    words = [t for t in tokens if sum(c.isalpha() for c in t) >= 2]
    word_ratio = len(words) / len(tokens) if tokens else 0.0
    persian = sum(bool(_PERSIAN.match(c)) for c in letters)
    latin = sum(bool(_LATIN.match(c)) for c in letters)
    # Short Latin fragments inside predominantly Persian text ("ae", "fal").
    stray = [t for t in tokens if _LATIN.search(t) and not _PERSIAN.search(t) and len(t) <= 3]
    stray_ratio = len(stray) / len(tokens) if tokens else 0.0
    persian_text = persian > latin
    noisy_lines = 0
    lines = [line for line in value.splitlines() if line.strip()]
    for line in lines:
        line_tokens = [t.strip('\u200e\u200f\u2066\u2067\u2068\u2069') for t in _TOKEN.findall(line)]
        line_words = [t for t in line_tokens if sum(c.isalpha() for c in t) >= 2]
        line_stray = [t for t in line_tokens if _LATIN.search(t) and not _PERSIAN.search(t) and len(t) <= 3]
        persian_words = [t for t in line_words if _PERSIAN.search(t)]
        # A line with no word, or (in Persian text) more stray Latin than Persian words.
        noisy_lines += not line_words or (persian_text and bool(line_stray) and len(line_stray) >= len(persian_words))
    noisy_ratio = noisy_lines / len(lines) if lines else 0.0
    score = round(0.5 * letter_ratio + 0.5 * word_ratio - (stray_ratio if persian_text else 0.0)
                  - 0.5 * noisy_ratio, 3)
    if letter_ratio < 0.5:
        return OcrQuality(False, 'mostly_symbols', max(score, 0.0))
    if word_ratio < 0.5:
        return OcrQuality(False, 'fragmented', max(score, 0.0))
    if persian_text and len(stray) >= 3 and stray_ratio >= 0.15:
        return OcrQuality(False, 'mixed_script_noise', max(score, 0.0))
    if noisy_lines >= 2 and noisy_ratio >= 0.3:
        return OcrQuality(False, 'noisy_lines', max(score, 0.0))
    return OcrQuality(True, 'plausible', max(score, 0.0))


__all__ = ['OcrQuality', 'QUALITY_POLICY', 'assess_text']
