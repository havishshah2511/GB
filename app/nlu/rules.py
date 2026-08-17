"""Deterministic slot extractor.

This is the default NLU engine: no network, no API key, fully testable. When an
Anthropic key is configured the LLM extractor runs first and this module
back-fills anything it missed (and takes over entirely if the call fails).

`extract()` never invents a value it cannot ground in the text.
"""
from __future__ import annotations

import calendar
import re
from datetime import date, timedelta
from typing import Any

from .. import catalog
from ..db import today
from ..utils import clean_name, normalise_mobile, to_float

# --------------------------------------------------------------------------- #
# vocabularies
# --------------------------------------------------------------------------- #
CITIES: dict[str, tuple[str, ...]] = {
    "Ahmedabad": ("ahmedabad", "amdavad", "ahmadabad", "ahemdabad", "ahd"),
    "Surat": ("surat",),
    "Vadodara": ("vadodara", "baroda"),
    "Rajkot": ("rajkot",),
    "Gandhinagar": ("gandhinagar",),
    "Mumbai": ("mumbai", "bombay"),
    "Pune": ("pune", "poona"),
    "Nashik": ("nashik", "nasik"),
    "Nagpur": ("nagpur",),
    "Delhi": ("delhi", "new delhi", "ncr"),
    "Gurugram": ("gurugram", "gurgaon"),
    "Noida": ("noida",),
    "Jaipur": ("jaipur",),
    "Lucknow": ("lucknow",),
    "Indore": ("indore",),
    "Bhopal": ("bhopal",),
    "Bengaluru": ("bengaluru", "bangalore", "blr"),
    "Hyderabad": ("hyderabad", "hyd", "secunderabad"),
    "Chennai": ("chennai", "madras"),
    "Coimbatore": ("coimbatore",),
    "Kochi": ("kochi", "cochin"),
    "Kolkata": ("kolkata", "calcutta"),
    "Chandigarh": ("chandigarh",),
    "Ludhiana": ("ludhiana",),
    "Patna": ("patna",),
}
_CITY_PATTERNS = [
    (re.compile(rf"\b{re.escape(alias)}\b", re.I), name)
    for name, aliases in CITIES.items()
    for alias in aliases
]

MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}
MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_name) if m})

AFFIRMATIVE = re.compile(
    r"\b(yes|yeah|yep|yup|sure|ok(ay)?|fine|correct|right|haan|ha|of course|definitely|absolutely)\b",
    re.I,
)
NEGATIVE = re.compile(r"\b(no|nope|nah|not really|never|don'?t|nahi)\b", re.I)
MAYBE = re.compile(r"\b(maybe|may be|perhaps|possibly|not sure|depends)\b", re.I)

HELP_PATTERNS = re.compile(
    r"(how (does|do) (this|it|group)|what is (this|group buy)|how it works|explain|"
    r"why (should|do)|is this (real|safe|genuine)|who are you)",
    re.I,
)
SHARE_PATTERNS = re.compile(r"\b(share|invite|refer|link|whatsapp)\b", re.I)
READY_PATTERNS = re.compile(
    r"(i'?ll take it|i am ready|i'?m ready|ready to buy|book (it|me)|confirm my|"
    r"i want to buy at|deal|proceed with (the )?order)",
    re.I,
)
RESTART_PATTERNS = re.compile(r"\b(restart|start over|start again|reset|new requirement)\b", re.I)
STOP_PATTERNS = re.compile(r"\b(stop|not interested|no longer|remove me)\b", re.I)

