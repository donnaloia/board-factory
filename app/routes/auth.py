"""Login, logout, registration, forgot-password."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from auth import services as auth_services
from routes import deps

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


@router.post("/login")
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form(default="/"),
):
    user = auth_services.find_by_email(email)
    if user is None or not auth_services.verify_password(user, password):
        return RedirectResponse(
            f"/login?next={deps.safe_next(next)}&error=Invalid+email+or+password",
            status_code=303,
        )
    cookie = auth_services.create_session_cookie(user.id)
    auth_services.touch_last_login(user.id)
    response = RedirectResponse(deps.safe_next(next), status_code=303)
    response.set_cookie(
        auth_services.COOKIE_NAME,
        cookie,
        httponly=True,
        samesite="lax",
        max_age=auth_services.SESSION_TTL_SEC,
    )
    return response


@router.post("/logout")
def logout_submit(request: Request):
    cookie_value = request.cookies.get(auth_services.COOKIE_NAME)
    auth_services.destroy_session_cookie(cookie_value)
    response = RedirectResponse("/login?info=Signed+out", status_code=303)
    response.delete_cookie(auth_services.COOKIE_NAME)
    return response


@router.get("/register", response_class=HTMLResponse)
def register_view(request: Request, error: str | None = None):
    return request.app.state.templates.TemplateResponse(
        request, "auth_register.html", {"error": error}
    )


@router.post("/register")
def register_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    display_name: str = Form(default=""),
):
    try:
        user = auth_services.register_user(
            email=email,
            password=password,
            display_name=display_name or None,
        )
    except ValueError as e:
        return RedirectResponse(
            f"/register?error={str(e).replace(' ', '+')}", status_code=303
        )
    cookie = auth_services.create_session_cookie(user.id)
    auth_services.touch_last_login(user.id)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        auth_services.COOKIE_NAME,
        cookie,
        httponly=True,
        samesite="lax",
        max_age=auth_services.SESSION_TTL_SEC,
    )
    return response


@router.get("/forgot-password", response_class=HTMLResponse)
def forgot_view(request: Request, sent: bool = False):
    return request.app.state.templates.TemplateResponse(
        request, "auth_forgot.html", {"sent": sent}
    )


@router.post("/forgot-password")
def forgot_submit(request: Request, email: str = Form(...)):
    return RedirectResponse("/forgot-password?sent=true", status_code=303)
