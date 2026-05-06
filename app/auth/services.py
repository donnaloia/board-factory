"""User + session use cases for the auth domain.

This is the public API for the auth domain. Routes call here; the
:mod:`auth.repository` does the SQL. The middleware in
:mod:`auth.middleware` is the only consumer that goes around the
service layer (it touches sessions on every request and we want that
hot path to be obvious).

Public surface
--------------

User dataclass + lookups
    :class:`User`, :func:`find_by_id`, :func:`find_by_email`,
    :func:`find_by_username`, :func:`is_setup_required`.

Registration + profile
    :func:`register_user`, :func:`create_first_user`,
    :func:`update_profile`, :func:`update_api_keys`,
    :func:`change_password`.

Auth
    :func:`hash_password`, :func:`verify_password`, :func:`touch_last_login`.

Sessions (signed cookie ↔ ``browser_sessions`` row)
    :func:`create_session_cookie`, :func:`resolve_session_cookie`,
    :func:`destroy_session_cookie`, :func:`destroy_all_sessions_for_user`,
    :data:`COOKIE_NAME`.
"""

from __future__ import annotations

import os
import re
import secrets
import time
import uuid
from dataclasses import asdict, dataclass, field
from threading import RLock

import bcrypt
from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy.orm import Session as SASession

from auth import repository as auth_repo
from boardfactory import boards as bf_boards
from infrastructure.db import session_scope
from auth.models import UserRecord


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_lock = RLock()


# Re-export the secret kind constants so callers don't need both imports.
SECRET_KIND_PIXELLAB = auth_repo.SECRET_KIND_PIXELLAB
SECRET_KIND_OPENAI = auth_repo.SECRET_KIND_OPENAI

GLYPHS = ["◆", "♠", "♣", "♥", "♦", "★", "✦", "✧", "▲", "●", "■", "◉"]
DEFAULT_GLYPH = "◆"
DEFAULT_COLOR = "#c8995b"


# ────────────────────────── User dataclass ──────────────────────────


@dataclass
class User:
    id: str
    email: str
    username: str
    password_hash: str
    display_name: str
    icon_glyph: str = DEFAULT_GLYPH
    icon_color: str = DEFAULT_COLOR
    pixellab_api_key: str = ""
    openai_api_key: str = ""
    created_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    last_login_ms: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    def public_dict(self) -> dict:
        d = self.to_dict()
        d.pop("password_hash", None)
        for field_name in ("pixellab_api_key", "openai_api_key"):
            raw = getattr(self, field_name, "") or ""
            d[f"{field_name}_last4"] = raw[-4:] if raw else ""
            d[f"{field_name}_set"] = bool(raw)
            d.pop(field_name, None)
        return d


def _row_to_user(session: SASession, rec: UserRecord) -> User:
    sm = auth_repo.secret_map(session, rec.id)
    return User(
        id=rec.id,
        email=rec.email,
        username=rec.username,
        password_hash=rec.password_hash,
        display_name=rec.display_name,
        icon_glyph=rec.icon_glyph or DEFAULT_GLYPH,
        icon_color=rec.icon_color or DEFAULT_COLOR,
        pixellab_api_key=sm.get(SECRET_KIND_PIXELLAB, ""),
        openai_api_key=sm.get(SECRET_KIND_OPENAI, ""),
        created_ms=int(rec.created_ms),
        last_login_ms=int(rec.last_login_ms),
    )


# ────────────────────────── lookups ──────────────────────────


def is_setup_required() -> bool:
    return auth_repo.count_users() == 0


def find_by_email(email: str) -> User | None:
    with session_scope() as session:
        rec = auth_repo.find_user_by_email(session, email)
        if rec is None:
            return None
        return _row_to_user(session, rec)


def find_by_username(username: str) -> User | None:
    with session_scope() as session:
        rec = auth_repo.find_user_by_username(session, username)
        if rec is None:
            return None
        return _row_to_user(session, rec)


def find_by_id(user_id: str) -> User | None:
    if not user_id:
        return None
    with session_scope() as session:
        rec = auth_repo.get_user_record(session, user_id)
        if rec is None:
            return None
        return _row_to_user(session, rec)


# ────────────────────────── passwords ──────────────────────────


def verify_password(user: User, plaintext: str) -> bool:
    if not user or not plaintext:
        return False
    try:
        return bcrypt.checkpw(plaintext.encode("utf-8"), user.password_hash.encode("utf-8"))
    except Exception:
        return False