#: Commands the customer may issue at ANY point in the conversation. They are
#: checked before slot extraction, so "cancel my request" can never be mistaken
#: for an answer to "Split or Window?".
CANCEL_PATTERNS = re.compile(
    r"\b(cancel|delete|drop|withdraw|remove)\b[^.?!]{0,24}\b(request|order|requirement|intent|it|this|me)\b"
    r"|\bcancel\b(?!\s*(the\s*)?(link|share))"
    r"|\bnot interested\b|\bno longer (required|interested|needed)\b|\bremove me\b",
    re.I,
)
SHOW_PAST_PATTERNS = re.compile(
    r"\b(show|see|view|check|open|display|what('?s| is)|track)\b[^.?!]{0,28}"
    r"\b(my|previous|past|old|earlier|existing)\b[^.?!]{0,18}"
    r"\b(request|order|requirement|status|booking)s?\b"
    r"|\b(my|past|old|previous|existing|earlier)\s+(request|order|requirement|booking)s?\b"
    r"|\b(request|order)\s+status\b|\bstatus of my\b",
    re.I,
)
CHANGE_PRODUCT_PATTERNS = re.compile(
    r"\bchange\b[^.?!]{0,20}\b(product|item|category|requirement|my mind)\b"
    r"|\b(different|another|other)\s+(product|item|thing|category)\b"
    r"|\bswitch\b[^.?!]{0,16}\b(product|to)\b"
    r"|\bsomething else\b|\bwrong product\b|\bnot (this|that) (product|one)\b",
    re.I,
)
EXIT_PATTERNS = re.compile(
    r"\b(exit|quit|bye|goodbye|leave|log ?out|close (the )?chat|end (the )?chat)\b"
    r"|\b(i'?m|i am) done\b|\bthat'?s (all|it)\b|\bnothing else\b|\bno thanks\b",
    re.I,
)

_QTY_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "a dozen": 12, "dozen": 12,
    "couple": 2, "half a ton": 500, "half ton": 500,
}

_TIMING_CHIPS = {
    "immediately": 0, "immediate": 0, "asap": 0, "right away": 0, "today": 0, "now": 0,
    "within 3 days": 3, "within 7 days": 7, "within 15 days": 15, "within 30 days": 30,
    "this week": 5, "next week": 7, "this month": 15, "next month": 30,
    "tomorrow": 1, "day after tomorrow": 2,
}


# --------------------------------------------------------------------------- #
# field extractors
# --------------------------------------------------------------------------- #
def extract_mobile(text: str) -> str | None:
    for match in re.finditer(r"(?:\+?91[\-\s]?)?\b(\d[\d\s\-]{8,13}\d)\b", text):
        candidate = normalise_mobile(match.group(1))
        if candidate:
            return candidate
    return None


def extract_city(text: str) -> str | None:
    for pattern, name in _CITY_PATTERNS:
        if pattern.search(text):
            return name
    return None


