"""Image-to-video provider adapters.

Default provider is :class:`openai.OpenAII2VProvider` (uses the user's
ChatGPT API key + ``gpt-image-2`` + a local morph step). The
:class:`mock.MockI2VProvider` ships alongside for tests and offline
work — see ``factory.select_provider``.

Real text-to-video / Sora providers will register here as sibling
modules with the same :class:`base.I2VProvider` protocol.
"""

from .base import Clip, I2VProvider
from .factory import select_provider
from .mock import MockI2VProvider
from .openai import OpenAII2VProvider

__all__ = [
    "Clip",
    "I2VProvider",
    "MockI2VProvider",
    "OpenAII2VProvider",
    "select_provider",
]
