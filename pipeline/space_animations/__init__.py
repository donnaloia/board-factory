"""Space Animations — looping clip pipeline for committed board spaces.

Sandboxed sibling of ``boardfactory``. Produces short looping animations
(GIF / APNG) from a single static PNG once a space's static art is live.

Strict isolation: this package MUST NOT import from ``boardfactory``,
``cardfactory``, or any other pipeline tree. Cross-pipeline duplication is
acceptable per the workspace ``.cursorrules``.

Top-level layout (mirrors ``boardfactory``):

    config.py            env-driven knobs (candidates, fps, duration, encoding)
    ops/                 atomic operations (entry points called by the app)
    steps/               internal stages (loop closure, encoding)
    providers/           image-to-video provider adapters (mock + real later)
    schemas/             Pydantic models for the on-disk proposal manifest
    tests/               pytest covering the mock provider end-to-end

The web app calls into this package only through ``ops.animate_space.animate_space``
and the provider factory; everything else is internal.
"""

__version__ = "0.1.0"
