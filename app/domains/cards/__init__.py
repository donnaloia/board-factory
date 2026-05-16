"""Cards domain — Card Factory backend (deck/set orchestration, layouts, routes).

All **HTTP and persistence** for Card Factory lives here (`domains.cards`), not under
`pipeline/cardfactory/` (image pipeline only).

Layout templates used by §8 of ``tech-spec/card-factory/spec.md`` are versioned as JSON under
``tech-spec/card-factory/`` until ORM models reference them by ``id``. Canonical canvas aspect
and default pixel size live in ``domains.cards.canvas``.

Layers (when implemented): ``repository.py``, ``services.py``, ``routes_html.py``,
``routes_api.py``, ``models.py`` per ``app/ARCHITECTURE.md``.
"""