def extract_area(text: str, city: str | None) -> str | None:
    """Area names are open-ended, so we only trust an explicit preposition."""
    patterns = [
        r"\b(?:in|at|near|from)\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?)\s*(?:area|colony|nagar|road|society)\b",
        r"\b([A-Za-z]+(?:\s+[A-Za-z]+)?)\s+(?:area|nagar|colony|society|vihar|puram)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            area = match.group(1).strip()
            if city and area.lower() == city.lower():
                continue
            if len(area) > 1 and area.lower() not in ("this", "that", "my", "our"):
                return area.title()
    return None


def extract_quantity(text: str, category: catalog.Category | None) -> float | None:
    lowered = text.lower()
    if category:
        for pattern, multiplier in category.quantity_patterns:
            match = re.search(pattern, lowered, re.I)
            if match:
                value = to_float(match.group(1))
                if value:
                    return value * multiplier
    for word, value in _QTY_WORDS.items():
        if re.search(rf"\b{re.escape(word)}\b", lowered):
            if category and category.unit == "kg" and value < 25:
                continue
            return float(value)
    return None


def extract_bare_number(text: str, category: catalog.Category | None = None) -> float | None:
    """Used when the bot just asked 'how many?' and the reply is only a number."""
    stripped = text.strip().lower()
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(kgs?|kilos?|nos?|units?|pcs?|\+)?", stripped)
    if match:
        return to_float(match.group(1))
    match = re.search(r"\b(\d{1,6}(?:\.\d+)?)\b", stripped)
    if match and len(re.findall(r"\d+", stripped)) == 1:
        value = to_float(match.group(1))
        # A 10-digit number is a phone number, not a quantity.
        if value is not None and len(match.group(1).replace(".", "")) < 8:
            return value
    for word, value in _QTY_WORDS.items():
        if re.fullmatch(rf"{re.escape(word)}s?", stripped):
            return float(value)
    return None


def extract_budget(text: str) -> float | None:
    match = re.search(
        r"(?:₹|rs\.?|inr)\s*(\d[\d,]*(?:\.\d+)?)\s*(k|thousand|lakh|lac)?", text, re.I
    )
    if not match:
        match = re.search(r"\b(\d[\d,]*)\s*(k|thousand|lakh|lac)\b", text, re.I)
    if not match:
        return None
    value = to_float(match.group(1).replace(",", ""))
    if value is None:
        return None
    suffix = (match.group(2) or "").lower()
    if suffix in ("k", "thousand"):
        value *= 1000
    elif suffix in ("lakh", "lac"):
        value *= 100000
    return value


def _month_day(month: int, day: int, base: date) -> date:
    year = base.year
    try:
        candidate = date(year, month, day)
    except ValueError:
        return base
    if candidate < base:
        try:
            candidate = date(year + 1, month, day)
        except ValueError:
            pass
    return candidate


def extract_date(text: str, base: date | None = None) -> tuple[date | None, int | None]:
    """Return (absolute date, relative days). Either may be None."""
    base = base or today()
    lowered = text.lower().strip()

    for phrase, days in sorted(_TIMING_CHIPS.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"\b{re.escape(phrase)}\b", lowered):
            return base + timedelta(days=days), days

    match = re.search(r"\b(?:with?in|in|after|next)\s+(\d{1,3})\s*(day|week|month)s?\b", lowered)
    if match:
        count = int(match.group(1))
        unit = match.group(2)
        days = count * {"day": 1, "week": 7, "month": 30}[unit]
        return base + timedelta(days=days), days

    match = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", lowered)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3))), None
        except ValueError:
            pass

    match = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", lowered)
    if match:
        day, month = int(match.group(1)), int(match.group(2))
        year = match.group(3)
        if 1 <= month <= 12 and 1 <= day <= 31:
            if year:
                year_int = int(year)
                year_int += 2000 if year_int < 100 else 0
                try:
                    return date(year_int, month, day), None
                except ValueError:
                    pass
            else:
                return _month_day(month, day, base), None

    match = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]{3,9})\b", lowered)
    if match and match.group(2) in MONTHS:
        return _month_day(MONTHS[match.group(2)], int(match.group(1)), base), None

    match = re.search(r"\b([a-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?\b", lowered)
    if match and match.group(1) in MONTHS:
        return _month_day(MONTHS[match.group(1)], int(match.group(2)), base), None

    return None, None


def extract_wait(text: str) -> tuple[bool | None, int | None]:
    """Flexibility answer -> (can_wait, extra days)."""
    lowered = text.lower()
    match = re.search(r"\b(?:wait|hold|delay)\s*(?:for|up to|upto)?\s*(\d{1,3})\s*(day|week)s?\b", lowered)
    if match:
        days = int(match.group(1)) * (7 if match.group(2) == "week" else 1)
        return True, days
    match = re.search(r"\b(\d{1,2})\s*[-–to]+\s*(\d{1,2})\s*days?\b", lowered)
    if match:
        return True, int(match.group(2))
    if re.search(r"\bno,? i need it\b|\bcan'?t wait\b|\bcannot wait\b|\burgent\b|\bimmediately\b", lowered):
        return False, 0
    if MAYBE.search(lowered):
        return True, 4
    if NEGATIVE.search(lowered) and not AFFIRMATIVE.search(lowered):
        return False, 0
    if AFFIRMATIVE.search(lowered):
        return True, 7
    return None, None


def extract_bool(text: str) -> bool | None:
    if AFFIRMATIVE.search(text) and not NEGATIVE.search(text):
        return True
    if NEGATIVE.search(text):
        return False
    return None


