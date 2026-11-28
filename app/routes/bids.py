"""Home page and bid-detail views."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.auth import UserDep
from app.models import Bid, User
from app.routes.deps import SessionDep, list_bids_desc
from app.templating import TEMPLATES

router = APIRouter()


def render_bid(
    request: Request,
    session: Session,
    bid_id: int,
    *,
    user: User | None = None,
    error: str | None = None,
    status_code: int = 200,
):
    bid = session.scalar(
        select(Bid)
        .options(selectinload(Bid.document), selectinload(Bid.line_items))
        .where(Bid.id == bid_id)
    )
    if bid is None:
        raise HTTPException(status_code=404, detail="Bid not found.")
    return TEMPLATES.TemplateResponse(
        request=request,
        name="bid.html",
        context={
            "bid": bid,
            "items": sorted(bid.line_items, key=lambda item: item.id),
            "user": user,
            "error": error,
        },
        status_code=status_code,
    )


@router.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    session: SessionDep,
    user: UserDep,
    q: Annotated[str, Query(max_length=160)] = "",
    status: Annotated[str, Query(max_length=32)] = "",
):
    return TEMPLATES.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "bids": list_bids_desc(session, q=q.strip() or None, status=status or None),
            "user": user,
            "q": q.strip(),
            "status": status,
        },
    )


@router.get("/bids/{bid_id}", response_class=HTMLResponse)
def bid_detail(request: Request, bid_id: int, session: SessionDep, user: UserDep):
    return render_bid(request, session, bid_id, user=user)
