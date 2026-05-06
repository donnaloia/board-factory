"""Auth JSON/session flows (forms + profile APIs)."""

from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from auth import pixellab_status
from auth import services as auth_services
from auth.middleware import require_user
from infrastructure import deps

router = APIRouter()


# ── Session / registration (form POST → redirect) ──────────────────────────


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


@router.post("/forgot-password")
def forgot_submit(request: Request, email: str = Form(...)):
    return RedirectResponse("/forgot-password?sent=true", status_code=303)


# ── Account modal (`/api/profile`) ─────────────────────────────────────────


@router.get("/api/profile")
def api_profile_get(request: Request):
    user = require_user(request)
    return JSONResponse(
        {
            **user.public_dict(),
            "glyphs": auth_services.GLYPHS,
            "default_glyph": auth_services.DEFAULT_GLYPH,
            "default_color": auth_services.DEFAULT_COLOR,
        }
    )


@router.put("/api/profile")
async def api_profile_update(request: Request):
    user = require_user(request)
    body = await request.json()
    try:
        updated = auth_services.update_profile(
            user.id,
            display_name=body.get("display_name"),
            email=body.get("email"),
            icon_glyph=body.get("icon_glyph"),
            icon_color=body.get("icon_color"),
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return JSONResponse(updated.public_dict())


@router.put("/api/profile/api-key")
async def api_profile_api_key(request: Request):
    user = require_user(request)
    body = await request.json()
    try:
        updated = auth_services.update_api_keys(
            user.id,
            pixellab_api_key=body.get("pixellab_api_key"),
            openai_api_key=body.get("openai_api_key"),
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return JSONResponse(updated.public_dict())


@router.post("/api/profile/password")
async def api_profile_password(request: Request):
    user = require_user(request)
    body = await request.json()
    try:
        auth_services.change_password(
            user.id,
            old=body.get("current_password", ""),
            new=body.get("new_password", ""),
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    auth_services.destroy_all_sessions_for_user(user.id)
    new_cookie = auth_services.create_session_cookie(user.id)
    response = JSONResponse({"ok": True})
    response.set_cookie(
        auth_services.COOKIE_NAME,
        new_cookie,
        httponly=True,
        samesite="lax",
        max_age=auth_services.SESSION_TTL_SEC,
    )
    return response


@router.get("/api/profile/api-status")
async def api_profile_status(request: Request):
    user = require_user(request)
    report = await pixellab_status.run_status_checks(user.pixellab_api_key)
    return JSONResponse(report.to_dict())


@router.get("/api/profile/openai-status")
async def api_openai_status(request: Request):
    user = require_user(request)
    key = user.openai_api_key or os.environ.get("OPENAI_API_KEY", "")
    if not key:
        return JSONResponse({"ok": False, "detail": "no key saved"})

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {key}"},
            )
        if r.status_code == 200:
            return JSONResponse({"ok": True, "detail": "connected"})
        if r.status_code == 401:
            return JSONResponse({"ok": False, "detail": "invalid key"})
        return JSONResponse({"ok": False, "detail": f"HTTP {r.status_code}"})
    except Exception as e:
        return JSONResponse({"ok": False, "detail": str(e)[:80]})
