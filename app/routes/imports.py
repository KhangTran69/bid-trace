"""Bid import submission."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse

from app.config import MAX_UPLOAD_BYTES
from app.routes.deps import SessionDep, list_bids_desc
from app.security import enforce_same_origin
from app.services.imports import import_bid
from app.templating import TEMPLATES

router = APIRouter()


@router.post("/imports", dependencies=[Depends(enforce_same_origin)])
def create_import(
    request: Request,
    project_name: Annotated[str, Form()],
    vendor_name: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    session: SessionDep,
):
    settings = request.app.state.settings
    content = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "bids": list_bids_desc(session),
                "error": "Uploads must be 10 MiB or smaller.",
            },
            status_code=400,
        )
    try:
        bid = import_bid(
            session,
            project_name=project_name,
            vendor_name=vendor_name,
            filename=file.filename or "uploaded-bid",
            content=content,
            storage_dir=settings.upload_dir,
        )
    except ValueError as exc:
        session.rollback()
        return TEMPLATES.TemplateResponse(
            request=request,
            name="index.html",
            context={"bids": list_bids_desc(session), "error": str(exc)},
            status_code=400,
        )
    return RedirectResponse(f"/bids/{bid.id}", status_code=303)
