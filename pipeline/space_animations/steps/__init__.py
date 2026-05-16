"""Internal pipeline stages: loop closure + encoding."""

from .encode import encode_clip, file_extension_for
from .loop_close import close_loop

__all__ = ["close_loop", "encode_clip", "file_extension_for"]
