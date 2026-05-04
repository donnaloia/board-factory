"""Login, logout, registration, forgot-password."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import auth
import sessions
import users
from routes import deps
from services import board_ownership

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
def login_view(
    request: Request,
    next: str | None = None,
    error: str | None = None,
    info: str | None = None,
):
    if users.is_setup_required():
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
    user = users.find_by_email(email)
    if user is None or not users.verify_password(user, password):
        return RedirectResponse(
            f"/login?next={deps.safe_next(next)}&error=Invalid+email+or+password",
            status_code=303,
        )
    cookie = sessions.create(user.id)
    users.touch_last_login(user.id)
    response = RedirectResponse(deps.safe_next(next), status_code=303)
    response.set_cookie(
        sessions.COOKIE_NAME,
        cookie,
        httponly=True,
        samesite="lax",
        max_age=sessions.SESSION_TTL_SEC,
    )
    return response


@router.post("/logout")
def logout_submit(request: Request):
    cookie_value = request.cookies.get(sessions.COOKIE_NAME)
    sessions.destroy(cookie_value)
    response = RedirectResponse("/login?info=Signed+out", status_code=303)
    response.delete_cookie(sessions.COOKIE_NAME)
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
        user = users.register_user(
            email=email,
            password=password,
            display_name=display_name or None,
        )
    except ValueError as e:
        return RedirectResponse(
            f"/register?error={str(e).replace(' ', '+')}", status_code=303
        )
    board_ownership.assign_all_unowned_disk_boards_to_user(user.id)
    cookie = sessions.create(user.id)
    users.touch_last_login(user.id)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        sessions.COOKIE_NAME,
        cookie,
        httponly=True,
        samesite="lax",
        max_age=sessions.SESSION_TTL_SEC,
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
