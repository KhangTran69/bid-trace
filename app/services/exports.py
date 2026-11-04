import csv
from decimal import Decimal
from io import StringIO

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import Bid
from app.services.errors import Conflict, NotFound

HEADERS = (
    "bid_id",
    "line_item_id",
    "project_name",
    "vendor_name",
    "description",
    "quantity",
    "unit",
    "unit_price",
    "amount",
    "source_filename",
    "source_locator",
)


def _safe_text(value: str) -> str:
    stripped = value.lstrip(" \t\r\n")
    if stripped.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def export_bid_csv(session: Session, bid_id: int) -> str:
    bid = session.execute(
        select(Bid)
        .options(joinedload(Bid.document), joinedload(Bid.line_items))
        .where(Bid.id == bid_id)
    )
    bid = bid.unique().scalar_one_or_none()
    if bid is None:
        raise NotFound("Bid was not found.")
    if (
        bid.status != "approved"
        or not bid.line_items
        or any(item.status != "approved" for item in bid.line_items)
    ):
        raise Conflict("Approve every line item before exporting this bid.")

    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow(HEADERS)
    for item in sorted(bid.line_items, key=lambda row: row.id):
        amount = (item.reviewed_quantity * item.reviewed_unit_price).quantize(Decimal("0.01"))
        writer.writerow(
            (
                bid.id,
                item.id,
                _safe_text(bid.project_name),
                _safe_text(bid.vendor_name),
                _safe_text(item.reviewed_description),
                item.reviewed_quantity,
                _safe_text(item.reviewed_unit),
                item.reviewed_unit_price,
                amount,
                _safe_text(bid.document.filename),
                _safe_text(item.source_locator),
            )
        )
    return output.getvalue()
