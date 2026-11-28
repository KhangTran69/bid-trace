"""Shared FastAPI dependencies and query helpers for route modules."""

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Bid


def session_dependency(request: Request) -> Session:
    with request.app.state.session_factory() as session:
        yield session


SessionDep = Annotated[Session, Depends(session_dependency)]


KNOWN_BID_STATUSES = ("needs_review", "approved")


def list_bids_desc(
    session: Session, *, q: str | None = None, status: str | None = None
) -> list[Bid]:
    """Bids newest first, optionally filtered by search text and status."""
    query = select(Bid).order_by(Bid.created_at.desc(), Bid.id.desc())
    if status in KNOWN_BID_STATUSES:
        query = query.where(Bid.status == status)
    if q:
        needle = f"%{q.strip()}%"
        query = query.where(Bid.project_name.ilike(needle) | Bid.vendor_name.ilike(needle))
    return list(session.scalars(query).all())
