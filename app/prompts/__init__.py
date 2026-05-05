"""``prompts``: build text prompts and resolve "which prompt belongs to this cell".

The three concerns here are different enough that this domain keeps them
in separate files instead of collapsing into one ``services.py``:

``live``
    Resolve the *active* prompt shown in the cell side panel — the
    promotion pointer wins; fall back to the newest live history row's
    prompt; finally fall back to the catalog's static prompt.

``live_source``
    Read ``workspace/meta/live_source/<cat>/<id>.json`` (the small
    "which history file did we promote?" pointer the pipeline writes).
    Pure read of one JSON file via ``BoardStore``.

``mockup``
    Compose the OpenAI-Images prompt for the AI mockup on the setup
    page: stitches user text + layout-aware geometry hints + style line
    + framing suffix.

Anything domain-y about generation lives here; per-cell history reads
live in :mod:`assets.repository`.
"""
