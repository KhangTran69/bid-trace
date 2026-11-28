"""Password hashing and session-based sign-in for the authenticated demo mode."""

import logging
from typing import Annotated

import bcrypt
from fastapi import Depends, HTTPException, Request

from app.models import User
from app.routes.deps import SessionDep

logger = logging.getLogger("bidtrace")

SESSION_USER_KEY = "user_id"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def require_user(request: Request, session: SessionDep) -> User | None:
    """Dependency resolving the signed-in reviewer.

    With ``Settings.auth_enabled`` disabled, anonymous demo access is allowed
    and the returned ``None`` maps to the hardcoded demo reviewer. With auth
    enabled, anonymous requests are redirected to the sign-in page and stale
    sessions are cleared.
    """
    settings = request.app.state.settings
    if not settings.auth_enabled:
        return None
    user_id = request.session.get(SESSION_USER_KEY)
    if user_id is None:
        raise HTTPException(
            status_code=303,
            headers={"Location": "/login"},
            detail="Sign in to continue.",
        )
    user = session.get(User, user_id)
    if user is None:
        request.session.clear()
        raise HTTPException(
            status_code=303,
            headers={"Location": "/login"},
            detail="Sign in to continue.",
        )
    return user


UserDep = Annotated[User | None, Depends(require_user)]


def actor_for(user: User | None) -> str:
    """Audit attribution for the resolved user (demo reviewer when auth is off)."""
    return user.username if user is not None else "demo-reviewer"
