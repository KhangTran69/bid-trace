"""Application wiring: engine, middleware, and route registration."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import Settings
from app.db import make_engine, make_session_factory
from app.routes import auth, bids, documents, exports, imports, reviews
from app.security import apply_security_headers, origin_tuple

logger = logging.getLogger("bidtrace")


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or Settings()
    engine = make_engine(resolved_settings.database_url)
    session_factory = make_session_factory(engine)

    if not logging.getLogger().handlers:
        # The Docker image runs uvicorn with its own logger config; add a root
        # handler only when none exists so app logs always reach stderr.
        logging.basicConfig(level=logging.INFO)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        engine.dispose()

    app = FastAPI(title="BidTrace", version="0.1.0", lifespan=lifespan)
    app.state.settings = resolved_settings
    app.state.session_factory = session_factory
    app.state.allowed_review_origins = frozenset(
        parsed
        for origin in resolved_settings.allowed_review_origins
        if (parsed := origin_tuple(origin)) is not None
    )
    app.mount(
        "/static",
        StaticFiles(directory=str(Path(__file__).parent / "static")),
        name="static",
    )
    app.add_middleware(
        SessionMiddleware,
        secret_key=resolved_settings.session_secret,
        same_site="lax",
    )

    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        response = await call_next(request)
        apply_security_headers(response)
        return response

    app.include_router(auth.router)
    app.include_router(bids.router)
    app.include_router(imports.router)
    app.include_router(reviews.router)
    app.include_router(exports.router)
    app.include_router(documents.router)
    return app


app = create_app()
