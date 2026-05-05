"""Auth domain — users, sessions, API-key secrets, HTTP gating.

Files in this package
---------------------

``services``
    User + session use cases. Public API for the domain: ``User``
    dataclass, ``register_user``, ``find_by_*``, ``update_profile``,
    ``update_api_keys``, ``change_password``, plus the cookie helpers
    (``create_session_cookie`` / ``resolve_session_cookie`` /
    ``destroy_session_cookie``) and the constants ``COOKIE_NAME`` +
    ``SESSION_TTL_SEC``.

``repository``
    Pure DB I/O for ``users`` + ``user_secrets`` + ``browser_sessions``.

``middleware``
    ``AuthMiddleware`` (request-time cookie → user resolution + redirect
    gate) and the ``current_user`` / ``require_user`` FastAPI
    dependencies. The hot path on every request, so it skips the
    services layer for session lookup and calls ``repository`` /
    ``services`` helpers directly.

``secret_crypto``
    Fernet wrapper used by the repository for API keys at rest.

``pixellab_status``
    Provider-health checks for the account modal (PixelLab connectivity,
    auth, quota). Fully self-contained — uses the user's saved API key
    via :func:`auth.services.find_by_id`.

Other domains import explicitly:

    from auth.middleware import AuthMiddleware, current_user, require_user
    from auth import services as auth_services
"""
