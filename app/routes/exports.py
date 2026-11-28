"""Approved CSV export."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.routes.deps import SessionDep
from app.services.errors import Conflict, NotFound
from app.services.exports import export_bid_csv

router = APIRouter()


@router.get("/bids/{bid_id}/export.csv")
def download_export(bid_id: int, session: SessionDep):
    try:
        csv_content = export_bid_csv(session, bid_id)
    except Conflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(
        content=csv_content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="bid-{bid_id}-approved.csv"'},
    )
