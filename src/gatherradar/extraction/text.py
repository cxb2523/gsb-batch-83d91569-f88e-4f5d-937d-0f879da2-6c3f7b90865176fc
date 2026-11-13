"""Deterministic text mechanics shared by the rule engine.

No vocabulary and no scoring live here: this module only knows how to look at
Persian and English text. It holds one deliberate property that the rest of the
engine depends on — `normalize` is **length preserving**. Every replacement maps
one character to exactly one character, so an offset found in the normalized form
is the same offset in the original. That is what lets the field extractor report
the operator's own wording (نیم‌فاصله, Persian digits and all) while matching
against a folded form.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

ZWNJ = "\u200c"

# Persian (U+06Fx) and Arabic-Indic (U+066x) digits, folded to ASCII for matching.
_DIGIT_MAP = {
    **{chr(0x06F0 + offset): str(offset) for offset in range(10)},
    **{chr(0x0660 + offset): str(offset) for offset in range(10)},
}

# Arabic spellings of letters that Persian writes differently. Every entry is a
# single character, so folding cannot change the length of the text.
_LETTER_MAP = {
    "\u064a": "\u06cc",  # ARABIC YEH -> FARSI YEH
    "\u0649": "\u06cc",  # ALEF MAKSURA -> FARSI YEH
    "\u0643": "\u06a9",  # ARABIC KAF -> KEHEH
    "\u0629": "\u0647",  # TEH MARBUTA -> HEH
    "\u0623": "\u0627",  # ALEF WITH HAMZA ABOVE -> ALEF
    "\u0625": "\u0627",  # ALEF WITH HAMZA BELOW -> ALEF
    "\u0622": "\u0627",  # ALEF WITH MADDA -> ALEF
    "\u0671": "\u0627",  # ALEF WASLA -> ALEF
}

# Invisible marks that separate words visually. Folding them to a space keeps the
# length identical while letting "کافه‌گالری" match the phrase "کافه گالری".
_SEPARATORS = frozenset(
    {ZWNJ, "\u200b", "\u200d", "\u200e", "\u200f", "\ufeff", "\u00a0", "\u2066", "\u2067", "\u2068", "\u2069"}
)

# Arabic combining marks. They are not word characters, so they would split a
# token; the tokenizer keeps them inside the token and strips them for comparison.
_MARKS = "\u064b-\u0652\u0670\u0654\u0655"
_MARK_RE = re.compile(f"[{_MARKS}]")
_TOKEN_RE = re.compile(rf"[^\W_]+(?:[{_MARKS}][^\W_]*)*")

# Letters only: the Persian (U+06F0-U+06F9) and Arabic-Indic (U+0660-U+0669) digit
# blocks are skipped, so a caption of dates is not mistaken for Persian prose.
_PERSIAN_LETTER_RE = re.compile(r"[\u0621-\u065F\u066E-\u06EF\u06FA-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]")
_LATIN_LETTER_RE = re.compile(r"[A-Za-z]")


def normalize(text: str) -> str:
    """Fold text for matching without changing its length.

    Persian and Arabic-Indic digits become ASCII digits, Arabic letter spellings
    become their Persian equivalents, invisible separators become spaces, and
    letters are lowercased one character at a time so a multi-character uppercase
    mapping can never shift an offset.
    """
    folded: list[str] = []
    for char in text:
        if char in _SEPARATORS:
            folded.append(" ")
            continue
        replacement = _DIGIT_MAP.get(char) or _LETTER_MAP.get(char)
        if replacement is not None:
            folded.append(replacement)
            continue
        lowered = char.lower()
        folded.append(lowered if len(lowered) == 1 else char)
    return "".join(folded)


@dataclass(frozen=True, slots=True)
class Token:
    """One word of the normalized text, with offsets valid in the original text."""

    text: str
    start: int
    end: int


def tokenize(normalized: str) -> tuple[Token, ...]:
    tokens: list[Token] = []
    for match in _TOKEN_RE.finditer(normalized):
        stripped = _MARK_RE.sub("", match.group())
        if stripped:
            tokens.append(Token(stripped, match.start(), match.end()))
    return tuple(tokens)


def phrase_tokens(phrase: str) -> tuple[str, ...]:
    """Token form of a vocabulary entry, folded the same way as observed text."""
    return tuple(token.text for token in tokenize(normalize(phrase)))


def title_equivalence_key(title: str) -> tuple[str, ...]:
    """Whether two written titles name the same thing, without fuzzy matching.

    Folding removes only spelling noise: punctuation, emoji, spacing, ZWNJ, digit
    script and Arabic/Persian letter variants. Every word and number stays, so
    "کارگاه سفال ۱" and "کارگاه سفال ۲" remain different titles.
    """
    return phrase_tokens(title)


def compile_vocabulary(phrases: Iterable[str]) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Pair every vocabulary phrase with its token form, longest phrase first.

    Longest-first ordering makes a specific phrase win over a shorter one it
    contains, so "کافه گالری" is matched as one term rather than as "گالری".
    """
    compiled = tuple((phrase, phrase_tokens(phrase)) for phrase in phrases)
    return tuple(sorted((entry for entry in compiled if entry[1]), key=lambda entry: -len(entry[1])))


