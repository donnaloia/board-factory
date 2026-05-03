"""Users persisted in SQLite (``users`` + ``user_secrets``).

Passwords stay bcrypt-hashed. Provider API keys live in ``user_secrets`` rows,
encrypted at rest via Fernet (see ``storage.secret_crypto``). A default dev
admin is inserted by Alembic migration ``0007_seed_dev_admin_user`` when the
``users`` table is empty (see README “Fresh clone”).

PUBLIC_API unchanged for callers: ``User`` dataclass, ``find_by_email``, etc.
"""

from __future__ import annotations

import os
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from threading import RLock

import bcrypt
from sqlalchemy import func, select
from sqlalchemy.orm import Session as SASession

from boardfactory import boards as bf_boards
from storage.db import session_scope
from storage.secret_crypto import decrypt_text, encrypt_text
from models.core import UserRecord, UserSecretRecord


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_lock = RLock()

SECRET_KIND_PIXELLAB = "pixellab_api_key"
SECRET_KIND_OPENAI = "openai_api_key"

GLYPHS = ["◆", "♠", "♣", "♥", "♦", "★", "✦", "✧", "▲", "●", "■", "◉"]
DEFAULT_GLYPH = "◆"
DEFAULT_COLOR = "#c8995b"


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


def _allocate_username(session: SASession, email: str) -> str:
    local = (email or "").split("@")[0]
    base = bf_boards.slugify(local)
    if not base or base == "untitled":
        base = "user"
    cand = base
    n = 0
    while session.scalar(select(UserRecord).where(UserRecord.username == cand)):
        n += 1
        cand = f"{base}-{n}"[:64]
    return cand


def _secret_map(session: SASession, user_id: str) -> dict[str, str]:
    rows = session.scalars(
        select(UserSecretRecord).where(UserSecretRecord.user_id == user_id)
    ).all()
    out: dict[str, str] = {}
    for r in rows:
        out[r.kind] = decrypt_text(r.ciphertext)
    return out


def _row_to_user(session: SASession, rec: UserRecord) -> User:
    sm = _secret_map(session, rec.id)
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


def _upsert_secret(session: SASession, user_id: str, kind: str, plain: str) -> None:
    row = session.scalar(
        select(UserSecretRecord).where(
            UserSecretRecord.user_id == user_id,
            UserSecretRecord.kind == kind,
        )
    )
    if not plain:
        if row is not None:
            session.delete(row)
        return
    token = encrypt_text(plain)
    if row is None:
        session.add(UserSecretRecord(user_id=user_id, kind=kind, ciphertext=token))
    else:
        row.ciphertext = token


def is_setup_required() -> bool:
    with session_scope() as session:
        n = session.scalar(select(func.count()).select_from(UserRecord)) or 0
        return int(n) == 0


def find_by_email(email: str) -> User | None:
    em = (email or "").strip().lower()
    if not em:
        return None
    with session_scope() as session:
        rec = session.scalar(select(UserRecord).where(UserRecord.email == em))
        if rec is None:
            return None
        return _row_to_user(session, rec)


def find_by_username(username: str) -> User | None:
    u = (username or "").strip().lower()
    if not u:
        return None
    with session_scope() as session:
        rec = session.scalar(select(UserRecord).where(UserRecord.username == u))
        if rec is None:
            return None
        return _row_to_user(session, rec)


def find_by_id(user_id: str) -> User | None:
    if not user_id:
        return None
    with session_scope() as session:
        rec = session.get(UserRecord, user_id)
        if rec is None:
            return None
        return _row_to_user(session, rec)


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


def create_first_user(*, email: str, password: str, display_name: str | None = None) -> User:
    em = (email or "").strip().lower()
    if not _EMAIL_RE.match(em):
        raise ValueError("Invalid email address")
    if not password or len(password) < 8:
        raise ValueError("Password must be at least 8 characters")
    with _lock:
        if not is_setup_required():
            raise ValueError("Registration is closed — an account already exists.")
        uid = uuid.uuid4().hex
        now_ms = int(time.time() * 1000)
        dn = (display_name or em.split("@")[0]).strip()
        with session_scope() as session:
            uname = _allocate_username(session, em)
            session.add(
                UserRecord(
                    id=uid,
                    email=em,
                    username=uname,
                    password_hash=hash_password(password),
                    display_name=dn,
                    icon_glyph=DEFAULT_GLYPH,
                    icon_color=DEFAULT_COLOR,
                    created_ms=now_ms,
                    last_login_ms=0,
                )
            )
        u = find_by_id(uid)
        assert u is not None
        return u


def update_profile(
    user_id: str,
    *,
    display_name: str | None = None,
    email: str | None = None,
    icon_glyph: str | None = None,
    icon_color: str | None = None,
) -> User:
    with session_scope() as session:
        rec = session.get(UserRecord, user_id)
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
            clash = session.scalar(
                select(UserRecord).where(UserRecord.email == em, UserRecord.id != user_id)
            )
            if clash is not None:
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
        rec = session.get(UserRecord, user_id)
        if rec is None:
            raise ValueError("Unknown user")
        if pixellab_api_key is not None:
            _upsert_secret(session, user_id, SECRET_KIND_PIXELLAB, pixellab_api_key.strip())
        if openai_api_key is not None:
            _upsert_secret(session, user_id, SECRET_KIND_OPENAI, openai_api_key.strip())
        session.flush()
        return _row_to_user(session, rec)


def change_password(user_id: str, *, old: str, new: str) -> None:
    with session_scope() as session:
        rec = session.get(UserRecord, user_id)
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


def touch_last_login(user_id: str) -> None:
    with session_scope() as session:
        rec = session.get(UserRecord, user_id)
        if rec is None:
            return
        rec.last_login_ms = int(time.time() * 1000)
