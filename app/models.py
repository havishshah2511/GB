"""Request/response schemas for the HTTP API."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# chat
# --------------------------------------------------------------------------- #
class ChatMessageIn(BaseModel):
    session_id: str = Field(min_length=4, max_length=64)
    message: str = ""
    ref: str | None = None
    group: str | None = None


# --------------------------------------------------------------------------- #
# intents
# --------------------------------------------------------------------------- #
class IntentIn(BaseModel):
    category: str
    quantity: float = Field(gt=0)
    city: str
    area: str | None = None
    name: str | None = None
    mobile: str | None = None
    desired_purchase_date: str | None = None
    maximum_purchase_date: str | None = None
    can_wait: bool = False
    budget: float | None = None
    specifications: dict[str, Any] = Field(default_factory=dict)
    conversation_id: str | None = None
    referral_code: str | None = None

    def to_state(self) -> dict[str, Any]:
        state = self.model_dump(exclude={"specifications", "conversation_id", "referral_code"})
        state.update(self.specifications)
        return state


class IntentPatch(BaseModel):
    quantity: float | None = None
    area: str | None = None
    city: str | None = None
    desired_purchase_date: str | None = None
    maximum_purchase_date: str | None = None
    can_wait: bool | None = None
    budget: float | None = None
    status: str | None = None
    intent_strength: str | None = None
    group_id: str | None = None
    specifications: dict[str, Any] | None = None
    rematch: bool = False


class ReconfirmIn(BaseModel):
    still_interested: bool = True
    new_date: str | None = None


# --------------------------------------------------------------------------- #
# groups
# --------------------------------------------------------------------------- #
class JoinGroupIn(BaseModel):
    intent_id: str


class SlabIn(BaseModel):
    minimum_qty: int = Field(ge=1)
    maximum_qty: int | None = None
    price: float = Field(gt=0)
    price_status: str = "indicative"
    supplier_id: str | None = None


class SlabsIn(BaseModel):
    slabs: list[SlabIn]


class SupplierConfirmIn(BaseModel):
    confirmed: bool = True
    supplier_id: str | None = None


class BroadcastIn(BaseModel):
    message: str = Field(min_length=1)
    channel: str | None = None


class MergeIn(BaseModel):
    source_group_id: str
    target_group_id: str


class SplitIn(BaseModel):
    intent_ids: list[str]
    match_mode: str | None = None


class MoveIntentIn(BaseModel):
    intent_id: str
    target_group_id: str


# --------------------------------------------------------------------------- #
# referrals
# --------------------------------------------------------------------------- #
class ReferralIn(BaseModel):
    customer_id: str
    group_id: str
