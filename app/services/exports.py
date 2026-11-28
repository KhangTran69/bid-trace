import csv
from decimal import Decimal
from io import StringIO

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, joinedload

from app.models import Bid, BidLineItem
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

SUMMARY_HEADERS = (
    "bid_id",
    "project_name",
    "vendor_name",
    "status",
    "item_count",
    "approved_items",
    "total_reviewed_amount",
)


def _safe_text(value: str) -> str:
    stripped = value.lstrip(" \t\r\n")
    if stripped.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _money(value: object) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value)).quantize(Decimal("0.01"))


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


def export_bids_summary_csv(session: Session) -> str:
    """One row per bid with review progress and totals; no approval gating."""
    rows = session.execute(
        select(
            Bid.id,
            Bid.project_name,
            Bid.vendor_name,
            Bid.status,
            func.count(BidLineItem.id),
            func.sum(case((BidLineItem.status == "approved", 1), else_=0)),
            func.coalesce(
                func.sum(BidLineItem.reviewed_quantity * BidLineItem.reviewed_unit_price), 0
            ),
        )
        .outerjoin(BidLineItem, BidLineItem.bid_id == Bid.id)
        .group_by(Bid.id)
        .order_by(Bid.id)
    ).all()

    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow(SUMMARY_HEADERS)
    for bid_id, project_name, vendor_name, status, item_count, approved, amount in rows:
        writer.writerow(
            (
                bid_id,
                _safe_text(project_name),
                _safe_text(vendor_name),
                status,
                item_count,
                approved or 0,
                _money(amount),
            )
        )
    return output.getvalue()
