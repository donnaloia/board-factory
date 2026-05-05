"""Symmetric encryption for API keys at rest (Fernet).

Uses the same ``BOARDFACTORY_SECRET`` default as session signing so local dev
works without extra env. Rotate ``BOARDFACTORY_SECRET`` only with a migration
plan — existing ciphertext becomes unreadable.
"""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken


def _secret_material() -> str:
    return os.environ.get("BOARDFACTORY_SECRET") or "dev-only-secret-change-me"


def fernet_for_app() -> Fernet:
    digest = hashlib.sha256(_secret_material().encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_text(plain: str) -> str:
    if not plain:
        return ""
    return fernet_for_app().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_text(token: str) -> str:
    if not token:
        return ""
    try:
        return fernet_for_app().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken:
        return ""
