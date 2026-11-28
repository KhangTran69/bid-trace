"""Line-item review and approval submission."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth import UserDep, actor_for
from app.models import BidLineItem
from app.routes.bids import render_bid
from app.routes.deps import SessionDep
from app.security import enforce_same_origin
from app.services.errors import Conflict, NotFound
from app.services.reviews import review_line_item

router = APIRouter()


def _item_bid_id_or_404(session: Session, item_id: int, exc: Exception) -> int:
    item = session.get(BidLineItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Line item not found.") from exc
    return item.bid_id


@router.post("/items/{item_id}/review", dependencies=[Depends(enforce_same_origin)])
def save_review(
    request: Request,
    item_id: int,
    expected_version: Annotated[int, Form()],
    action: Annotated[str, Form()],
    description: Annotated[str, Form()],
    quantity: Annotated[str, Form()],
    unit: Annotated[str, Form()],
    unit_price: Annotated[str, Form()],
    session: SessionDep,
    user: UserDep,
):
    try:
        item = review_line_item(
            session,
            item_id=item_id,
            expected_version=expected_version,
            values={
                "description": description,
                "quantity": quantity,
                "unit": unit,
                "unit_price": unit_price,
            },
            action=action,
            actor=actor_for(user),
        )
    except NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Conflict as exc:
        session.rollback()
        return render_bid(
            request,
            session,
            _item_bid_id_or_404(session, item_id, exc),
            user=user,
            error=str(exc),
            status_code=409,
        )
    except ValueError as exc:
        session.rollback()
        return render_bid(
            request,
            session,
            _item_bid_id_or_404(session, item_id, exc),
            user=user,
            error=str(exc),
            status_code=422,
        )
    return RedirectResponse(f"/bids/{item.bid_id}", status_code=303)
