"""Formatting and normalisation helpers shared across services."""
from __future__ import annotations

import re
import secrets
import string
from datetime import date, timedelta
from typing import Any

from .config import settings

_ALPHABET = string.ascii_uppercase + string.digits


def token(length: int = 8) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


# --------------------------------------------------------------------------- #
# money
# --------------------------------------------------------------------------- #
def indian_group(value: float) -> str:
    """1234567 -> '12,34,567' (Indian digit grouping)."""
    neg = value < 0
    whole = f"{abs(value):.0f}"
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        head = re.sub(r"(?<=\d)(?=(\d\d)+$)", ",", head)
        whole = f"{head},{tail}"
    return ("-" if neg else "") + whole


def money(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{settings.CURRENCY_SYMBOL}{indian_group(float(value))}"


# --------------------------------------------------------------------------- #
# phone
# --------------------------------------------------------------------------- #
MOBILE_RE = re.compile(r"(?:\+?91[\-\s]?)?([6-9]\d{9})\b")


def normalise_mobile(raw: Any) -> str | None:
    """Return a 10-digit Indian mobile number, or None if it isn't one."""
    if raw is None:
        return None
    digits = re.sub(r"\D", "", str(raw))
    if digits.startswith("0"):
        digits = digits.lstrip("0")
    if len(digits) > 10 and digits.startswith("91"):
        digits = digits[2:]
    if len(digits) == 10 and digits[0] in "6789":
        return digits
    return None


def mask_mobile(mobile: str | None) -> str:
    if not mobile or len(mobile) < 4:
        return "—"
    return f"{mobile[:2]}••••{mobile[-3:]}"


# --------------------------------------------------------------------------- #
# names / text
# --------------------------------------------------------------------------- #
_NAME_STOPWORDS = {
    "yes", "no", "ok", "okay", "hi", "hello", "hey", "thanks", "thank", "sure",
    "maybe", "ac", "acs", "rice", "kg", "ton", "tons", "please", "need", "want",
    "buy", "my", "name", "is", "im", "i", "am", "the", "and", "for",
}


def clean_name(raw: str | None) -> str | None:
    if not raw:
        return None
    text = re.sub(r"[^A-Za-z\s\.\-']", " ", str(raw)).strip()
    text = re.sub(r"\s+", " ", text)
    words = [w for w in text.split() if w.lower() not in _NAME_STOPWORDS]
    # One-letter names are real names; rejecting them used to trap the customer
    # on the name question forever.
    if not words or not " ".join(words):
        return None
    return " ".join(w.capitalize() if w.islower() or w.isupper() else w for w in words[:4])


# --------------------------------------------------------------------------- #
# open-ended product names
# --------------------------------------------------------------------------- #
#: Words that carry no product identity. Two buyers typing "good quality office
#: chairs" and "office chair" must land on the same key.
_PRODUCT_NOISE = {
    "a", "an", "the", "some", "any", "few", "new", "brand", "good", "best",
    "quality", "nice", "cheap", "premium", "standard", "normal", "regular",
    "pcs", "pieces", "piece", "nos", "no", "units", "unit", "qty", "quantity",
    "i", "we", "need", "want", "require", "looking", "for", "buy", "buying",
    "purchase", "please", "plz", "kindly", "my", "our", "of", "to",
}

#: Irregular plurals worth handling; everything else uses the suffix rules.
_IRREGULAR_SINGULARS = {
    "boxes": "box", "batteries": "battery", "supplies": "supply",
    "brushes": "brush", "glasses": "glass", "dresses": "dress",
    "benches": "bench", "watches": "watch", "knives": "knife",
    "shelves": "shelf", "leaves": "leaf", "wheat": "wheat", "rice": "rice",
}


def singular(word: str) -> str:
    """Best-effort singular. Deliberately conservative: turning 'glass' into
    'glas' would split a group, which is worse than leaving a plural alone."""
    lowered = word.lower()
    if lowered in _IRREGULAR_SINGULARS:
        return _IRREGULAR_SINGULARS[lowered]
    if len(lowered) <= 3 or lowered.endswith("ss") or lowered.endswith("us"):
        return lowered
    if lowered.endswith("ies") and len(lowered) > 4:
        return lowered[:-3] + "y"
    if lowered.endswith(("ches", "shes", "xes", "zes", "ses")):
        return lowered[:-2]
    if lowered.endswith("s"):
        return lowered[:-1]
    return lowered


def normalise_product(raw: str | None) -> str:
    """Canonical key for an arbitrary product name.

    "2 Office Chairs!", "office chair", "good quality OFFICE CHAIRS"
      -> "office chair"

    This key decides who is pooled with whom, so it strips quantities, units,
    punctuation and filler adjectives, then singularises each remaining word.
    """
    if not raw:
        return ""
    text = str(raw).lower()
    text = re.sub(r"[^a-z0-9\s\-/&]+", " ", text)
    text = re.sub(r"\b\d+(?:\.\d+)?\s*(?:kg|kgs|gm|gms|g|ton|tonne|tons|l|ltr|litre|"
                  r"liters?|ml|mtr|meter|metres?|ft|feet|inch|in|box|boxes|bag|bags|"
                  r"packet|packets|pack|packs|dozen|set|sets)?\b", " ", text)
    words = [w for w in text.split() if w and w not in _PRODUCT_NOISE]
    words = [singular(w) for w in words]
    words = [w for w in words if w and w not in _PRODUCT_NOISE]
    return " ".join(words[:5]).strip()


#: Units a customer might count in, mapped to a canonical label.
_UNIT_ALIASES = {
    "kg": "kg", "kgs": "kg", "kilo": "kg", "kilos": "kg", "kilogram": "kg",
    "kilograms": "kg", "quintal": "quintal", "ton": "ton", "tons": "ton",
    "tonne": "ton", "tonnes": "ton",
    "l": "litre", "ltr": "litre", "litre": "litre", "litres": "litre",
    "liter": "litre", "liters": "litre", "ml": "ml",
    "box": "box", "boxes": "box", "carton": "carton", "cartons": "carton",
    "bag": "bag", "bags": "bag", "packet": "packet", "packets": "packet",
    "pack": "pack", "packs": "pack", "roll": "roll", "rolls": "roll",
    "sheet": "sheet", "sheets": "sheet", "set": "set", "sets": "set",
    "pair": "pair", "pairs": "pair", "dozen": "dozen", "metre": "metre",
    "metres": "metre", "meter": "metre", "meters": "metre", "mtr": "metre",
    "foot": "ft", "feet": "ft", "ft": "ft", "sqft": "sq ft",
}


def detect_unit(text: str | None) -> str | None:
    """The unit a quantity was expressed in, if the customer named one."""
    if not text:
        return None
    match = re.search(
        r"\b\d+(?:\.\d+)?\s*([a-z]+)\b", str(text).lower()
    )
    if match and match.group(1) in _UNIT_ALIASES:
        return _UNIT_ALIASES[match.group(1)]
    for token in re.findall(r"[a-z]+", str(text).lower()):
        if token in _UNIT_ALIASES:
            return _UNIT_ALIASES[token]
    return None


def title(value: Any) -> str:
    text = str(value or "").strip()
    return text[:1].upper() + text[1:] if text else ""


def truncate(text: str, limit: int = 120) -> str:
    text = str(text or "")
    return text if len(text) <= limit else text[: limit - 1] + "…"


# --------------------------------------------------------------------------- #
# dates
# --------------------------------------------------------------------------- #
def add_days(base: date, days: int) -> date:
    return base + timedelta(days=days)


def days_between(a: date | None, b: date | None) -> int | None:
    if a is None or b is None:
        return None
    return (b - a).days


def overlap_days(a_start: date, a_end: date, b_start: date, b_end: date) -> int:
    start = max(a_start, b_start)
    end = min(a_end, b_end)
    return (end - start).days + 1 if end >= start else 0


def friendly_date(value: date | str | None) -> str:
    if value is None:
        return "—"
    if isinstance(value, str):
        try:
            value = date.fromisoformat(value[:10])
        except ValueError:
            return value
    return value.strftime("%d %b %Y")


def short_date(value: date | str | None) -> str:
    if value is None:
        return "—"
    if isinstance(value, str):
        try:
            value = date.fromisoformat(value[:10])
        except ValueError:
            return value
    return value.strftime("%d %b")


# --------------------------------------------------------------------------- #
# numbers
# --------------------------------------------------------------------------- #
def to_int(value: Any, default: int = 0) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def to_float(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def qty_str(value: float) -> str:
    return f"{value:g}"
