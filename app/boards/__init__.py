"""Boards domain — the central entity of the application.

Every board has:

  * a row in ``board_games`` (column-typed catalog header + body_json layout),
  * a row in ``owned_boards`` (which user owns it, what its URL slug is),
  * a tree on disk under ``<boards-root>/<user_id>/<board_uuid>/``,
  * a set of ``cells`` rows (see the cells/ domain).

Layout (per ``app/ARCHITECTURE.md``):

  * ``repository.py`` — DB I/O against ``board_games`` + ``owned_boards``,
                        plus the on-disk root resolver.
  * ``services.py``   — Catalog assembly (joining cells + body_json + columns
                        into the legacy nested dict), board CRUD, generation
                        block validation.
"""
