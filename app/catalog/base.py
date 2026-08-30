"""Category definition primitives.

Adding a new product category means writing one module that declares its slots
and price slabs -- the conversation engine, matching engine, pricing engine and
admin dashboard are all driven from these declarations.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ..utils import normalise_product

#: Units that read the same at any quantity ("1 kg", "100 kg").
_INVARIANT_UNITS = {"kg", "litre", "ml", "ton", "quintal", "metre", "ft", "sq ft"}


@dataclass(frozen=True)
class Slot:
    """One piece of information the bot may collect."""

    name: str
    question: str
    priority: int
    kind: str = "choice"          # choice | number | text | date | bool | mobile | name
    chips: tuple[str, ...] = ()
    # value -> regex fragments that imply that value, used by the rules extractor
    synonyms: dict[str, tuple[str, ...]] = field(default_factory=dict)
    required: bool = True
    grouping: bool = False        # part of the group's spec signature
    label: str = ""               # human label for summaries / admin
    unit: str = ""
    # Only ask when this returns True for the current slot bag.
    ask_if: Callable[[dict[str, Any]], bool] | None = None
    # Free-text answers are accepted for this slot even if chips are offered.
    freeform: bool = False
    # How long a free-text answer may be. Product names need more room than a
    # brand ("recycled packaging boxes 12x12" vs "Daikin").
    max_words: int = 3
    max_chars: int = 30
    help_text: str = ""

    def display_label(self) -> str:
        return self.label or self.name.replace("_", " ").title()

    def should_ask(self, state: dict[str, Any]) -> bool:
        if self.ask_if is not None and not self.ask_if(state):
            return False
        return True


@dataclass(frozen=True)
class Slab:
    minimum_qty: int
    maximum_qty: int | None
    price: float


@dataclass
class Category:
    key: str                      # "AC"
    label: str                    # "Air Conditioner"
    emoji: str
    unit: str                     # "AC" / "kg" -- how quantity is counted
    unit_plural: str              # "ACs" / "kg"
    quantity_question: str
    quantity_chips: tuple[str, ...]
    slots: tuple[Slot, ...]
    # spec values that define a distinct buying group, in signature order
    grouping_fields: tuple[str, ...]
    # product_key -> slabs; product_key is built by `product_key()`
    slabs: dict[str, tuple[Slab, ...]]
    default_slab_key: str
    # what "Not Sure" resolves to when a group has to be created
    grouping_defaults: dict[str, str] = field(default_factory=dict)
    # Where "how many?" sits among the slot priorities. The default puts it
    # before every specification question, which suits products people count
    # first ("I need 2 AC"). Raise it for products where the specification has
    # to be settled before a quantity means anything (plywood).
    quantity_priority: int = 15
    # words/regex that route a free-text message to this category
    triggers: tuple[str, ...] = ()
    # Regexes that VETO a trigger match. A dedicated flow should only claim the
    # products it can actually ask about and price -- "cassette AC" matches the
    # AC trigger but the AC flow only knows split and window units, and there
    # are no slabs for a cassette. Vetoed text falls through to the open-ended
    # category, where it pools by product name and waits for a real quote.
    exclusions: tuple[str, ...] = ()
    # (regex capturing a number, multiplier to convert into `unit`)
    quantity_patterns: tuple[tuple[str, float], ...] = ()
    min_group_quantity: int = 1
    intro: str = ""
    # slot names holding the brand preference and the brand-flexibility answer
    brand_field: str = ""
    flex_field: str = "brand_flexible"
    # Noun used when naming the product ("1.5 Ton Split Inverter **AC**",
    # "200-300 L Double Door **Refrigerator**"). Defaults to the counting unit.
    product_noun: str = ""
    # An open category has no fixed product list: the customer names the
    # product and it is normalised into the grouping key. Such groups start
    # with no price slabs -- quantity pools while an operator negotiates.
    open_ended: bool = False
    # Extra cards this category contributes once a requirement is captured,
    # e.g. solar's subsidy estimate. Keeps category specifics out of the
    # conversation engine. Signature: (state, facts) -> list of cards.
    extra_cards: Callable[[dict[str, Any], dict[str, Any]], list[dict[str, Any]]] | None = None

    def noun(self) -> str:
        return self.product_noun or self.unit

    # -- spec helpers ------------------------------------------------------ #
    def spec_slots(self) -> tuple[Slot, ...]:
        return tuple(s for s in self.slots if s.grouping)

    def spec_from_state(self, state: dict[str, Any]) -> dict[str, Any]:
        """The subset of collected values that describes the product itself."""
        spec: dict[str, Any] = {}
        for slot in self.slots:
            value = state.get(slot.name)
            if value not in (None, "", []):
                spec[slot.name] = value
        return spec

    @staticmethod
    def is_wildcard(value: Any) -> bool:
        return value in (None, "", []) or str(value).strip().lower() in (
            "not sure", "no preference", "any", "doesn't matter", "unknown",
        )

    def grouping_value(self, spec: dict[str, Any], name: str) -> str | None:
        """The value used for matching. 'Not Sure' answers are wildcards."""
        value = spec.get(name)
        return None if self.is_wildcard(value) else str(value).strip()

    def resolve_spec(self, spec: dict[str, Any]) -> dict[str, Any]:
        """Fill wildcard grouping fields with the category defaults so a brand
        new group always has a concrete, priceable specification."""
        resolved = dict(spec)
        by_name = {s.name: s for s in self.slots}
        for name in self.grouping_fields:
            if self.grouping_value(spec, name) is not None:
                continue
            slot = by_name.get(name)
            default = self.grouping_defaults.get(name)
            # A field the flow deliberately skipped (e.g. inverter on a window
            # AC) stays unset rather than picking up a default.
            if default and (slot is None or slot.should_ask(resolved)):
                resolved[name] = default
            else:
                resolved.pop(name, None)
        return resolved

    def canonical(self, value: str | None) -> str:
        """The comparable form of a grouping value. Open categories normalise
        free text so "2 Office Chairs!" and "office chair" are one group.

        Where the taxonomy recognises the product, its catalogue name wins:
        "cassette a/c" and "Cassette AC" then pool, while a cassette and a
        split AC — different purchases, quoted differently — stay apart.
        """
        if value is None:
            return ""
        if self.open_ended:
            from .taxonomy import match as taxonomy_match

            found = taxonomy_match(value)
            return found.key if found else normalise_product(value)
        return str(value).strip().lower()

    def signature(self, spec: dict[str, Any]) -> str:
        parts = [self.key]
        for name in self.grouping_fields:
            value = self.canonical(self.grouping_value(spec, name)) or "any"
            parts.append(value.replace(" ", "_"))
        return "|".join(parts)

    def product_key(self, spec: dict[str, Any]) -> str:
        """Key into the slab template table. Falls back by progressively
        relaxing the least significant grouping fields."""
        values = [self.grouping_value(spec, n) for n in self.grouping_fields]
        for drop in range(len(values) + 1):
            trial = values[: len(values) - drop] + [None] * drop
            key = "|".join(
                [self.key] + [(v or "any").lower().replace(" ", "_") for v in trial]
            )
            if key in self.slabs:
                return key
        return self.default_slab_key

    def spec_description(self, spec: dict[str, Any]) -> str:
        """Short human string, e.g. '1.5 Ton Split Inverter AC'."""
        bits = [self.grouping_value(spec, name) for name in self.grouping_fields]
        bits = [b for b in bits if b]
        if self.open_ended:
            # Label by the catalogue's wording where it knows the product, so a
            # group reads "Cassette AC" rather than whatever the first buyer
            # happened to type. The product name IS the noun here; appending
            # "unit" would give "Office Chair unit".
            from .taxonomy import canonical_product

            named = [canonical_product(b) for b in bits]
            return " ".join(n.title() if n.islower() else n for n in named if n).strip()
        return " ".join(bits + [self.noun()]).strip()

    def qty_label(self, qty: float, unit: str | None = None) -> str:
        """`unit` overrides the category default -- an open product is counted
        in whatever the customer named (kg, boxes, litres...)."""
        qty_str = f"{qty:g}"
        counted = (unit or "").strip() or self.unit
        # Mass/volume/measure units are already plural-neutral ("100 kg").
        if counted != self.unit or counted in _INVARIANT_UNITS:
            return f"{qty_str} {counted}"
        if self.unit in _INVARIANT_UNITS:
            return f"{qty_str} {self.unit}"
        return f"{qty_str} {self.unit if qty == 1 else self.unit_plural}"

    def slabs_for(self, spec: dict[str, Any]) -> tuple[Slab, ...]:
        return self.slabs[self.product_key(spec)]

    # -- brand helpers ----------------------------------------------------- #
    def brand_of(self, spec: dict[str, Any]) -> str | None:
        if not self.brand_field:
            return None
        value = spec.get(self.brand_field)
        return None if self.is_wildcard(value) else str(value).strip()

    def brand_flexible(self, spec: dict[str, Any]) -> bool:
        """A buyer with no brand preference is flexible by definition."""
        if self.brand_of(spec) is None:
            return True
        return bool(spec.get(self.flex_field))
