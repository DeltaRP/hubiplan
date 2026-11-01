"""Beträge in Worten für Quittungen („einhundertzwanzig Euro und 50 Cent“)."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from django.utils.translation import gettext

_ONES = [
    "null",
    "eins",
    "zwei",
    "drei",
    "vier",
    "fünf",
    "sechs",
    "sieben",
    "acht",
    "neun",
    "zehn",
    "elf",
    "zwölf",
    "dreizehn",
    "vierzehn",
    "fünfzehn",
    "sechzehn",
    "siebzehn",
    "achtzehn",
    "neunzehn",
]
_TENS = [
    "",
    "",
    "zwanzig",
    "dreißig",
    "vierzig",
    "fünfzig",
    "sechzig",
    "siebzig",
    "achtzig",
    "neunzig",
]


def _below_100(n: int, final: bool) -> str:
    if n < 20:
        if n == 1:
            return "eins" if final else "ein"
        return _ONES[n]
    tens, ones = divmod(n, 10)
    if ones == 0:
        return _TENS[tens]
    unit = "ein" if ones == 1 else _ONES[ones]
    return f"{unit}und{_TENS[tens]}"


def _below_1000(n: int, final: bool) -> str:
    hundreds, rest = divmod(n, 100)
    text = ""
    if hundreds:
        text = ("ein" if hundreds == 1 else _ONES[hundreds]) + "hundert"
    if rest:
        text += _below_100(rest, final)
    return text


def number_words(n: int) -> str:
    """Ganze Zahl (0 bis unter eine Milliarde) in Worten, klein geschrieben."""
    if n < 0 or n >= 1_000_000_000:
        raise ValueError(gettext("Zahl außerhalb des Bereichs"))
    if n == 0:
        return "null"
    millions, rest = divmod(n, 1_000_000)
    thousands, ones = divmod(rest, 1000)
    parts = []
    if millions:
        parts.append(
            "eine Million" if millions == 1 else f"{_below_1000(millions, False)} Millionen"
        )
    text = ""
    if thousands:
        text += _below_1000(thousands, False) + "tausend"
    if ones:
        text += _below_1000(ones, True)
    if text:
        parts.append(text)
    return " ".join(parts)


def euro_words(amount: Decimal) -> str:
    value = Decimal(amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    euros = int(value)
    cents = int((value - euros) * 100)
    text = f"{number_words(euros)} Euro"
    if euros == 1:
        text = "ein Euro"
    if cents:
        text += f" und {cents} Cent"
    return text
