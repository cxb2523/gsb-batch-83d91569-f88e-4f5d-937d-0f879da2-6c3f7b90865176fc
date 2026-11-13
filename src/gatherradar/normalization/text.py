"""Internal parsing copies only: never assign folded text to source fields."""
from persiantools import characters, digits
import unicodedata


def fold(text: str) -> str:
    text = characters.ar_to_fa(digits.fa_to_en(digits.ar_to_fa(text)))
    text = ''.join(' ' if c == '\u200c' else '' if unicodedata.category(c) == 'Cf' else c for c in text)
    return " ".join(text.split()).casefold()
