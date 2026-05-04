"""Use-case-level services for the Board Factory web application.

Each module exposes a small API that route handlers call. Services sit
between HTTP and ``storage`` (filesystem + SQLAlchemy) plus the
``boardfactory`` pipeline. They raise plain Python exceptions; routes map
those to ``HTTPException``.

Modules (non-exhaustive):

  - ``boards``           — list / create / rename / delete boards; summaries
  - ``board_ownership``  — which user owns which board slug
  - ``board_definition`` — relational ``board_games`` ↔ pipeline ``Catalog`` dict
  - ``catalog``          — load/save catalog + ``generation`` block read/write
  - ``cells``            — per-cell assets, history, status
  - ``asset_urls``       — millisecond ``?t=`` helpers for ``/asset/`` links (cache bust)
  - ``live_source``      — read promotion-pointer JSON under ``workspace/meta/live_source``
  - ``live_prompt``      — sidebar ``active_prompt`` from pointer + history metadata
  - ``job_runs``         — persisted job snapshots
  - ``asset_index`` / ``asset_meta`` / ``workspace_palette`` — asset + palette DB helpers
"""
