"""Sign-in and sign-out routes."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from app.auth import SESSION_USER_KEY, verify_password
from app.models import User
from app.routes.deps import SessionDep
from app.security import enforce_same_origin
from app.templating import TEMPLATES

logger = logging.getLogger("bidtrace")

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, session: SessionDep):
    settings = request.app.state.settings
    if not settings.auth_enabled:
        raise HTTPException(status_code=404, detail="Authentication is disabled in demo mode.")
    if request.session.get(SESSION_USER_KEY) is not None:
        return RedirectResponse("/", status_code=303)
    return TEMPLATES.TemplateResponse(request=request, name="login.html", context={})


@router.post("/login", dependencies=[Depends(enforce_same_origin)])
def login(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    session: SessionDep,
):
    settings = request.app.state.settings
    if not settings.auth_enabled:
        raise HTTPException(status_code=404, detail="Authentication is disabled in demo mode.")
    user = session.scalar(select(User).where(User.username == username))
    if user is None or not verify_password(password, user.password_hash):
        logger.warning("Failed sign-in attempt for username %.80r.", username)
        return TEMPLATES.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "Invalid username or password."},
            status_code=401,
        )
    request.session[SESSION_USER_KEY] = user.id
    logger.info("User %s signed in.", user.username)
    return RedirectResponse("/", status_code=303)


@router.post("/logout", dependencies=[Depends(enforce_same_origin)])
def logout(request: Request):
    settings = request.app.state.settings
    if not settings.auth_enabled:
        return RedirectResponse("/", status_code=303)
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
