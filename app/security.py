"""Shared request-security helpers: same-origin enforcement and response headers."""

import logging
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, Response

logger = logging.getLogger(__name__)

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; form-action 'self'; base-uri 'self'; frame-ancestors 'none'"
    ),
}


def origin_tuple(value: str) -> tuple[str, str, int] | None:
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


def enforce_same_origin(request: Request) -> None:
    """FastAPI dependency that rejects cross-site state-changing form submissions.

    Non-browser clients that omit both headers remain usable. The allowed
    origins come from ``Settings.allowed_review_origins`` via ``app.state``.
    """
    if request.headers.get("sec-fetch-site", "").lower() == "cross-site":
        logger.warning(
            "Rejected cross-site submission to %s (fetch metadata).", request.url.path
        )
        raise HTTPException(status_code=403, detail="Cross-site submissions are not allowed.")

    origin = request.headers.get("origin")
    if origin is None:
        return

    request_host = request.headers.get("host", "")
    expected_origin = origin_tuple(f"http://{request_host}")
    submitted_origin = origin_tuple(origin)
    allowed = request.app.state.allowed_review_origins
    if (
        expected_origin not in allowed
        or submitted_origin not in allowed
        or submitted_origin != expected_origin
    ):
        logger.warning(
            "Rejected cross-origin submission to %s (origin %.100r).", request.url.path, origin
        )
        raise HTTPException(status_code=403, detail="Cross-origin submissions are not allowed.")


def apply_security_headers(response: Response) -> None:
    """Add hardening headers without clobbering values already set by a handler."""
    for header, value in SECURITY_HEADERS.items():
        response.headers.setdefault(header, value)
