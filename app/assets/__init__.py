"""``assets``: per-cell generated artifacts (live + history files).

The pipeline calls ``boardfactory.assets`` to write PNG files (live + history)
and emits ``history_push`` events that this domain catches in
:mod:`assets.repository.on_asset_event` to index a row in
``asset_versions``. Browsers then reach files through routes registered in
:mod:`assets.routes_api`, with cache-busting URLs built by
:func:`assets.services.board_asset_url`.

Files in this package
---------------------

``repository``
    Pure DB I/O for ``asset_versions`` rows: insert + read metadata.
    Listens to ``history_push`` events from the pipeline.

``services``
    URL builders + cache-bust helpers used by views and routes when
    rendering links to ``/asset/...``.

``routes_api``
    HTTP routes serving ``/asset/...`` and ``/mockup/...`` under the nested
    board URL prefix.
"""
