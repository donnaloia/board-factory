"""Per-board data store — abstraction over local disk vs (future) object storage.

Every per-board read/write in the application and pipeline goes through a
``BoardStore``. The default ``LocalBoardStore`` is backed by the local
filesystem under ``<BOARDFACTORY_REPO>/data/boards/`` (override with
``BOARDFACTORY_BOARDS_DIR``); a future ``S3BoardStore`` can drop in behind
the same protocol so the same code runs against a bucket without changes
to the call sites.

Two surfaces:

1. **Bytes-shaped** (``open_read``, ``read_bytes``, ``write_bytes``,
   ``delete``, ``exists``, ``list``, ``stat``, ``url_for``,
   ``signed_get_url``) — what HTTP routes and the asset index use. These
   work cleanly against both local disk and an S3 bucket.

2. **Local-path escape hatch** (``LocalBoardStore.local_path``) — the
   pipeline package today does ``PIL.Image.open(path)`` and
   ``path.write_bytes(data)`` in dozens of places. Forcing all of those
   through a BinaryIO interface would be a much larger refactor for very
   little gain (each per-cell job materializes 30+ files; staying on
   ``Path`` keeps the pipeline package usable as a library on its own).
   When we add an S3 backend, the pipeline will materialize the few files
   it needs (palette, style sheet, mockup) to a per-job temp dir at job
   start — a narrow, well-scoped piece of work.
"""

from __future__ import annotations

import os
import shutil
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import BinaryIO, Iterator, Protocol, runtime_checkable


# ────────────────────────── value types ──────────────────────────


@dataclass(frozen=True)
class FileStat:
    """Lightweight stat result that works for both local disk and S3."""

    size: int
    mtime_ms: int


# ────────────────────────── exceptions ──────────────────────────


class StoreError(Exception):
    """Base class for store-level failures."""


class StorePathError(StoreError, ValueError):
    """Raised when ``rel`` would escape the per-board prefix."""


class StoreFileNotFound(StoreError, FileNotFoundError):
    """Raised when an operation expects a file that does not exist."""


# ────────────────────────── protocol ──────────────────────────


@runtime_checkable
class BoardStore(Protocol):
    """Per-board data store. Implementations must enforce path safety:
    every ``rel`` is treated as a forward-slash path under the board's
    root and must not escape it (no ``..``, no absolute paths).
    """

    # ── byte-level ──
    def exists(self, board_id: str, rel: str) -> bool: ...
    def read_bytes(self, board_id: str, rel: str) -> bytes: ...
    def open_read(self, board_id: str, rel: str) -> "_ReadCtx": ...
    def write_bytes(self, board_id: str, rel: str, data: bytes) -> None: ...
    def delete(self, board_id: str, rel: str) -> None: ...
    def list(self, board_id: str, rel_dir: str = "") -> list[str]: ...
    def stat(self, board_id: str, rel: str) -> FileStat: ...
    def url_for(self, board_id: str, rel: str) -> str: ...
    def signed_get_url(self, board_id: str, rel: str) -> str | None: ...

    # ── board lifecycle ──
    def board_exists(self, board_id: str) -> bool: ...
    def list_board_ids(self) -> list[str]: ...
    def create_board_skeleton(self, board_id: str) -> None: ...
    def delete_board(self, board_id: str) -> None: ...


class _ReadCtx(Protocol):
    """Context manager yielded by ``open_read``."""

    def __enter__(self) -> BinaryIO: ...
    def __exit__(self, *args) -> None: ...


# ────────────────────────── path safety helper ──────────────────────────


def _safe_join(root: Path, rel: str) -> Path:
    """Resolve ``rel`` underneath ``root`` and reject escapes.

    ``rel`` is treated as a POSIX-style relative path. Empty string returns
    ``root`` itself.
    """
    if rel.startswith("/") or "\\" in rel:
        raise StorePathError(f"Absolute or backslash paths are not allowed: {rel!r}")
    target = (root / rel).resolve()
    root_resolved = root.resolve()
    if target != root_resolved and root_resolved not in target.parents:
        raise StorePathError(f"{rel!r} resolves outside the board root")
    return target


# ────────────────────────── local-disk implementation ──────────────────────────


