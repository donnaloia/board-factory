"""Board cell art — version index, file URLs, and HTTP serving.

Each ``cells`` row can have many generated PNGs (``asset_versions``); one
is promoted to ``workspace/live/…``. The pipeline writes files via
``boardfactory.assets``; this slice indexes rows and serves bytes under
the board URL prefix.

Layers: ``models``, ``repository``, ``services``, ``routes_api``.
"""

from domains.spaces.assets.models import AssetVersionRecord

__all__ = ["AssetVersionRecord"]
