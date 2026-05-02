"""HTTP routers for the Board Factory FastAPI app.

``server`` assembles the ``FastAPI`` instance, attaches middleware, mounts
static files, and ``include_router``'s the modules here. Shared request helpers
live in ``routes.deps``.
"""
