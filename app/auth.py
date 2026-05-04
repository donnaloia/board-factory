"""Auth glue: HTTP middleware + FastAPI dependency for the current user.

The middleware does two things:
  1. Resolve the bf_session cookie → user (attached to request.state.user)
  2. Gate access — anything that isn't an auth route, /static, or a small
     "open" allow-list redirects to /login when there's no user.

Flow rules:
  - When zero users exist → unauthenticated visitors go to /register (first account).
  - When users exist → unauthenticated visitors go to /login; /register stays open
    for additional accounts.
  - The /login form, /register form, /forgot-password (always),
    /static/*, and /favicon.ico are anonymous.

Why not FastAPI's built-in dependency?
  We do want a Depends(current_user) for routes that need the user object
  (the account modal API, the per-user API key resolver). But we *also* need
  a hard gate — middleware — so a misconfigured route can't accidentally
  serve data to anonymous browsers.
"""

from __future__ import annotations

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse, Response

import sessions
import users


# Paths that don't require authentication. /static is matched as a prefix.
ANON_PATH_PREFIXES = ("/static/",)
ANON_EXACT_PATHS = {
    "/login",
    "/logout",
    "/register",
    "/forgot-password",
    "/favicon.ico",
    "/health",
    "/health/ready",
}


def _is_anonymous_path(path: str) -> bool:
    if path in ANON_EXACT_PATHS:
        return True
    return any(path.startswith(p) for p in ANON_PATH_PREFIXES)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        cookie_value = request.cookies.get(sessions.COOKIE_NAME)
        user_id = sessions.resolve(cookie_value) if cookie_value else None
        user = users.find_by_id(user_id) if user_id else None

        # Always attach (possibly None) so route handlers and templates can rely
        # on request.state.user being defined.
        request.state.user = user

        if _is_anonymous_path(path):
            return await call_next(request)

        if user is None:
            # No users yet → offer registration first; otherwise login.
            target = "/register" if users.is_setup_required() else "/login"
            # Preserve original target as ?next=<path> (login template uses it).
            sep = "?" if "?" not in target else "&"
            redirect = f"{target}{sep}next={request.url.path}"
            return RedirectResponse(redirect, status_code=303)

        return await call_next(request)


def current_user(request: Request) -> users.User | None:
    """Dependency: returns the user attached by AuthMiddleware (or None)."""
    return getattr(request.state, "user", None)


def require_user(request: Request) -> users.User:
    u = current_user(request)
    if u is None:
        # The middleware should have already redirected, but if a route is
        # somehow reached anonymously, fail loud rather than serve nothing.
        from fastapi import HTTPException
        raise HTTPException(401, "Authentication required")
    return u