def hash_password(plaintext: str) -> str:
    if not plaintext or len(plaintext) < 8:
        raise ValueError("Password must be at least 8 characters")
    return bcrypt.hashpw(plaintext.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def touch_last_login(user_id: str) -> None:
    auth_repo.touch_last_login(user_id)


# ────────────────────────── registration + profile ──────────────────────────


def _allocate_username(session: SASession, email: str) -> str:
    local = (email or "").split("@")[0]
    base = bf_boards.slugify(local)
    if not base or base == "untitled":
        base = "user"
    cand = base
    n = 0
    while auth_repo.find_user_by_username(session, cand):
        n += 1
        cand = f"{base}-{n}"[:64]
    return cand


def register_user(*, email: str, password: str, display_name: str | None = None) -> User:
    """Create a new account if the email is not already registered."""
    em = (email or "").strip().lower()
    if not _EMAIL_RE.match(em):
        raise ValueError("Invalid email address")
    if not password or len(password) < 8:
        raise ValueError("Password must be at least 8 characters")
    with _lock:
        with session_scope() as session:
            if auth_repo.find_user_by_email(session, em):
                raise ValueError("An account with this email already exists.")
        uid = uuid.uuid4().hex
        now_ms = int(time.time() * 1000)
        dn = (display_name or em.split("@")[0]).strip()
        with session_scope() as session:
            uname = _allocate_username(session, em)
            auth_repo.insert_user(
                session,
                rec=UserRecord(
                    id=uid,
                    email=em,
                    username=uname,
                    password_hash=hash_password(password),
                    display_name=dn,
                    icon_glyph=DEFAULT_GLYPH,
                    icon_color=DEFAULT_COLOR,
                    created_ms=now_ms,
                    last_login_ms=0,
                ),
            )
        u = find_by_id(uid)
        assert u is not None
        return u


def create_first_user(*, email: str, password: str, display_name: str | None = None) -> User:
    """Only when the database has zero users (initial setup / tests)."""
    with _lock:
        if not is_setup_required():
            raise ValueError("Registration is closed — an account already exists.")
    return register_user(email=email, password=password, display_name=display_name)


def update_profile(
    user_id: str,
    *,
    display_name: str | None = None,
    email: str | None = None,
    icon_glyph: str | None = None,
    icon_color: str | None = None,
) -> User:
    with session_scope() as session:
        rec = auth_repo.get_user_record(session, user_id)
        if rec is None:
            raise ValueError("Unknown user")
        if display_name is not None:
            dn = display_name.strip()
            if not dn:
                raise ValueError("Display name cannot be empty")
            rec.display_name = dn[:80]
        if email is not None:
            em = email.strip().lower()
            if not _EMAIL_RE.match(em):
                raise ValueError("Invalid email address")
            clash = auth_repo.find_user_by_email(session, em)
            if clash is not None and clash.id != user_id:
                raise ValueError("Email already in use")
            rec.email = em
        if icon_glyph is not None and icon_glyph in GLYPHS:
            rec.icon_glyph = icon_glyph
        if icon_color is not None:
            if not re.match(r"^#[0-9a-fA-F]{6}$", icon_color):
                raise ValueError("Color must be a #RRGGBB hex string")
            rec.icon_color = icon_color
        session.flush()
        return _row_to_user(session, rec)


def update_api_keys(
    user_id: str,
    *,
    pixellab_api_key: str | None = None,
    openai_api_key: str | None = None,
) -> User:
    with session_scope() as session:
        rec = auth_repo.get_user_record(session, user_id)
        if rec is None:
            raise ValueError("Unknown user")
        if pixellab_api_key is not None:
            auth_repo.upsert_secret(session, user_id, SECRET_KIND_PIXELLAB, pixellab_api_key.strip())
        if openai_api_key is not None:
            auth_repo.upsert_secret(session, user_id, SECRET_KIND_OPENAI, openai_api_key.strip())
        session.flush()
        return _row_to_user(session, rec)


def change_password(user_id: str, *, old: str, new: str) -> None:
    with session_scope() as session:
        rec = auth_repo.get_user_record(session, user_id)
        if rec is None:
            raise ValueError("Unknown user")
        tmp = User(
            id=rec.id,
            email=rec.email,
            username=rec.username,
            password_hash=rec.password_hash,
            display_name=rec.display_name,
        )
        if not verify_password(tmp, old):
            raise ValueError("Current password is incorrect")
        if len(new) < 8:
            raise ValueError("New password must be at least 8 characters")
        rec.password_hash = hash_password(new)


# ────────────────────────── browser sessions ──────────────────────────


COOKIE_NAME = "bf_session"
SESSION_TTL_SEC = 30 * 24 * 3600  # 30 days idle

_SECRET = os.environ.get("BOARDFACTORY_SECRET") or "dev-only-secret-change-me"
_signer = URLSafeSerializer(_SECRET, salt="bf-session")


def create_session_cookie(user_id: str) -> str:
    """Create a new session row and return the signed cookie value."""
    sid = secrets.token_urlsafe(24)
    auth_repo.create_session(sid, user_id)
    return _signer.dumps(sid)


def resolve_session_cookie(cookie_value: str | None) -> str | None:
    """Validate the cookie + sliding-TTL session row; return ``user_id`` or ``None``."""
    if not cookie_value:
        return None
    try:
        sid = _signer.loads(cookie_value)
    except BadSignature:
        return None
    if not isinstance(sid, str):
        return None
    return auth_repo.resolve_session(sid, ttl_sec=SESSION_TTL_SEC)


def destroy_session_cookie(cookie_value: str | None) -> None:
    if not cookie_value:
        return
    try:
        sid = _signer.loads(cookie_value)
    except BadSignature:
        return
    if not isinstance(sid, str):
        return
    auth_repo.delete_session(sid)


def destroy_all_sessions_for_user(user_id: str) -> None:
    auth_repo.delete_all_sessions_for_user(user_id)
