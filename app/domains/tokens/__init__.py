"""Tokens domain — Token Factory (user-scoped character tokens).

HTTP, persistence, and job orchestration for the token pipeline
(``pipeline/tokenfactory/``). Each token belongs to a user; an optional
``linked_board_id`` supplies palette/style from a board. Artifacts live under
``data/tokens/<token_id>/`` (design lock, candidates, clips, published atlas).

Layers (per ``app/ARCHITECTURE.md``): ``models``, ``repository``, ``services``,
``routes_html``, ``routes_api``, ``pipeline_jobs``. Palette computation lives
in ``palette.py``.
"""
