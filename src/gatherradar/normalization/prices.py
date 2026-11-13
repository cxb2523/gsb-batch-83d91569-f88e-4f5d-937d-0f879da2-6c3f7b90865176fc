"""One explicit price only. Full matching avoids extracting a tier or discount."""
from __future__ import annotations

import re
from decimal import Decimal, localcontext

from .models import Diagnostic, PriceResult
from .text import fold

_CURRENCIES = {
    "تومان": "TOMAN", "تومن": "TOMAN", "ریال": "IRR", "irr": "IRR",
    "usd": "USD", "us dollar": "USD", "us dollars": "USD", "دلار آمریکا": "USD",
    "eur": "EUR", "euro": "EUR", "euros": "EUR", "یورو": "EUR", "€": "EUR",
    "gbp": "GBP", "پوند انگلیس": "GBP", "£": "GBP",
}
_CURRENCY = "(?:" + "|".join(re.escape(k) for k in sorted(_CURRENCIES, key=len, reverse=True)) + ")"
_NUMBER = r"(?:[0-9]{1,3}(?:[,٬][0-9]{3})+|[0-9]+)(?:[.٫][0-9]+)?"
_AMOUNT = rf"(?P<amount>{_NUMBER})\s*(?P<scale>هزار|میلیون|thousand|million)?"
_PRICE = re.compile(rf"(?:{_AMOUNT}\s*(?P<currency>{_CURRENCY}))")
_PREFIX = re.compile(rf"(?P<currency>{_CURRENCY})\s*{_AMOUNT}")
_LABEL = re.compile(r"^(?:(?:هزینه(?:\s+ثبت نام)?|قیمت(?:\s+بلی[تط])?|ورودی|بلی[تط]|price|admission)\s*[:：]?\s*)")


def normalize_price(source_text: str | None) -> PriceResult:
    if source_text is None or not source_text.strip():
        return PriceResult(diagnostics=(Diagnostic("missing_price", "price_text", "No price was supplied."),))
    if len(source_text) > 4096:
        return PriceResult(diagnostics=(Diagnostic("price_too_long", "price_text", "Price exceeds parsing limit."),))
    text = _LABEL.sub("", fold(source_text)).strip(" .؛;")
    if text in {"رایگان", "بدون هزینه", "free", "free admission", "no fee"}:
        return PriceResult(Decimal(0))  # No currency was stated; zero does not imply TOMAN.
    matched = _PRICE.fullmatch(text) or _PREFIX.fullmatch(text)
    if matched:
        amount = Decimal(matched["amount"].replace(",", "").replace("٬", "").replace("٫", "."))
        scale = {"هزار": 1000, "thousand": 1000, "میلیون": 1000000, "million": 1000000}.get(matched["scale"], 1)
        # Bound digits before Decimal arithmetic so the default context cannot round.
        if len(amount.as_tuple().digits) <= 18:
            with localcontext() as context:
                context.prec = 32
                return PriceResult(amount * scale, _CURRENCIES[matched["currency"]])
    return PriceResult(diagnostics=(Diagnostic(
        "ambiguous_price", "price_text",
        "No single explicit price: range, tiers, conditions, currency or wording needs review.",
    ),))
