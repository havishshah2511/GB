"""Product taxonomy from the Magaao category brief.

1,366 products across 102 procurement families. It does two jobs:

1. **Canonicalisation.** "20 cassette ac", "Cassette A/C", "cassete AC" all
   resolve to the catalogue entry *Cassette AC*, so buyers of the same thing
   pool together instead of fragmenting on spelling. This matters far more here
   than in a two-category world: "MCB" and "MCBs" and "mcb switch" must be one
   group.

2. **Separation.** A split AC and a cassette AC are both air conditioning but
   are not the same purchase, and a supplier quotes them differently. The
   taxonomy keeps them apart while `family` still lets the back office roll
   demand up per procurement family.

Matching is longest-token-overlap against a normalised index, deliberately
conservative: an unrecognised product still works (it falls back to the raw
normalised name), it just doesn't get a family.
"""
from __future__ import annotations

import difflib
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ..utils import normalise_product

_DATA = Path(__file__).with_name("taxonomy.json")


@dataclass(frozen=True)
class Match:
    product: str        # canonical catalogue name, e.g. "Cassette AC"
    family: str         # e.g. "COMMERCIAL HVAC & COOLING"
    family_letter: str
    score: int | None   # the brief's opportunity score for the family
    key: str            # normalised grouping key, e.g. "cassette ac"


def _load() -> dict:
    if not _DATA.exists():
        return {"families": []}
    return json.loads(_DATA.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _index() -> dict[str, Match]:
    """normalised product name -> Match. Built once, then cached."""
    index: dict[str, Match] = {}
    for family in _load().get("families", []):
        if family.get("kind") != "product":
            continue
        for product in family["products"]:
            key = normalise_product(product)
            if not key or key in index:
                continue
            index[key] = Match(
                product=product,
                family=family["name"],
                family_letter=family["letter"],
                score=family.get("score"),
                key=key,
            )
    return index


@lru_cache(maxsize=1)
def _by_length() -> list[tuple[str, Match]]:
    """Longest keys first so "cassette ac" wins over "ac"."""
    return sorted(_index().items(), key=lambda kv: -len(kv[0].split()))


@lru_cache(maxsize=1)
def events() -> list[str]:
    """Procurement events from the brief ("Restaurant setup") -- not products,
    kept for a future "what are you opening?" flow."""
    return [f["name"] for f in _load().get("families", []) if f.get("kind") == "event"]


def families() -> list[dict]:
    return [f for f in _load().get("families", []) if f.get("kind") == "product"]


#: Spellings customers actually type, mapped onto the catalogue's wording.
ALIASES = {
    "ac": "air conditioner", "a c": "air conditioner", "a/c": "air conditioner",
    "acs": "air conditioner", "aircon": "air conditioner",
    "cctv camera": "cctv", "cc tv": "cctv", "camera": "cctv",
    "mcb switch": "mcb", "led light": "lighting", "led bulb": "lighting",
    "led": "lighting", "bulb": "lighting", "tube light": "lighting",
    "genset": "diesel generator",
    "dg set": "diesel generator", "solar plate": "solar panels",
    "solar panel": "solar panels", "invertor": "inverter",
    "ro plant": "ro plants", "water purifier": "ro plants",
    "chair": "office chairs", "table": "desks", "computer": "desktops",
    "laptop": "laptops", "printer": "printers", "ups": "ups",
}


def _apply_aliases(key: str) -> str:
    if key in ALIASES:
        return normalise_product(ALIASES[key])
    return key


def match(text: str | None) -> Match | None:
    """Best catalogue entry for a free-text product name, or None."""
    key = _apply_aliases(normalise_product(text))
    if not key:
        return None

    index = _index()
    if key in index:
        return index[key]

    # Longest known product name contained in what they typed.
    words = key.split()
    for candidate, entry in _by_length():
        parts = candidate.split()
        if len(parts) > len(words):
            continue
        if _contains(words, parts):
            return entry

    # Reverse: they typed something shorter than the catalogue entry
    # ("racks" -> "storage racks") -- only when it is unambiguous.
    hits = [e for c, e in _by_length() if _contains(c.split(), words)]
    if len({h.product for h in hits}) == 1:
        return hits[0]

    # Last resort: a near-miss spelling ("cassete ac"). Deliberately strict --
    # a wrong match here would pool two different products, which is worse
    # than not recognising one.
    close = difflib.get_close_matches(key, list(index), n=1, cutoff=0.88)
    if close:
        return index[close[0]]
    return None


def _contains(haystack: list[str], needle: list[str]) -> bool:
    """Is `needle` a contiguous run inside `haystack`?"""
    n = len(needle)
    return any(haystack[i:i + n] == needle for i in range(len(haystack) - n + 1))


def canonical_product(text: str | None) -> str:
    """Catalogue name when recognised, otherwise the customer's own words
    normalised. Never returns empty for non-empty input."""
    found = match(text)
    if found:
        return found.product
    return normalise_product(text)


def stats() -> dict[str, int]:
    return {
        "families": len(families()),
        "products": len(_index()),
        "events": len(events()),
    }
