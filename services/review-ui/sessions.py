"""In-memory session store with sliding 30-day TTL.

Single-process Uvicorn → a dict is fine. If we ever multi-process this,
swap _store for a sqlite table or redis without changing the public API.

The cookie itself is a signed token (itsdangerous) so a stolen .users.json
can't be replayed without the SECRET. Cookies are httponly + samesite=lax.
We don't set Secure because we live on plain HTTP localhost — flip that
on the day we deploy behind real TLS.
"""

from __future__ import annotations

import os
import secrets
import time
from dataclasses import dataclass
from threading import RLock

from itsdangerous import BadSignature, URLSafeSerializer


COOKIE_NAME = "bf_session"
SESSION_TTL_SEC = 30 * 24 * 3600  # 30 days idle

# A weak default secret so the system works out of the box, but operators
# should set BOARDFACTORY_SECRET in compose for any non-throwaway use.
_SECRET = os.environ.get("BOARDFACTORY_SECRET") or "dev-only-secret-change-me"
_signer = URLSafeSerializer(_SECRET, salt="bf-session")

_lock = RLock()
_store: dict[str, "Session"] = {}


@dataclass
class Session:
    sid: str
    user_id: str
    created_ms: int
    last_seen_ms: int


def create(user_id: str) -> str:
    """Create a new session for the given user. Returns the signed cookie value."""
    sid = secrets.token_urlsafe(24)
    now = int(time.time() * 1000)
    with _lock:
        _store[sid] = Session(sid=sid, user_id=user_id, created_ms=now, last_seen_ms=now)
    return _signer.dumps(sid)


def resolve(cookie_value: str | None) -> str | None:
    """Resolve a cookie value to a user_id, or None if invalid/expired."""
    if not cookie_value:
        return None
    try:
        sid = _signer.loads(cookie_value)
    except BadSignature:
        return None
    if not isinstance(sid, str):
        return None
    now = int(time.time() * 1000)
    with _lock:
        sess = _store.get(sid)
        if sess is None:
            return None
        if (now - sess.last_seen_ms) > SESSION_TTL_SEC * 1000:
            _store.pop(sid, None)
            return None
        sess.last_seen_ms = now  # sliding refresh
        return sess.user_id


def destroy(cookie_value: str | None) -> None:
    if not cookie_value:
        return
    try:
        sid = _signer.loads(cookie_value)
    except BadSignature:
        return
    with _lock:
        _store.pop(sid, None)


def destroy_all_for_user(user_id: str) -> None:
    """Used after password change to log other browsers out."""
    with _lock:
        for sid in [s for s, sess in _store.items() if sess.user_id == user_id]:
            _store.pop(sid, None)
