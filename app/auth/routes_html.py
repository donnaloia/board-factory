"""Auth HTML pages — login, registration, forgot-password forms."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from auth import services as auth_services
from infrastructure import deps

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
def login_view(
    request: Request,
    next: str | None = None,
    error: str | None = None,
    info: str | None = None,
):
    if auth_services.is_setup_required():
        return RedirectResponse("/register", status_code=303)
    return request.app.state.templates.TemplateResponse(
        request,
        "auth_login.html",
        {"next": deps.safe_next(next), "error": error, "info": info},
    )


@router.get("/register", response_class=HTMLResponse)
def register_view(request: Request, error: str | None = None):
    return request.app.state.templates.TemplateResponse(
        request, "auth_register.html", {"error": error}
    )


@router.get("/forgot-password", response_class=HTMLResponse)
def forgot_view(request: Request, sent: bool = False):
    return request.app.state.templates.TemplateResponse(
        request, "auth_forgot.html", {"sent": sent}
    )