def extract_name(text: str, expecting_name: bool = False) -> str | None:
    match = re.search(r"\b(?:my name is|i am|i'm|this is|myself|name[:\-]?)\s+([A-Za-z][A-Za-z\s\.']{1,40})", text, re.I)
    if match:
        return clean_name(match.group(1))
    if expecting_name:
        stripped = re.sub(r"[^A-Za-z\s\.'\-]", " ", text).strip()
        if stripped and len(stripped.split()) <= 4:
            return clean_name(stripped)
    return None


#: Answers that mean "I'm not telling you" rather than a real value.
FILLER = re.compile(
    r"^(skip|no|none|na|n/?a|nope|nothing|not sure|dunno|dont know|don't know|"
    r"no idea|whatever|any|anything|idk|pass|later|maybe)$",
    re.I,
)


def _is_filler(text: str) -> bool:
    return bool(FILLER.fullmatch(text.strip()))


def match_choice(text: str, slot: catalog.Slot) -> str | None:
    """Resolve a message against a slot's chips and synonyms."""
    lowered = text.lower().strip()
    for value, patterns in slot.synonyms.items():
        for pattern in patterns:
            if re.search(pattern, lowered, re.I):
                return value
    for chip in slot.chips:
        if "{" in chip:
            continue
        if lowered == chip.lower() or re.search(rf"\b{re.escape(chip.lower())}\b", lowered):
            return chip
    return None


# --------------------------------------------------------------------------- #
# message-level intent
# --------------------------------------------------------------------------- #
def detect_command(text: str) -> str | None:
    """A steering instruction rather than an answer to the current question.

    Order matters: "cancel my current request" must read as a cancellation, not
    as a request to view requests.
    """
    if not text or not text.strip():
        return None
    if CANCEL_PATTERNS.search(text):
        return "cancel"
    if SHOW_PAST_PATTERNS.search(text):
        return "show_past"
    if CHANGE_PRODUCT_PATTERNS.search(text):
        return "change_product"
    if RESTART_PATTERNS.search(text):
        return "restart"
    if EXIT_PATTERNS.search(text):
        return "exit"
    return None


def detect_message_intent(text: str) -> str | None:
    command = detect_command(text)
    if command:
        return command
    if READY_PATTERNS.search(text):
        return "ready_to_buy"
    if HELP_PATTERNS.search(text):
        return "explain"
    if STOP_PATTERNS.search(text):
        return "cancel"
    if SHARE_PATTERNS.search(text) and len(text.split()) <= 6:
        return "share"
    return None


# --------------------------------------------------------------------------- #
# main entry point
# --------------------------------------------------------------------------- #
def extract(text: str, state: dict[str, Any], expecting: str | None = None) -> dict[str, Any]:
    """Pull every grounded value out of `text`.

    Returns only newly-found slots. `expecting` is the slot the bot just asked
    about, which makes short replies ("2", "yes", "Satellite") interpretable.
    """
    found: dict[str, Any] = {}
    if not text or not text.strip():
        return found

    text = text.strip()
    category = catalog.get(state.get("category"))

    intent = detect_message_intent(text)
    if intent:
        found["message_intent"] = intent

    # --- product routing ---------------------------------------------------
    if not category:
        detected = catalog.detect(text)
        if detected:
            found["category"] = detected
            category = catalog.get(detected)

    slots = {s.name: s for s in category.slots} if category else {}

    # --- the slot we explicitly asked about --------------------------------
    if expecting:
        value = _extract_for_slot(text, expecting, slots.get(expecting), state, category)
        if value is not None:
            found.update(value)

    # --- opportunistic sweep across everything else ------------------------
    mobile = extract_mobile(text)
    if mobile and not state.get("mobile"):
        found["mobile"] = mobile

    quantity = extract_quantity(text, category)
    if quantity and "quantity" not in found:
        found["quantity"] = quantity

    city = extract_city(text)
    if city and not state.get("city"):
        found["city"] = city

    area = extract_area(text, city or state.get("city"))
    if area and not state.get("area") and "area" not in found:
        found["area"] = area

    if category:
        for name, slot in slots.items():
            if name in found or state.get(name) not in (None, ""):
                continue
            if slot.kind in ("choice",) or slot.synonyms:
                # Skip bool slots here: a bare "yes" belongs to the asked slot.
                if slot.kind == "bool":
                    continue
                value = match_choice(text, slot)
                if value is not None:
                    found[name] = value

    if not state.get("desired_purchase_date") and "desired_purchase_date" not in found:
        when, _ = extract_date(text)
        if when:
            found["desired_purchase_date"] = str(when)

    if not state.get("budget") and "budget" not in found:
        budget = extract_budget(text)
        if budget:
            found["budget"] = budget

    name = extract_name(text, expecting_name=(expecting == "name"))
    if name and not state.get("name") and "name" not in found:
        found["name"] = name

    return found


