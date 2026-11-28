"""SQL-side aggregates for the review-progress dashboard."""

from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuditEvent, Bid, BidLineItem


@dataclass(frozen=True)
class DashboardStats:
    bids_by_status: dict[str, int] = field(default_factory=dict)
    items_by_status: dict[str, int] = field(default_factory=dict)
    audit_counts: dict[str, int] = field(default_factory=dict)
    total_extracted_amount: Decimal = Decimal("0")
    total_reviewed_amount: Decimal = Decimal("0")
    recent_events: list[AuditEvent] = field(default_factory=list)
    total_bids: int = 0
    approved_bids: int = 0
    total_items: int = 0
    approved_items: int = 0


def _as_decimal(value: object) -> Decimal:
    # PostgreSQL returns Decimal; SQLite may return float for summed numerics.
    return value if isinstance(value, Decimal) else Decimal(str(value))


def collect_dashboard_stats(session: Session, *, recent_limit: int = 10) -> DashboardStats:
    bids_by_status = dict(
        session.execute(select(Bid.status, func.count()).group_by(Bid.status)).all()
    )
    items_by_status = dict(
        session.execute(
            select(BidLineItem.status, func.count()).group_by(BidLineItem.status)
        ).all()
    )
    audit_counts = dict(
        session.execute(select(AuditEvent.action, func.count()).group_by(AuditEvent.action)).all()
    )
    extracted_total, reviewed_total = session.execute(
        select(
            func.coalesce(
                func.sum(BidLineItem.extracted_quantity * BidLineItem.extracted_unit_price), 0
            ),
            func.coalesce(
                func.sum(BidLineItem.reviewed_quantity * BidLineItem.reviewed_unit_price), 0
            ),
        )
    ).one()
    recent_events = list(
        session.scalars(
            select(AuditEvent)
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            .limit(recent_limit)
        ).all()
    )
    return DashboardStats(
        bids_by_status=bids_by_status,
        items_by_status=items_by_status,
        audit_counts=audit_counts,
        total_extracted_amount=_as_decimal(extracted_total),
        total_reviewed_amount=_as_decimal(reviewed_total),
        recent_events=recent_events,
        total_bids=sum(bids_by_status.values()),
        approved_bids=bids_by_status.get("approved", 0),
        total_items=sum(items_by_status.values()),
        approved_items=items_by_status.get("approved", 0),
    )
