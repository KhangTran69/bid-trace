from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.decimal_limits import (
    QUANTITY_MAX_EXCLUSIVE,
    QUANTITY_SCALE,
    UNIT_PRICE_MAX_EXCLUSIVE,
    UNIT_PRICE_SCALE,
)
from app.models import AuditEvent, Bid, BidLineItem
from app.services.errors import Conflict, NotFound


@dataclass(frozen=True)
class ReviewValues:
    description: str
    quantity: Decimal
    unit: str
    unit_price: Decimal


def validate_values(values: dict[str, object] | ReviewValues) -> ReviewValues:
    if isinstance(values, ReviewValues):
        submitted = values
    else:
        try:
            submitted = ReviewValues(
                description=str(values.get("description", "")).strip(),
                quantity=Decimal(str(values.get("quantity", "")).strip()),
                unit=str(values.get("unit", "")).strip(),
                unit_price=Decimal(str(values.get("unit_price", "")).strip()),
            )
        except (InvalidOperation, ValueError):
            raise ValueError("Quantity and unit price must be valid decimal numbers.") from None
    if not submitted.description or len(submitted.description) > 500:
        raise ValueError("Description must contain 1 to 500 characters.")
    if not submitted.unit or len(submitted.unit) > 32:
        raise ValueError("Unit must contain 1 to 32 characters.")
    if (
        not submitted.quantity.is_finite()
        or submitted.quantity <= 0
        or not submitted.unit_price.is_finite()
        or submitted.unit_price < 0
    ):
        raise ValueError("Quantity must be positive and unit price must be zero or greater.")
    if submitted.quantity.as_tuple().exponent < -QUANTITY_SCALE:
        raise ValueError(f"Quantity supports at most {QUANTITY_SCALE} decimal places.")
    if submitted.unit_price.as_tuple().exponent < -UNIT_PRICE_SCALE:
        raise ValueError(f"Unit price supports at most {UNIT_PRICE_SCALE} decimal places.")
    if (
        submitted.quantity >= QUANTITY_MAX_EXCLUSIVE
        or submitted.unit_price >= UNIT_PRICE_MAX_EXCLUSIVE
    ):
        raise ValueError("Quantity or unit price is too large for this bid demo.")
    return submitted


def _snapshot(item: BidLineItem) -> dict[str, str]:
    return {
        "description": item.reviewed_description,
        "quantity": str(item.reviewed_quantity),
        "unit": item.reviewed_unit,
        "unit_price": str(item.reviewed_unit_price),
        "status": item.status,
        "version": str(item.version),
    }


def review_line_item(
    session: Session,
    *,
    item_id: int,
    expected_version: int,
    values: dict[str, object] | ReviewValues,
    action: Literal["save", "approve"],
    actor: str = "demo-reviewer",
) -> BidLineItem:
    if action not in {"save", "approve"}:
        raise ValueError("Action must be save or approve.")
    submitted = validate_values(values)
    with session.begin():
        locked_bid = None
        if action == "approve":
            bid_id = session.scalar(
                select(BidLineItem.bid_id).where(BidLineItem.id == item_id)
            )
            if bid_id is None:
                raise NotFound("Line item was not found.")
            locked_bid = session.scalar(select(Bid).where(Bid.id == bid_id).with_for_update())
            if locked_bid is None:
                raise NotFound("Bid was not found.")
        item = session.scalar(
            select(BidLineItem).where(BidLineItem.id == item_id).with_for_update()
        )
        if item is None:
            raise NotFound("Line item was not found.")
        if item.version != expected_version:
            raise Conflict("This line item changed since it was opened. Reload before saving.")
        if item.status == "approved":
            raise Conflict("Approved line items cannot be changed in this demo.")

        before_values = _snapshot(item)
        item.reviewed_description = submitted.description
        item.reviewed_quantity = submitted.quantity
        item.reviewed_unit = submitted.unit
        item.reviewed_unit_price = submitted.unit_price
        item.status = "approved" if action == "approve" else "corrected"
        item.version += 1
        session.flush()
        session.add(
            AuditEvent(
                bid_id=item.bid_id,
                line_item_id=item.id,
                entity_type="line_item",
                entity_id=item.id,
                actor=actor,
                action="item_approved" if action == "approve" else "item_corrected",
                before_values=before_values,
                after_values=_snapshot(item),
            )
        )
        if action == "approve":
            remaining = session.scalar(
                select(func.count())
                .select_from(BidLineItem)
                .where(BidLineItem.bid_id == item.bid_id, BidLineItem.status != "approved")
            )
            if remaining == 0:
                locked_bid.status = "approved"
    return item