def _extract_for_slot(
    text: str,
    slot_name: str,
    slot: catalog.Slot | None,
    state: dict[str, Any],
    category: catalog.Category | None,
) -> dict[str, Any] | None:
    """Interpretation biased by the question the bot just asked."""
    if slot_name == "quantity":
        value = extract_quantity(text, category) or extract_bare_number(text, category)
        return {"quantity": value} if value else None

    if slot_name == "mobile":
        value = extract_mobile(text)
        return {"mobile": value} if value else None

    if slot_name == "name":
        if _is_filler(text.strip()):
            return None
        value = extract_name(text, expecting_name=True)
        return {"name": value} if value else None

    if slot_name == "city":
        city = extract_city(text)
        if city:
            return {"city": city}
        # Accept an unknown city name, but never a filler word -- "skip" must
        # not become a city and spawn a group of its own.
        cleaned = re.sub(r"[^A-Za-z\s]", " ", text).strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        if _is_filler(cleaned):
            return None
        if 1 < len(cleaned) <= 30 and len(cleaned.split()) <= 3:
            return {"city": cleaned.title()}
        return None

    if slot_name == "area":
        area = extract_area(text, state.get("city"))
        if area:
            return {"area": area}
        cleaned = re.sub(r"[^A-Za-z0-9\s\-]", " ", text).strip()
        if _is_filler(cleaned):
            return None
        if 1 < len(cleaned) <= 40:
            return {"area": cleaned.title()}
        return None

    if slot_name == "desired_purchase_date":
        when, days = extract_date(text)
        if when:
            out: dict[str, Any] = {"desired_purchase_date": str(when)}
            if days is not None:
                out["purchase_period"] = text.strip()
            return out
        return None

    if slot_name == "can_wait":
        can_wait, days = extract_wait(text)
        if can_wait is None:
            return None
        out = {"can_wait": can_wait, "wait_days": days or 0}
        desired = state.get("desired_purchase_date")
        if desired:
            base = date.fromisoformat(str(desired)[:10])
            out["maximum_purchase_date"] = str(base + timedelta(days=days or 0))
        return out

    if slot is None:
        return None

    if slot.kind == "bool":
        value = extract_bool(text)
        if value is None and slot.synonyms:
            choice = match_choice(text, slot)
            if choice in ("yes", "no"):
                value = choice == "yes"
        return {slot_name: value} if value is not None else None

    if slot.kind == "number":
        if re.search(r"\bskip\b|\bno\b|\bnot sure\b", text, re.I):
            return {slot_name: None}
        value = extract_budget(text) or extract_bare_number(text)
        return {slot_name: value} if value else None

    value = match_choice(text, slot)
    if value is not None:
        return {slot_name: value}
    if slot.freeform:
        cleaned = re.sub(r"[^A-Za-z0-9\s\-&']", " ", text).strip()
        if 1 < len(cleaned) <= 30 and len(cleaned.split()) <= 3:
            return {slot_name: cleaned.title()}
    return None
