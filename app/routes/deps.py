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


def list_bids_desc(session: Session) -> list[Bid]:
    """All bids, newest first — the single ordering used by list views."""
    return list(session.scalars(select(Bid).order_by(Bid.created_at.desc(), Bid.id.desc())).all())
