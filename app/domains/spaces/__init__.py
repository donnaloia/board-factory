"""Spaces domain — perimeter spaces, feature panels, centerpiece.

A *cell* is one painted region of a board (DB table ``cells``). Three subtypes share the same
``cells`` row shape (see ``domains.spaces.models.CellRecord``):

  * ``kind == 'perimeter'``   — perimeter tile; geometry comes from
                                ``board_games.body_json.board_spaces.layout``
                                + ``cells.positions_json``.
  * ``kind == 'functional'``  — interior functional UI cell; absolute bbox + target_size
                                stored on the cell row.
  * ``kind == 'centerpiece'`` — exactly one per board; absolute bbox +
                                target_size stored on the cell row.

  * ``models.py``    — ORM mapping for ``CellRecord``.
  * ``status.py``    — ``CellStatus`` value object (readiness for routes + SVG).
  * ``geometry.py`` — ``resolve_position`` for catalog perimeter layout dicts.
  * ``repository.py`` — DB I/O for ``CellRecord`` (CRUD against ``cells``).
  * ``services.py``   — Read-side use cases: per-cell status, batched
                        ``BoardCellStats`` aggregate.
  * ``routes_api.py`` — JSON under ``/api/cell/...`` (GET / PATCH / promote).
"""
