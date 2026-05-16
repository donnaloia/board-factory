"""Token Factory pipeline.

Isolated subsystem for generating character token sprite sheets. Three operations:

* ``ops.design_explore``  — generate N reference candidates from a text prompt.
* ``ops.generate_clip``   — generate one animation clip (key poses + inter-frame fill).
* ``ops.pack_publish``    — pack all clips into an atlas + manifest.

Providers (``providers/``) abstract the AI backend (mock, openai).
Steps (``steps/``) handle deterministic work: canvas registration, palette
quantization, atlas packing, loop QA.
"""
