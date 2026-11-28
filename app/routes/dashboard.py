"""Review-progress dashboard."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.auth import UserDep
from app.routes.deps import SessionDep
from app.services.analytics import collect_dashboard_stats
from app.templating import TEMPLATES

router = APIRouter()


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, session: SessionDep, user: UserDep):
    stats = collect_dashboard_stats(session)
    return TEMPLATES.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"stats": stats, "user": user},
    )
