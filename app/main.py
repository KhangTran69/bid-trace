from contextlib import asynccontextmanager
from hashlib import sha256
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import Settings
from app.db import make_engine, make_session_factory
from app.models import Bid, BidLineItem, SourceDocument
from app.services.errors import Conflict, NotFound
from app.services.exports import export_bid_csv
from app.services.imports import import_bid
from app.services.reviews import review_line_item

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
LOCAL_REVIEW_ORIGINS = frozenset(
    {
        ("http", "localhost", 8000),
        ("http", "127.0.0.1", 8000),
    }
)


def _origin_tuple(value: str) -> tuple[str, str, int] | None:
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            return None
        port = parsed.port
        if port is None:
            port = 443 if parsed.scheme == "https" else 80
    except ValueError:
        return None
    return parsed.scheme, parsed.hostname.lower(), port


def _reject_cross_site_review(request: Request) -> None:
    if request.headers.get("sec-fetch-site", "").lower() == "cross-site":
        raise HTTPException(status_code=403, detail="Cross-site review requests are not allowed.")

    origin = request.headers.get("origin")
    if origin is None:
        return

    request_host = request.headers.get("host", "")
    expected_origin = _origin_tuple(f"http://{request_host}")
    submitted_origin = _origin_tuple(origin)
    if (
        expected_origin not in LOCAL_REVIEW_ORIGINS
        or submitted_origin not in LOCAL_REVIEW_ORIGINS
        or submitted_origin != expected_origin
    ):
        raise HTTPException(status_code=403, detail="Cross-origin review requests are not allowed.")


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or Settings()
    engine = make_engine(resolved_settings.database_url)
    session_factory = make_session_factory(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        engine.dispose()

    app = FastAPI(title="BidTrace", version="0.1.0", lifespan=lifespan)
    app.state.settings = resolved_settings
    app.state.session_factory = session_factory
    app.mount(
        "/static",
        StaticFiles(directory=str(Path(__file__).parent / "static")),
        name="static",
    )

    def session_dependency(request: Request):
        with request.app.state.session_factory() as session:
            yield session

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request, session: Annotated[Session, Depends(session_dependency)]):
        bids = session.scalars(select(Bid).order_by(Bid.created_at.desc(), Bid.id.desc())).all()
        return TEMPLATES.TemplateResponse(
            request=request,
            name="index.html",
            context={"bids": bids, "error": request.query_params.get("error")},
        )

    @app.post("/imports")
    def create_import(
        request: Request,
        project_name: Annotated[str, Form()],
        vendor_name: Annotated[str, Form()],
        file: Annotated[UploadFile, File()],
        session: Annotated[Session, Depends(session_dependency)],
    ):
        content = file.file.read(resolved_settings.max_upload_bytes + 1)
        if len(content) > resolved_settings.max_upload_bytes:
            bids = session.scalars(select(Bid).order_by(Bid.created_at.desc(), Bid.id.desc())).all()
            return TEMPLATES.TemplateResponse(
                request=request,
                name="index.html",
                context={"bids": bids, "error": "Uploads must be 10 MiB or smaller."},
                status_code=400,
            )
        try:
            bid = import_bid(
                session,
                project_name=project_name,
                vendor_name=vendor_name,
                filename=file.filename or "uploaded-bid",
                content=content,
                storage_dir=resolved_settings.upload_dir,
            )
        except ValueError as exc:
            session.rollback()
            bids = session.scalars(select(Bid).order_by(Bid.created_at.desc(), Bid.id.desc())).all()
            return TEMPLATES.TemplateResponse(
                request=request,
                name="index.html",
                context={"bids": bids, "error": str(exc)},
                status_code=400,
            )
        return RedirectResponse(f"/bids/{bid.id}", status_code=303)

    def render_bid(
        request: Request,
        session: Session,
        bid_id: int,
        *,
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
                "error": error,
            },
            status_code=status_code,
        )

    @app.get("/bids/{bid_id}", response_class=HTMLResponse)
    def bid_detail(
        request: Request,
        bid_id: int,
        session: Annotated[Session, Depends(session_dependency)],
    ):
        return render_bid(request, session, bid_id)

    @app.post("/items/{item_id}/review")
    def save_review(
        request: Request,
        item_id: int,
        expected_version: Annotated[int, Form()],
        action: Annotated[str, Form()],
        description: Annotated[str, Form()],
        quantity: Annotated[str, Form()],
        unit: Annotated[str, Form()],
        unit_price: Annotated[str, Form()],
        session: Annotated[Session, Depends(session_dependency)],
    ):
        _reject_cross_site_review(request)
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
            )
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Conflict as exc:
            session.rollback()
            item = session.get(BidLineItem, item_id)
            if item is None:
                raise HTTPException(status_code=404, detail="Line item not found.") from exc
            bid_id = item.bid_id
            return render_bid(request, session, bid_id, error=str(exc), status_code=409)
        except ValueError as exc:
            session.rollback()
            item = session.get(BidLineItem, item_id)
            if item is None:
                raise HTTPException(status_code=404, detail="Line item not found.") from exc
            bid_id = item.bid_id
            return render_bid(request, session, bid_id, error=str(exc), status_code=422)
        return RedirectResponse(f"/bids/{item.bid_id}", status_code=303)

    @app.get("/bids/{bid_id}/export.csv")
    def download_export(
        bid_id: int,
        session: Annotated[Session, Depends(session_dependency)],
    ):
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

    @app.get("/documents/{document_id}")
    def get_document(
        document_id: int,
        session: Annotated[Session, Depends(session_dependency)],
    ):
        document = session.get(SourceDocument, document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Source document not found.")
        upload_root = resolved_settings.upload_dir.resolve()
        source_path = (upload_root / document.storage_key).resolve()
        if upload_root not in source_path.parents or not source_path.is_file():
            return Response(status_code=404)
        try:
            with source_path.open("rb") as source_file:
                content = source_file.read(resolved_settings.max_upload_bytes + 1)
        except OSError:
            return Response(status_code=404)
        if (
            len(content) > resolved_settings.max_upload_bytes
            or sha256(content).hexdigest() != document.sha256
        ):
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

    return app


app = create_app()