class LocalBoardStore:
    """``BoardStore`` backed by a local filesystem directory.

    Each board lives at ``<root>/<board_id>/`` and the existing layout
    (``mockup/``, ``workspace/``, ``export/``) sits underneath. The
    ``rel`` argument to every method is a POSIX-style path relative to
    that board root — e.g. ``"workspace/live/spaces/foo.png"``.
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    # ── per-board path resolution ──

    def board_root(self, board_id: str) -> Path:
        """Absolute path to ``<root>/<board_id>/``. Local-only escape hatch."""
        return self._root / board_id

    def local_path(self, board_id: str, rel: str = "") -> Path:
        """Resolve ``rel`` to an absolute on-disk path under the board root.

        Local-only escape hatch for callers that genuinely need a real
        path (PIL ``Image.open``, ``shutil.copy2``, the pipeline package).
        Path-safety still applies — a ``..`` in ``rel`` raises.
        """
        return _safe_join(self.board_root(board_id), rel)

    # ── byte-level ──

    def exists(self, board_id: str, rel: str) -> bool:
        try:
            return _safe_join(self.board_root(board_id), rel).exists()
        except StorePathError:
            return False

    def read_bytes(self, board_id: str, rel: str) -> bytes:
        p = _safe_join(self.board_root(board_id), rel)
        if not p.exists():
            raise StoreFileNotFound(f"{board_id}:{rel}")
        return p.read_bytes()

    @contextmanager
    def open_read(self, board_id: str, rel: str) -> Iterator[BinaryIO]:
        p = _safe_join(self.board_root(board_id), rel)
        if not p.exists():
            raise StoreFileNotFound(f"{board_id}:{rel}")
        with p.open("rb") as fh:
            yield fh

    def write_bytes(self, board_id: str, rel: str, data: bytes) -> None:
        p = _safe_join(self.board_root(board_id), rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def delete(self, board_id: str, rel: str) -> None:
        try:
            p = _safe_join(self.board_root(board_id), rel)
        except StorePathError:
            return
        if p.exists():
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()

    def list(self, board_id: str, rel_dir: str = "") -> list[str]:
        """Recursive list of file rel-paths underneath ``rel_dir``.

        Returns POSIX-style strings relative to the board root, sorted.
        Returns ``[]`` if the directory does not exist.
        """
        base = self.board_root(board_id)
        if rel_dir:
            base = _safe_join(self.board_root(board_id), rel_dir)
        if not base.exists():
            return []
        out: list[str] = []
        for p in base.rglob("*"):
            if p.is_file():
                rel = p.relative_to(self.board_root(board_id)).as_posix()
                out.append(rel)
        out.sort()
        return out

    def stat(self, board_id: str, rel: str) -> FileStat:
        p = _safe_join(self.board_root(board_id), rel)
        if not p.exists():
            raise StoreFileNotFound(f"{board_id}:{rel}")
        st = p.stat()
        return FileStat(size=st.st_size, mtime_ms=int(st.st_mtime * 1000))

    def url_for(self, board_id: str, rel: str) -> str:
        """URL the browser can fetch this asset from.

        Local backend serves through the FastAPI route at ``/b/<id>/asset/<rel>``;
        S3 backend will return a presigned GET URL via ``signed_get_url``.
        """
        return f"/b/{board_id}/asset/{rel}"

    def signed_get_url(self, board_id: str, rel: str) -> str | None:
        """Presigned URL the browser can fetch directly without going through
        the app. ``None`` for the local backend (route streams via sendfile).

        S3 backend will return e.g. an https://<bucket>.s3... URL with a
        bounded expiry; the asset route then 302s the browser to it.
        """
        _ = (board_id, rel)
        return None

    # ── board lifecycle ──

    def board_exists(self, board_id: str) -> bool:
        return self.board_root(board_id).is_dir()

    def list_board_ids(self) -> list[str]:
        if not self._root.exists():
            return []
        return sorted(child.name for child in self._root.iterdir() if child.is_dir())

    def create_board_skeleton(self, board_id: str) -> None:
        """Make the empty per-board dir layout. Idempotent."""
        root = self.board_root(board_id)
        if root.exists():
            return
        root.mkdir(parents=True)
        (root / "mockup").mkdir()
        (root / "workspace").mkdir()
        (root / "export").mkdir()

    def delete_board(self, board_id: str) -> None:
        root = self.board_root(board_id)
        if root.exists():
            shutil.rmtree(root)


# ────────────────────────── singleton wiring ──────────────────────────


_DEFAULT_BOARDS_SUBDIR = "data/boards"


def _resolve_boards_dir() -> Path:
    """Where ``LocalBoardStore`` lives by default.

    Order of resolution:

      1. ``BOARDFACTORY_BOARDS_DIR`` (absolute path) — full override.
      2. ``<BOARDFACTORY_REPO>/data/boards`` — current default.
    """
    explicit = os.environ.get("BOARDFACTORY_BOARDS_DIR", "").strip()
    if explicit:
        return Path(explicit)
    repo = Path(os.environ.get("BOARDFACTORY_REPO", "/repo"))
    return repo / _DEFAULT_BOARDS_SUBDIR


_store: BoardStore | None = None
_lock = RLock()


def get_store() -> BoardStore:
    """Return the process-wide store, building it on first use."""
    global _store
    if _store is not None:
        return _store
    with _lock:
        if _store is None:
            backend = os.environ.get("BOARDFACTORY_STORAGE", "local").strip().lower()
            if backend == "local":
                _store = LocalBoardStore(_resolve_boards_dir())
            else:
                raise StoreError(
                    f"Unknown BOARDFACTORY_STORAGE backend: {backend!r}. "
                    "Supported: 'local'."
                )
    return _store


def override_store(store: BoardStore | None) -> None:
    """Test hook: swap the singleton (pass ``None`` to revert to env-driven)."""
    global _store
    with _lock:
        _store = store


def reset_store() -> None:
    """Test hook: drop the cached singleton so the next ``get_store()``
    re-reads the environment.
    """
    global _store
    with _lock:
        _store = None