@dataclass(frozen=True, slots=True)
class PhraseMatch:
    phrase: str
    first_token: int
    last_token: int
    start: int
    end: int


def find_phrases(
    tokens: Sequence[Token],
    vocabulary: Sequence[tuple[str, tuple[str, ...]]],
    *,
    blocked: frozenset[int] = frozenset(),
) -> tuple[PhraseMatch, ...]:
    """Every non-overlapping token-sequence match of `vocabulary`, in text order.

    Matching whole tokens rather than substrings is what keeps "کلاسیک" from
    counting as "کلاس" and "رویدادهای" from counting as "رویداد". `blocked` holds
    token indices already claimed by a stronger reading of the same words — a
    retrospective phrase claims its words before temporal detection looks at them.
    """
    matches: list[PhraseMatch] = []
    taken: set[int] = set(blocked)
    for phrase, wanted in vocabulary:
        span = len(wanted)
        for index in range(len(tokens) - span + 1):
            window = range(index, index + span)
            if any(position in taken for position in window):
                continue
            if all(tokens[index + offset].text == wanted[offset] for offset in range(span)):
                matches.append(
                    PhraseMatch(
                        phrase=phrase,
                        first_token=index,
                        last_token=index + span - 1,
                        start=tokens[index].start,
                        end=tokens[index + span - 1].end,
                    )
                )
                taken.update(window)
    return tuple(sorted(matches, key=lambda match: match.start))


def has_meaningful_content(text: str, function_words: frozenset[str]) -> bool:
    """Whether the text carries anything worth classifying at all.

    Conservative on purpose, and deliberately not a character count: a short
    legitimate title ("کنسرت") is meaningful, while a stray connector ("and") or
    a lone emoji is not. Anything with at least one word that is not a closed-class
    function word counts, and so does any number.
    """
    for token in tokenize(normalize(text)):
        if token.text.isdigit():
            return True
        if len(token.text) > 1 and token.text not in function_words:
            return True
    return False


def detect_language(text: str) -> str | None:
    """`fa`, `en`, or None — a deterministic script count, not a language model."""
    persian = len(_PERSIAN_LETTER_RE.findall(text))
    latin = len(_LATIN_LETTER_RE.findall(text))
    if persian > latin:
        return "fa"
    if latin > persian:
        return "en"
    return None


def line_bounds(text: str, position: int) -> tuple[int, int]:
    """Start and end offsets of the line containing `position`."""
    start = text.rfind("\n", 0, position) + 1
    end = text.find("\n", position)
    return start, len(text) if end == -1 else end


__all__ = [
    "PhraseMatch",
    "Token",
    "ZWNJ",
    "compile_vocabulary",
    "detect_language",
    "find_phrases",
    "has_meaningful_content",
    "line_bounds",
    "normalize",
    "phrase_tokens",
    "title_equivalence_key",
    "tokenize",
]
