"""Integrity-checked source-document downloads."""

import logging
from hashlib import sha256

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from app.auth import require_user
from app.config import MAX_UPLOAD_BYTES
from app.models import SourceDocument
from app.routes.deps import SessionDep

logger = logging.getLogger("bidtrace")

router = APIRouter()


@router.get("/documents/{document_id}", dependencies=[Depends(require_user)])
def get_document(request: Request, document_id: int, session: SessionDep):
    document = session.get(SourceDocument, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Source document not found.")
    upload_root = request.app.state.settings.upload_dir.resolve()
    source_path = (upload_root / document.storage_key).resolve()
    if upload_root not in source_path.parents or not source_path.is_file():
        logger.warning(
            "Source document %s (%s) is missing or outside the upload root.",
            document_id,
            document.storage_key,
        )
        return Response(status_code=404)
    try:
        with source_path.open("rb") as source_file:
            content = source_file.read(MAX_UPLOAD_BYTES + 1)
    except OSError:
        logger.warning("Source document %s could not be read.", document_id)
        return Response(status_code=404)
    if len(content) > MAX_UPLOAD_BYTES or sha256(content).hexdigest() != document.sha256:
        logger.warning(
            "Source document %s failed integrity verification (size %d).",
            document_id,
            len(content),
        )
        return Response(status_code=404)
    media_type = (
        "application/pdf" if source_path.suffix == ".pdf" else "application/octet-stream"
    )
    disposition = "inline" if source_path.suffix == ".pdf" else "attachment"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'{disposition}; filename="{document.filename}"'},
    )
