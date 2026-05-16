"""Provider selection.

Three providers ship today:

  * ``sora`` (default) — calls the OpenAI Sora 2 video API for *true*
    image-to-video and decodes the MP4 to PIL frames. Uses the user's
    ChatGPT / OpenAI API key. Higher fidelity, higher cost (per-second
    billing), longer latency (several minutes per job). See
    ``sora.py``. Aliases: ``sora``, ``sora-2``, ``sora-2-pro``.
  * ``openai`` — gpt-image-2 destination still + local crossfade morph,
    directed by a one-shot gpt-4o vision pass. Cheaper and faster than
    Sora but limited to crossfade-style motion. See ``openai.py`` and
    ``_motion_director.py``. Aliases: ``openai``, ``chatgpt``, ``gpt``,
    ``gpt-image-2``.
  * ``mock`` — offline; for tests and local dev without an API key.

The factory is the single place an adapter discovers what's available.
Pipeline isolation: providers never import from sibling pipelines.
"""

from __future__ import annotations

import os

from .base import I2VProvider
from .mock import MockI2VProvider
from .openai import OpenAII2VProvider
from .sora import SoraI2VProvider


_SORA_ALIASES = ("sora", "sora-2", "sora2")
_SORA_PRO_ALIASES = ("sora-pro", "sora-2-pro", "sora2-pro")
_OPENAI_ALIASES = ("openai", "chatgpt", "gpt", "gpt-image-2")
_MOCK_ALIASES = ("mock", "fake", "offline")


def select_provider(
    name: str,
    *,
    openai_api_key: str | None = None,
) -> I2VProvider:
    """Return the I2V provider for ``name``.

    OpenAI-backed providers (Sora + gpt-image-2) require the per-user
    OpenAI API key; passing ``None`` raises a clear error rather than
    silently falling back to mock — per .cursorrules, "no silent
    fallbacks for required state".

    Unknown names also raise so a typo doesn't get mistaken for the
    default provider.
    """
    n = (name or "").strip().lower()
    if n in _SORA_ALIASES or n in _SORA_PRO_ALIASES:
        _require_openai_key("Sora", openai_api_key)
        model = "sora-2-pro" if n in _SORA_PRO_ALIASES else "sora-2"
        return SoraI2VProvider(
            api_key=openai_api_key.strip(),
            model=_sora_model_override(model),
            seconds=_sora_seconds_override(),
        )
    if n in _OPENAI_ALIASES:
        _require_openai_key("OpenAI", openai_api_key)
        return OpenAII2VProvider(api_key=openai_api_key.strip())
    if n in _MOCK_ALIASES:
        return MockI2VProvider()
    raise ValueError(
        f"Unknown space-animations provider: {name!r}. "
        f"Known providers: {sorted(set(_SORA_ALIASES + _SORA_PRO_ALIASES + _OPENAI_ALIASES + _MOCK_ALIASES))}."
    )


def _require_openai_key(label: str, openai_api_key: str | None) -> None:
    if (openai_api_key or "").strip():
        return
    raise RuntimeError(
        f"{label} animation provider needs an OpenAI / ChatGPT API "
        "key. Save it in Account → Connections → OpenAI / ChatGPT "
        "(per-user), or set SPACE_ANIMATIONS_PROVIDER=mock for "
        "offline use."
    )


def _sora_model_override(default: str) -> str:
    """Allow operators to pin the Sora model via env."""
    raw = (os.environ.get("SPACE_ANIMATIONS_SORA_MODEL") or "").strip().lower()
    if raw in ("sora-2", "sora-2-pro"):
        return raw
    return default


def _sora_seconds_override() -> int:
    """Allow operators to pin Sora ``seconds`` via env (default 4)."""
    raw = (os.environ.get("SPACE_ANIMATIONS_SORA_SECONDS") or "").strip()
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return 4
    if n in (4, 8, 12, 16, 20):
        return n
    return 4
