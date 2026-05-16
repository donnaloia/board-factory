"""Auth HTML pages — login, registration, forgot-password forms."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

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
    setup_required = auth_services.is_setup_required()
    return request.app.state.templates.TemplateResponse(
        request,
        "auth_login.html",
        {
            "next": deps.safe_next(next),
            "error": error,
            "info": info,
            "setup_required": setup_required,
        },
    )


@router.get("/register", response_class=HTMLResponse)
def register_view(request: Request, error: str | None = None):
    return request.app.state.templates.TemplateResponse(
        request,
        "auth_register.html",
        {
            "error": error,
            "setup_required": auth_services.is_setup_required(),
        },
    )


@router.get("/forgot-password", response_class=HTMLResponse)
def forgot_view(request: Request, sent: bool = False):
    return request.app.state.templates.TemplateResponse(
        request, "auth_forgot.html", {"sent": sent}
    )
