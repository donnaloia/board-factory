"""Space-animation slice of the spaces domain.

Owns the persistence + HTTP surface for committed live animations on cells.
Per ``tech-spec/space-animations/spec.md`` §G7 / §9, the heavy work lives in the
sandbox pipeline at ``pipeline/space_animations/``; everything in this
package is orchestration:

  * :mod:`models`        — ``space_animations`` ORM table + ``cells.live_animation_id`` FK.
  * :mod:`repository`    — DB I/O for ``space_animations`` rows.
  * :mod:`manifest_io`   — disk paths + read of the per-job proposal manifest.
  * :mod:`services`      — gate (``assert_can_animate``), enqueue, commit chain.
  * :mod:`routes_api`    — nested REST endpoints + file serving for the UI.

Allow-list (MVP, per implementation plan): only ``cells.kind = 'functional'``.
A per-cell flag column is the documented upgrade path if product later wants
per-space override.
"""
