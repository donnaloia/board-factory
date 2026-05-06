"""Pure DB I/O for the auth domain.

Three tables, all small and tightly bound to the same domain:

* ``users``           — the User record itself.
* ``user_secrets``    — Fernet-encrypted API keys per user.
* ``browser_sessions``— signed session cookies; sid lives in the
  ``bf_session`` cookie, the row holds the user binding + sliding TTL.

Use cases (registration, login, profile updates, API key rotation) live
in :mod:`auth.services` and call into here. The middleware in
:mod:`auth.middleware` calls :func:`resolve_session` directly because
that's a hot path on every request.
"""

from __future__ import annotations

import time

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session as SASession

from auth.secret_crypto import decrypt_text, encrypt_text
from infrastructure.db import session_scope
from auth.models import BrowserSessionRecord, UserRecord, UserSecretRecord


SECRET_KIND_PIXELLAB = "pixellab_api_key"
SECRET_KIND_OPENAI = "openai_api_key"


# ── users + secrets ───────────────────────────────────────────────────


def secret_map(session: SASession, user_id: str) -> dict[str, str]:
    """Return ``{kind: plaintext}`` for one user. Caller already has a session."""
    rows = session.scalars(
        select(UserSecretRecord).where(UserSecretRecord.user_id == user_id)
    ).all()
    out: dict[str, str] = {}
    for r in rows:
        out[r.kind] = decrypt_text(r.ciphertext)
    return out


def upsert_secret(session: SASession, user_id: str, kind: str, plain: str) -> None:
    """Insert / update / delete one secret row. Empty plaintext deletes the row."""
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


def get_user_record(session: SASession, user_id: str) -> UserRecord | None:
    return session.get(UserRecord, user_id)


def find_user_by_email(session: SASession, email: str) -> UserRecord | None:
    em = (email or "").strip().lower()
    if not em:
        return None
    return session.scalar(select(UserRecord).where(UserRecord.email == em))


def find_user_by_username(session: SASession, username: str) -> UserRecord | None:
    u = (username or "").strip().lower()
    if not u:
        return None
    return session.scalar(select(UserRecord).where(UserRecord.username == u))


def count_users() -> int:
    with session_scope() as session:
        n = session.scalar(select(func.count()).select_from(UserRecord)) or 0
        return int(n)


def insert_user(session: SASession, *, rec: UserRecord) -> None:
    session.add(rec)


def touch_last_login(user_id: str) -> None:
    with session_scope() as session:
        rec = session.get(UserRecord, user_id)
        if rec is None:
            return
        rec.last_login_ms = int(time.time() * 1000)


# ── browser sessions ──────────────────────────────────────────────────


def create_session(sid: str, user_id: str) -> None:
    now = int(time.time() * 1000)
    with session_scope() as session:
        session.add(
            BrowserSessionRecord(
                sid=sid,
                user_id=user_id,
                created_ms=now,
                last_seen_ms=now,
            )
        )


def resolve_session(sid: str, *, ttl_sec: int) -> str | None:
    """Return ``user_id`` or ``None``; refresh ``last_seen_ms`` if still valid."""
    now = int(time.time() * 1000)
    with session_scope() as session:
        row = session.get(BrowserSessionRecord, sid)
        if row is None:
            return None
        if (now - row.last_seen_ms) > ttl_sec * 1000:
            session.delete(row)
            return None
        row.last_seen_ms = now
        return row.user_id


def delete_session(sid: str) -> None:
    with session_scope() as session:
        row = session.get(BrowserSessionRecord, sid)
        if row is not None:
            session.delete(row)


def delete_all_sessions_for_user(user_id: str) -> None:
    with session_scope() as session:
        session.execute(
            delete(BrowserSessionRecord).where(BrowserSessionRecord.user_id == user_id)
        )
