"""Users store backed by boards/.users.json — single-tenant, first-user-only.

This is intentionally a small flat-file store. We're a single-process Uvicorn
behind a localhost listener; sqlite would be overkill and the read pattern
("look up the one signed-in user per request") is bounded.

Storage shape:
  {
    "users": [
      {
        "id": "<uuid>",
        "email": "you@example.com",
        "password_hash": "<bcrypt>",
        "display_name": "Don",
        "icon_glyph": "skull",       # one of GLYPHS
        "icon_color": "#c8995b",
        "pixellab_api_key": "...",   # plaintext — see SECURITY note
        "openai_api_key": "...",     # plaintext — see SECURITY note
        "created_ms": 1714400000000,
        "last_login_ms": 1714400000000
      }
    ]
  }

Image-gen keys live together because the artist mental model is "both keys
serve the same job (drawing pixels), they just go to different providers".
PixelLab is the one we drive today; the OpenAI slot is here so when we add
gpt-image-based ops there's a place for the key without another schema bump.

SECURITY: passwords are bcrypt-hashed; provider API keys are stored
plaintext. That's the same exposure the existing docker-compose.yml already
has, and it's appropriate for a localhost dev tool. .users.json is added
to .gitignore so it never ships to GitHub. If you ever expose this beyond
localhost, the API key columns should be encrypted at rest with a key from
the OS keychain.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import RLock

import bcrypt


REPO_ROOT = Path(os.environ.get("BOARDFACTORY_REPO", "/repo"))
USERS_PATH = REPO_ROOT / "boards" / ".users.json"

# Preset icon glyphs for the avatar — pixel-art-themed strings the modal
# renders as a single Unicode character. Picked for visual variety; user
# adds their own avatar later if we ever support image upload.
GLYPHS = ["◆", "♠", "♣", "♥", "♦", "★", "✦", "✧", "▲", "●", "■", "◉"]
DEFAULT_GLYPH = "◆"
DEFAULT_COLOR = "#c8995b"  # brass

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_lock = RLock()


@dataclass
class User:
    id: str
    email: str
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
        """Safe-to-send-to-browser projection — no password hash, masked API keys.

        Each key gets a `<name>_set` boolean (so the UI can show a "saved" pill
        without showing the value) and a `<name>_last4` string for the masked
        placeholder. The raw key never crosses the wire after it's saved.
        """
        d = self.to_dict()
        d.pop("password_hash", None)
        for field_name in ("pixellab_api_key", "openai_api_key"):
            raw = getattr(self, field_name, "") or ""
            d[f"{field_name}_last4"] = raw[-4:] if raw else ""
            d[f"{field_name}_set"] = bool(raw)
            d.pop(field_name, None)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "User":
        return cls(
            id=str(d["id"]),
            email=str(d["email"]).lower(),
            password_hash=str(d["password_hash"]),
            display_name=str(d.get("display_name") or d["email"].split("@")[0]),
            icon_glyph=str(d.get("icon_glyph") or DEFAULT_GLYPH),
            icon_color=str(d.get("icon_color") or DEFAULT_COLOR),
            pixellab_api_key=str(d.get("pixellab_api_key") or ""),
            openai_api_key=str(d.get("openai_api_key") or ""),
            created_ms=int(d.get("created_ms") or 0),
            last_login_ms=int(d.get("last_login_ms") or 0),
        )


# ────────────────────────── persistence ──────────────────────────


def _load_raw() -> dict:
    if not USERS_PATH.exists():
        return {"users": []}
    try:
        return json.loads(USERS_PATH.read_text())
    except Exception:
        # Corrupt file → treat as empty rather than wipe in place. Operator
        # can inspect manually.
        return {"users": []}


def _save_raw(payload: dict) -> None:
    USERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = USERS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    os.replace(tmp, USERS_PATH)


def _all_users() -> list[User]:
    return [User.from_dict(u) for u in _load_raw().get("users", [])]


def _save_users(users: list[User]) -> None:
    _save_raw({"users": [u.to_dict() for u in users]})


# ────────────────────────── public API ──────────────────────────


def is_setup_required() -> bool:
    """True iff there are zero users on disk → /register is the only entrypoint."""
    with _lock:
        return len(_all_users()) == 0


def find_by_email(email: str) -> User | None:
    em = (email or "").strip().lower()
    if not em:
        return None
    with _lock:
        for u in _all_users():
            if u.email == em:
                return u
    return None


def find_by_id(user_id: str) -> User | None:
    if not user_id:
        return None
    with _lock:
        for u in _all_users():
            if u.id == user_id:
                return u
    return None


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
    """First-user-only registration. Raises ValueError if a user already exists."""
    em = (email or "").strip().lower()
    if not _EMAIL_RE.match(em):
        raise ValueError("Invalid email address")
    if not password or len(password) < 8:
        raise ValueError("Password must be at least 8 characters")
    with _lock:
        users = _all_users()
        if users:
            raise ValueError("Registration is closed — an account already exists.")
        u = User(
            id=uuid.uuid4().hex,
            email=em,
            password_hash=hash_password(password),
            display_name=(display_name or em.split("@")[0]).strip(),
        )
        users.append(u)
        _save_users(users)
        return u


def update_profile(user_id: str, *, display_name: str | None = None,
                   email: str | None = None, icon_glyph: str | None = None,
                   icon_color: str | None = None) -> User:
    with _lock:
        users = _all_users()
        for i, u in enumerate(users):
            if u.id != user_id:
                continue
            if display_name is not None:
                dn = display_name.strip()
                if not dn:
                    raise ValueError("Display name cannot be empty")
                u.display_name = dn[:80]
            if email is not None:
                em = email.strip().lower()
                if not _EMAIL_RE.match(em):
                    raise ValueError("Invalid email address")
                # Disallow stealing another user's email (forward-looking — we
                # only have one user today, but guard anyway).
                for other in users:
                    if other.id != u.id and other.email == em:
                        raise ValueError("Email already in use")
                u.email = em
            if icon_glyph is not None and icon_glyph in GLYPHS:
                u.icon_glyph = icon_glyph
            if icon_color is not None:
                # Accept any 7-char #rrggbb; we don't validate the palette.
                if not re.match(r"^#[0-9a-fA-F]{6}$", icon_color):
                    raise ValueError("Color must be a #RRGGBB hex string")
                u.icon_color = icon_color
            users[i] = u
            _save_users(users)
            return u
    raise ValueError("Unknown user")


def update_api_keys(
    user_id: str,
    *,
    pixellab_api_key: str | None = None,
    openai_api_key: str | None = None,
) -> User:
    """Update one or both image-gen API keys.

    Per-field semantics so the modal can submit just the key the artist
    edited without forcing them to retype the other:

      - field absent / None  → leave the existing value alone
      - field present, ""    → clear the saved key
      - field present, "..." → save (after .strip())

    Single endpoint that takes both keys in one body keeps the modal's
    "Save image-gen keys" button atomic — partial saves where only PixelLab
    persisted because OpenAI hit a network blip would be confusing.
    """
    with _lock:
        users = _all_users()
        for i, u in enumerate(users):
            if u.id != user_id:
                continue
            if pixellab_api_key is not None:
                u.pixellab_api_key = pixellab_api_key.strip()
            if openai_api_key is not None:
                u.openai_api_key = openai_api_key.strip()
            users[i] = u
            _save_users(users)
            return u
    raise ValueError("Unknown user")


def change_password(user_id: str, *, old: str, new: str) -> None:
    with _lock:
        users = _all_users()
        for i, u in enumerate(users):
            if u.id != user_id:
                continue
            if not verify_password(u, old):
                raise ValueError("Current password is incorrect")
            if len(new) < 8:
                raise ValueError("New password must be at least 8 characters")
            u.password_hash = hash_password(new)
            users[i] = u
            _save_users(users)
            return
    raise ValueError("Unknown user")


def touch_last_login(user_id: str) -> None:
    with _lock:
        users = _all_users()
        for i, u in enumerate(users):
            if u.id == user_id:
                u.last_login_ms = int(time.time() * 1000)
                users[i] = u
                _save_users(users)
                return
