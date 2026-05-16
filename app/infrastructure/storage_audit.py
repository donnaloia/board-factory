"""Storage audit: compare files on disk against DB pointers.

Walks the three runtime artifact roots (boards / decks / tokens) and
classifies every file into a known *bucket*. For buckets that have a DB
pointer (e.g. ``asset_versions.rel_path``, ``cells.live_asset_version_id``),
we also check whether each row resolves to an existing file (*dangling
pointers*).

Buckets are grouped into three lifecycles:

* ``tracked``      — should map 1:1 to a DB row. Files without a row are
                     **orphans**; rows without a file are **dangling**.
* ``transient``    — intermediate generation artifacts with no DB row
                     (proposals, previews, masks, …). Not deleted by
                     :func:`prune_orphan_files` — they need explicit
                     lifecycle hooks or a separate policy.
* ``unknown``      — under a recognised root but not matching any known
                     pattern. Not auto-deleted.

**Orphan cleanup:** :func:`prune_orphan_files` deletes every file whose
lifecycle is ``tracked`` and ``referenced is False`` across all three
domains. Invoke via ``make audit-storage`` (report only) or
``make audit-storage ARGS='--apply'`` (report + delete).

Usage::

    from infrastructure.storage_audit import run_audit, render_text, prune_orphan_files
    report = run_audit()
    print(render_text(report))
    prune_orphan_files(report, apply=True)

Env overrides:

* ``BOARDFACTORY_BOARDS_DIR``   — boards root (default ``$REPO/data/boards``)
* ``CARDFACTORY_DECKS_DIR``     — decks root  (default ``$REPO/data/decks``)
* ``BOARDFACTORY_TOKENS_DIR``   — tokens root (default ``$REPO/data/tokens``)
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from sqlalchemy import select

from domains.spaces.assets.models import AssetVersionRecord
from domains.boards.models import OwnedBoardRecord
from domains.cards.models import (
    CardDeckRecord,
    CardFrameCandidateRecord,
    CardSlotRecord,
)
from domains.spaces.animations.models import SpaceAnimationRecord
from domains.spaces.models import CellRecord
from domains.tokens.models import TokenRecord
from infrastructure.db import session_scope


# ────────────────────────── value types ──────────────────────────


@dataclass(frozen=True)
class FileEntry:
    """One file on disk plus our verdict about it."""

    rel_path: str  # relative to ``data/`` root (or whatever root is configured)
    size_bytes: int
    bucket: str
    lifecycle: str  # "tracked" | "transient" | "unknown"
    referenced: bool | None  # True/False for tracked; None for transient/unknown
    note: str = ""


@dataclass(frozen=True)
class DanglingPointer:
    """A DB row whose pointer references a file that does not exist on disk."""

    table: str
    column: str
    pk: str
    expected_rel: str


@dataclass
class BucketSummary:
    bucket: str
    lifecycle: str
    file_count: int = 0
    total_bytes: int = 0
    orphan_count: int = 0  # tracked files with no DB row
    orphan_bytes: int = 0


@dataclass
class AuditReport:
    boards_root: Path
    decks_root: Path
    tokens_root: Path
    files: list[FileEntry] = field(default_factory=list)
    dangling: list[DanglingPointer] = field(default_factory=list)

    def summarize(self) -> dict[str, BucketSummary]:
        out: dict[str, BucketSummary] = {}
        for f in self.files:
            s = out.setdefault(
                f.bucket, BucketSummary(bucket=f.bucket, lifecycle=f.lifecycle)
            )
            s.file_count += 1
            s.total_bytes += f.size_bytes
            if f.lifecycle == "tracked" and f.referenced is False:
                s.orphan_count += 1
                s.orphan_bytes += f.size_bytes
        return out

    def orphan_files(self) -> list[FileEntry]:
        """Tracked files with no DB pointer — safe targets for :func:`prune_orphan_files`."""
        return [
            f for f in self.files if f.lifecycle == "tracked" and f.referenced is False
        ]


@dataclass
class PruneResult:
    """Outcome of :func:`prune_orphan_files`."""

    dry_run: bool
    deleted_files: int = 0
    deleted_bytes: int = 0
    removed_empty_dirs: int = 0
    errors: list[str] = field(default_factory=list)


# ────────────────────────── root resolution ──────────────────────────


def _repo_root() -> Path:
    return Path(os.environ.get("BOARDFACTORY_REPO", "/repo"))


def _boards_root() -> Path:
    explicit = os.environ.get("BOARDFACTORY_BOARDS_DIR", "").strip()
    return Path(explicit) if explicit else _repo_root() / "data" / "boards"


def _decks_root() -> Path:
    explicit = os.environ.get("CARDFACTORY_DECKS_DIR", "").strip()
    return Path(explicit) if explicit else _repo_root() / "data" / "decks"


def _tokens_root() -> Path:
    explicit = os.environ.get("BOARDFACTORY_TOKENS_DIR", "").strip()
    return Path(explicit) if explicit else _repo_root() / "data" / "tokens"


# ────────────────────────── DB indexes ──────────────────────────


@dataclass(frozen=True)
class _DbIndex:
    """Snapshot of every pointer we cross-check against. Built once per audit."""

    board_ids: set[str]
    # ``owned_boards`` keyed by (user_id, board_id). Disk layout is
    # ``<boards_root>/<user_id>/<board_id>/...`` so we need the pair.
    owned_board_pairs: set[tuple[str, str]]
    deck_ids: set[str]
    token_ids: set[str]
    # ``cells`` keyed by (board_id, plural_category, slug)
    cell_ids: set[tuple[str, str, str]]
    # ``asset_versions`` keyed by (board_id, rel_path under board root)
    asset_version_paths: set[tuple[str, str]]
    # ``space_animations`` keyed by (board_id, rel_path)
    space_animation_paths: set[tuple[str, str]]
    # Card slot live rel-paths keyed by (deck_id, rel_path under deck root)
    card_slot_live_paths: set[tuple[str, str]]
    # Card frame candidates keyed by (deck_id, rel_path under deck root)
    card_frame_paths: set[tuple[str, str]]
    # Decks that have a committed frame
    decks_with_committed_frame: set[str]
    # Tokens that have ``live_run_id`` set
    tokens_with_live: set[str]


_KIND_TO_CATEGORY = {
    "perimeter": "spaces",
    "functional": "panels",
    "centerpiece": "centerpiece",
}


def _normalize_workspace_rel(rel: str) -> str:
    """Return ``rel`` guaranteed to include the ``workspace/`` prefix.

    Two domains disagree about how they store workspace-relative paths:
    ``asset_versions.rel_path`` strips ``workspace/`` (it lives implicitly
    under the workspace dir), while ``space_animations.rel_path`` keeps
    the prefix. Normalize on read so the audit can cross-check on-disk
    files with one consistent shape.
    """
    if rel.startswith("workspace/"):
        return rel
    return f"workspace/{rel}"


def _load_db_index() -> _DbIndex:
    with session_scope() as s:
        owned_rows = list(
            s.execute(select(OwnedBoardRecord.user_id, OwnedBoardRecord.board_uuid))
        )
        owned_board_pairs = {(u, b) for u, b in owned_rows}
        board_ids = {b for _, b in owned_board_pairs}
        deck_ids = {d for (d,) in s.execute(select(CardDeckRecord.id))}
        token_ids = {t for (t,) in s.execute(select(TokenRecord.id))}

        cell_rows = list(
            s.execute(select(CellRecord.board_uuid, CellRecord.kind, CellRecord.slug))
        )
        cell_ids: set[tuple[str, str, str]] = set()
        for board, kind, slug in cell_rows:
            cat = _KIND_TO_CATEGORY.get(kind, kind)
            cell_ids.add((board, cat, slug))

        av_rows = list(
            s.execute(select(AssetVersionRecord.board_uuid, AssetVersionRecord.rel_path))
        )
        asset_version_paths = {(b, _normalize_workspace_rel(p)) for b, p in av_rows}

        anim_rows = list(
            s.execute(
                select(SpaceAnimationRecord.board_uuid, SpaceAnimationRecord.rel_path)
            )
        )
        space_animation_paths = {
            (b, _normalize_workspace_rel(p)) for b, p in anim_rows
        }

        slot_rows = list(
            s.execute(
                select(CardSlotRecord.deck_id, CardSlotRecord.live_rel_path).where(
                    CardSlotRecord.live_rel_path.is_not(None)
                )
            )
        )
        card_slot_live_paths = {(d, p) for d, p in slot_rows if p}

        cand_rows = list(
            s.execute(
                select(CardFrameCandidateRecord.deck_id, CardFrameCandidateRecord.rel_path)
            )
        )
        card_frame_paths = {(d, p) for d, p in cand_rows}

        committed_rows = list(
            s.execute(
                select(CardDeckRecord.id).where(
                    CardDeckRecord.committed_frame_id.is_not(None)
                )
            )
        )
        decks_with_committed_frame = {d for (d,) in committed_rows}

        live_token_rows = list(
            s.execute(
                select(TokenRecord.id).where(TokenRecord.live_run_id.is_not(None))
            )
        )
        tokens_with_live = {t for (t,) in live_token_rows}

    return _DbIndex(
        board_ids=board_ids,
        owned_board_pairs=owned_board_pairs,
        deck_ids=deck_ids,
        token_ids=token_ids,
        cell_ids=cell_ids,
        asset_version_paths=asset_version_paths,
        space_animation_paths=space_animation_paths,
        card_slot_live_paths=card_slot_live_paths,
        card_frame_paths=card_frame_paths,
        decks_with_committed_frame=decks_with_committed_frame,
        tokens_with_live=tokens_with_live,
    )


# ────────────────────────── classifiers ──────────────────────────


def _bucket_board_file(parts: tuple[str, ...], idx: _DbIndex, board_id: str) -> tuple[str, str, bool | None]:
    """Map a path under ``boards/<id>/`` to ``(bucket, lifecycle, referenced)``.

    ``parts`` is the path *after* the board id, e.g. ``("workspace", "live",
    "spaces", "foo.png")``.
    """
    if not parts:
        return ("board.unknown", "unknown", None)

    top = parts[0]
    if top == "mockup":
        return ("board.mockup", "tracked", board_id in idx.board_ids)
    if top == "export":
        return ("board.export", "transient", None)

    if top != "workspace":
        return ("board.unknown", "unknown", None)

    if len(parts) < 2:
        return ("board.unknown", "unknown", None)

    sub = parts[1]
    rest = parts[2:]

    if sub == "live" and len(rest) >= 2:
        category = rest[0]
        if category == "centerpiece":
            slug = "centerpiece"
        else:
            slug = rest[1].rsplit(".", 1)[0]
        if category in {"spaces", "panels", "centerpiece"}:
            ref = (board_id, category, slug) in idx.cell_ids
            return (f"board.workspace.live.{category}", "tracked", ref)
        return ("board.workspace.live.unknown", "unknown", None)

    if sub == "history" and len(rest) >= 3:
        category, asset_id = rest[0], rest[1]
        if category not in {"spaces", "panels", "centerpiece"}:
            return ("board.workspace.history.unknown", "unknown", None)
        rel_path = "/".join(("workspace",) + parts[1:])
        ref = (board_id, rel_path) in idx.asset_version_paths
        return (f"board.workspace.history.{category}", "tracked", ref)

    if sub == "animations" and len(rest) >= 1:
        if len(rest) >= 2 and rest[1] == "_proposals":
            return ("board.workspace.animations.proposals", "transient", None)
        if len(rest) >= 2 and rest[1] == "history":
            # Legacy archive flow (now removed). Surface as orphan: nothing
            # references these clips, so they should be cleaned up.
            return ("board.workspace.animations.history", "tracked", False)
        if len(rest) >= 2 and rest[-1] in {"live.gif", "live.apng"}:
            rel_path = "/".join(parts)
            ref = (board_id, rel_path) in idx.space_animation_paths
            return ("board.workspace.animations.live", "tracked", ref)
        return ("board.workspace.animations.unknown", "unknown", None)

    if sub == "frames":
        if len(rest) >= 1 and rest[0] == "_proposals":
            return ("board.workspace.frames.proposals", "transient", None)
        return ("board.workspace.frames.house", "transient", None)

    if sub == "tokens":
        return ("board.workspace.tokens.legacy", "transient", None)

    if sub == "preview":
        return ("board.workspace.preview", "transient", None)

    if sub == "style":
        return ("board.workspace.style", "tracked", board_id in idx.board_ids)

    return ("board.unknown", "unknown", None)


def _bucket_deck_file(parts: tuple[str, ...], idx: _DbIndex, deck_id: str) -> tuple[str, str, bool | None]:
    if not parts:
        return ("deck.unknown", "unknown", None)
    top = parts[0]
    rest = parts[1:]

    if top == "frames":
        if rest[:1] == ("candidates",) and len(rest) >= 3:
            rel_path = "/".join(parts)
            ref = (deck_id, rel_path) in idx.card_frame_paths
            return ("deck.frames.candidates", "tracked", ref)
        if rest[:1] == ("committed",):
            ref = deck_id in idx.decks_with_committed_frame
            return ("deck.frames.committed", "tracked", ref)
        return ("deck.frames.unknown", "unknown", None)

    if top == "cards" and len(rest) >= 2:
        # rest = (slot_index, "live"/"history"/"masks", ...)
        section = rest[1]
        if section == "live":
            rel_path = "/".join(parts)
            ref = (deck_id, rel_path) in idx.card_slot_live_paths
            return ("deck.cards.live", "tracked", ref)
        if section == "history":
            # Cards no longer keep history. Any file under cards/<idx>/history/
            # is from a previous version of the regen path and counts as an
            # orphan — delete via ``make audit-storage ARGS='--apply'``.
            return ("deck.cards.history", "tracked", False)
        if section == "masks":
            return ("deck.cards.masks", "transient", None)
        return ("deck.cards.unknown", "unknown", None)

    if top == "prompts.json":
        return ("deck.prompts", "tracked", deck_id in idx.deck_ids)

    return ("deck.unknown", "unknown", None)


def _bucket_token_file(parts: tuple[str, ...], idx: _DbIndex, token_id: str) -> tuple[str, str, bool | None]:
    if not parts:
        return ("token.unknown", "unknown", None)
    top = parts[0]
    rest = parts[1:]

    if top == "design_lock.json":
        return ("token.design_lock", "tracked", token_id in idx.token_ids)
    if top == "references":
        return ("token.references", "tracked", token_id in idx.token_ids)
    if top == "candidates":
        return ("token.candidates", "transient", None)
    if top == "clips":
        return ("token.clips", "transient", None)
    if top == "animations":
        if rest[:1] == ("live",):
            return ("token.animations.live", "tracked", token_id in idx.tokens_with_live)
        if rest[:1] == ("history",):
            return ("token.animations.history", "transient", None)
        return ("token.animations.unknown", "unknown", None)
    return ("token.unknown", "unknown", None)


# ────────────────────────── disk walks ──────────────────────────


def _walk(root: Path) -> Iterator[Path]:
    if not root.exists():
        return
    for p in root.rglob("*"):
        if p.is_file():
            yield p


def _rel_parts(path: Path, base: Path) -> tuple[str, ...]:
    return path.relative_to(base).parts


# ────────────────────────── audit runner ──────────────────────────


def run_audit() -> AuditReport:
    """Walk all three roots and produce a full report. Read-only."""
    boards_root = _boards_root()
    decks_root = _decks_root()
    tokens_root = _tokens_root()

    idx = _load_db_index()
    report = AuditReport(
        boards_root=boards_root, decks_root=decks_root, tokens_root=tokens_root
    )

    _walk_boards(boards_root, idx, report)
    _walk_decks(decks_root, idx, report)
    _walk_tokens(tokens_root, idx, report)

    _collect_dangling_pointers(idx, report)

    return report


def resolve_file_path(report: AuditReport, entry: FileEntry) -> Path | None:
    """Map a :class:`FileEntry` ``rel_path`` to an absolute path on disk."""
    if entry.rel_path.startswith("boards/"):
        rel = entry.rel_path.removeprefix("boards/")
        return report.boards_root / rel
    if entry.rel_path.startswith("decks/"):
        rel = entry.rel_path.removeprefix("decks/")
        return report.decks_root / rel
    if entry.rel_path.startswith("tokens/"):
        rel = entry.rel_path.removeprefix("tokens/")
        return report.tokens_root / rel
    return None


def _prune_empty_parents(path: Path, stop_at: Path) -> int:
    """Remove empty ancestor directories up to (but not including) ``stop_at``."""
    removed = 0
    current = path.parent.resolve()
    stop = stop_at.resolve()
    while current != stop:
        try:
            current.relative_to(stop)
        except ValueError:
            break
        try:
            current.rmdir()
            removed += 1
        except OSError:
            break
        current = current.parent
    return removed


def prune_stale_workspace(report: AuditReport, *, apply: bool = False) -> PruneResult:
    """Remove generation leftovers that have no DB pointer (transient buckets).

    Deletes, when present:

    * ``workspace/tokens/`` — legacy pre–top-level token layout
    * ``workspace/*/_proposals/`` — animation / frame pick rounds
    * ``workspace/preview/`` — compositor previews (regenerated on demand)
    * ``workspace/frames/house/`` — frame atelier scratch
    * ``export/`` — one-off export stubs
    * ``decks/.../cards/*/masks/`` — card regen intermediates

    Does **not** touch tracked history/live, mockups, active ``data/tokens/``
    workspaces, or deck live PNGs.
    """
    result = PruneResult(dry_run=not apply)
    targets: list[Path] = []

    if report.boards_root.exists():
        for board_root in report.boards_root.rglob("workspace"):
            if not board_root.is_dir():
                continue
            ws = board_root
            for name in ("tokens", "preview"):
                p = ws / name
                if p.is_dir():
                    targets.append(p)
            frames_house = ws / "frames" / "house"
            if frames_house.is_dir():
                targets.append(frames_house)
            for proposals in ws.rglob("_proposals"):
                if proposals.is_dir():
                    targets.append(proposals)
            export = ws.parent / "export"
            if export.is_dir():
                targets.append(export)

    if report.decks_root.exists():
        for masks in report.decks_root.rglob("masks"):
            if masks.is_dir() and masks.parent.name.isdigit():
                targets.append(masks)

    seen: set[Path] = set()
    for path in sorted(targets, key=lambda p: len(p.parts), reverse=True):
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if not resolved.exists():
            continue
        file_count = sum(1 for _ in resolved.rglob("*") if _.is_file())
        byte_count = sum(f.stat().st_size for f in resolved.rglob("*") if f.is_file())
        if apply:
            try:
                if resolved.is_dir():
                    shutil.rmtree(resolved)
                else:
                    resolved.unlink()
            except OSError as e:
                result.errors.append(f"{resolved}: {e}")
                continue
            decks_stop = report.decks_root.resolve()
            parent_stop = (
                decks_stop
                if str(resolved).startswith(str(decks_stop))
                else report.boards_root.resolve()
            )
            result.removed_empty_dirs += _prune_empty_parents(resolved, parent_stop)
        result.deleted_files += file_count
        result.deleted_bytes += byte_count

    return result


def prune_orphan_files(report: AuditReport, *, apply: bool = False) -> PruneResult:
    """Delete every tracked orphan file in the audit report.

    Only touches files where ``lifecycle == 'tracked'`` and
    ``referenced is False``. Does **not** delete ``transient`` buckets
    (proposals, previews, masks, …) or ``unknown`` paths — those are not
    orphans under the DB-pointer invariant.

    When ``apply`` is False (default), returns counts without unlinking.
    After each successful delete, removes empty parent directories up to
    the relevant domain root (``boards/``, ``decks/``, or ``tokens/``).
    """
    result = PruneResult(dry_run=not apply)
    roots = {
        "boards": report.boards_root.resolve(),
        "decks": report.decks_root.resolve(),
        "tokens": report.tokens_root.resolve(),
    }

    for entry in report.orphan_files():
        path = resolve_file_path(report, entry)
        if path is None:
            result.errors.append(f"unresolved rel_path: {entry.rel_path}")
            continue
        if not path.is_file():
            continue

        if apply:
            try:
                path.unlink()
            except OSError as e:
                result.errors.append(f"{entry.rel_path}: {e}")
                continue
            prefix = entry.rel_path.split("/", 1)[0]
            stop = roots.get(prefix)
            if stop is not None:
                result.removed_empty_dirs += _prune_empty_parents(path, stop)

        result.deleted_files += 1
        result.deleted_bytes += entry.size_bytes

    return result


def _walk_boards(root: Path, idx: _DbIndex, report: AuditReport) -> None:
    """Boards live at ``<root>/<user_id>/<board_id>/...``.

    A path with fewer than two segments is itself an orphan layout (a board
    dir at the wrong depth). Otherwise we treat the (user_id, board_id) pair
    as the ownership key — any pair not in ``owned_boards`` is orphan.
    """
    for path in _walk(root):
        parts = _rel_parts(path, root)
        rel = f"boards/{path.relative_to(root).as_posix()}"
        size = path.stat().st_size

        if len(parts) < 2:
            report.files.append(
                FileEntry(
                    rel_path=rel,
                    size_bytes=size,
                    bucket="board.orphan_root",
                    lifecycle="tracked",
                    referenced=False,
                    note="file directly under boards root (not a <user_id>/<board_id>/ child)",
                )
            )
            continue

        user_id, board_id = parts[0], parts[1]
        if (user_id, board_id) not in idx.owned_board_pairs:
            report.files.append(
                FileEntry(
                    rel_path=rel,
                    size_bytes=size,
                    bucket="board.orphan_root",
                    lifecycle="tracked",
                    referenced=False,
                    note=f"no owned_boards row for user_id={user_id} board_id={board_id}",
                )
            )
            continue

        bucket, lifecycle, referenced = _bucket_board_file(parts[2:], idx, board_id)
        report.files.append(
            FileEntry(
                rel_path=rel,
                size_bytes=size,
                bucket=bucket,
                lifecycle=lifecycle,
                referenced=referenced,
            )
        )


def _walk_decks(root: Path, idx: _DbIndex, report: AuditReport) -> None:
    for path in _walk(root):
        parts = _rel_parts(path, root)
        if not parts:
            continue
        deck_id = parts[0]
        if deck_id not in idx.deck_ids:
            report.files.append(
                FileEntry(
                    rel_path=f"decks/{path.relative_to(root).as_posix()}",
                    size_bytes=path.stat().st_size,
                    bucket="deck.orphan_root",
                    lifecycle="tracked",
                    referenced=False,
                    note="no card_decks row for this deck id",
                )
            )
            continue
        bucket, lifecycle, referenced = _bucket_deck_file(parts[1:], idx, deck_id)
        report.files.append(
            FileEntry(
                rel_path=f"decks/{path.relative_to(root).as_posix()}",
                size_bytes=path.stat().st_size,
                bucket=bucket,
                lifecycle=lifecycle,
                referenced=referenced,
            )
        )


def _walk_tokens(root: Path, idx: _DbIndex, report: AuditReport) -> None:
    for path in _walk(root):
        parts = _rel_parts(path, root)
        if not parts:
            continue
        token_id = parts[0]
        if token_id not in idx.token_ids:
            report.files.append(
                FileEntry(
                    rel_path=f"tokens/{path.relative_to(root).as_posix()}",
                    size_bytes=path.stat().st_size,
                    bucket="token.orphan_root",
                    lifecycle="tracked",
                    referenced=False,
                    note="no token_records row for this token id",
                )
            )
            continue
        bucket, lifecycle, referenced = _bucket_token_file(parts[1:], idx, token_id)
        report.files.append(
            FileEntry(
                rel_path=f"tokens/{path.relative_to(root).as_posix()}",
                size_bytes=path.stat().st_size,
                bucket=bucket,
                lifecycle=lifecycle,
                referenced=referenced,
            )
        )


def _collect_dangling_pointers(idx: _DbIndex, report: AuditReport) -> None:
    """For each pointer table, check that the referenced file exists on disk.

    Note: the audit *normalises* every pointer to a ``workspace/...`` form
    (see ``_normalize_workspace_rel``) so the disk-existence check can use
    one consistent path-join. The ``expected_rel`` we report back uses
    the same canonical shape so users can grep for it on disk.
    """
    board_owner: dict[str, str] = {b: u for u, b in idx.owned_board_pairs}

    def _check_board_pointer(table: str, board_id: str, rel_path: str) -> None:
        user_id = board_owner.get(board_id)
        if user_id is None:
            report.dangling.append(
                DanglingPointer(
                    table=table,
                    column="board_uuid",
                    pk=f"{board_id}:{rel_path}",
                    expected_rel=f"(no owned_boards row for {board_id})",
                )
            )
            return
        full = report.boards_root / user_id / board_id / rel_path
        if not full.exists():
            report.dangling.append(
                DanglingPointer(
                    table=table,
                    column="rel_path",
                    pk=f"{board_id}:{rel_path}",
                    expected_rel=f"boards/{user_id}/{board_id}/{rel_path}",
                )
            )

    for board_id, rel_path in idx.asset_version_paths:
        _check_board_pointer("asset_versions", board_id, rel_path)

    for board_id, rel_path in idx.space_animation_paths:
        _check_board_pointer("space_animations", board_id, rel_path)

    for deck_id, rel_path in idx.card_slot_live_paths:
        full = report.decks_root / deck_id / rel_path
        if not full.exists():
            report.dangling.append(
                DanglingPointer(
                    table="card_slot_records",
                    column="live_rel_path",
                    pk=f"{deck_id}:{rel_path}",
                    expected_rel=f"decks/{deck_id}/{rel_path}",
                )
            )

    for deck_id, rel_path in idx.card_frame_paths:
        full = report.decks_root / deck_id / rel_path
        if not full.exists():
            report.dangling.append(
                DanglingPointer(
                    table="card_frame_candidates",
                    column="rel_path",
                    pk=f"{deck_id}:{rel_path}",
                    expected_rel=f"decks/{deck_id}/{rel_path}",
                )
            )


# ────────────────────────── rendering ──────────────────────────


def _human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f}{unit}" if unit != "B" else f"{n}{unit}"
        n /= 1024  # type: ignore[assignment]
    return f"{n}TB"


def render_text(report: AuditReport) -> str:
    """Human-readable plain-text report. Stable enough to use in tests."""
    summary = report.summarize()
    by_lifecycle: dict[str, list[BucketSummary]] = {
        "tracked": [],
        "transient": [],
        "unknown": [],
    }
    for s in summary.values():
        by_lifecycle.setdefault(s.lifecycle, []).append(s)
    for lst in by_lifecycle.values():
        lst.sort(key=lambda s: (-s.total_bytes, s.bucket))

    lines: list[str] = []
    lines.append("Storage audit")
    lines.append("=============")
    lines.append(f"Boards root:  {report.boards_root}")
    lines.append(f"Decks root:   {report.decks_root}")
    lines.append(f"Tokens root:  {report.tokens_root}")
    lines.append("")

    total_files = sum(s.file_count for s in summary.values())
    total_bytes = sum(s.total_bytes for s in summary.values())
    total_orphans = sum(s.orphan_count for s in summary.values())
    total_orphan_bytes = sum(s.orphan_bytes for s in summary.values())
    lines.append(
        f"Totals: {total_files} files, {_human_bytes(total_bytes)} on disk, "
        f"{total_orphans} orphan files ({_human_bytes(total_orphan_bytes)}), "
        f"{len(report.dangling)} dangling DB pointers."
    )
    lines.append("")

    for lifecycle in ("tracked", "transient", "unknown"):
        rows = by_lifecycle.get(lifecycle, [])
        if not rows:
            continue
        lines.append(f"[{lifecycle}]")
        lines.append(
            f"  {'bucket':<44} {'files':>7} {'size':>10} {'orphans':>9} {'orphan size':>12}"
        )
        for s in rows:
            lines.append(
                f"  {s.bucket:<44} "
                f"{s.file_count:>7} "
                f"{_human_bytes(s.total_bytes):>10} "
                f"{s.orphan_count:>9} "
                f"{_human_bytes(s.orphan_bytes):>12}"
            )
        lines.append("")

    if report.dangling:
        lines.append("Dangling DB pointers (row exists, file missing):")
        for d in report.dangling[:50]:
            lines.append(f"  {d.table}.{d.column} [{d.pk}] -> {d.expected_rel}")
        extra = len(report.dangling) - 50
        if extra > 0:
            lines.append(f"  ... and {extra} more.")
        lines.append("")

    orphan_files = report.orphan_files()
    if orphan_files:
        lines.append("Orphan files (no DB row points at them, sample):")
        orphan_files.sort(key=lambda f: -f.size_bytes)
        for f in orphan_files[:25]:
            note = f"  -- {f.note}" if f.note else ""
            lines.append(f"  [{f.bucket}] {_human_bytes(f.size_bytes):>9}  {f.rel_path}{note}")
        extra = len(orphan_files) - 25
        if extra > 0:
            lines.append(f"  ... and {extra} more.")
        lines.append(
            "  Run with --apply to delete all tracked orphans "
            "(boards, decks, tokens). Transient files are not removed."
        )
        lines.append("")

    return "\n".join(lines)


def render_prune_summary(prune: PruneResult) -> str:
    verb = "Would delete" if prune.dry_run else "Deleted"
    lines = [
        "",
        "Orphan prune",
        "============",
        f"{verb} {prune.deleted_files} files ({_human_bytes(prune.deleted_bytes)}).",
    ]
    if prune.removed_empty_dirs:
        lines.append(f"Removed {prune.removed_empty_dirs} empty directories.")
    if prune.errors:
        lines.append(f"{len(prune.errors)} errors:")
        for err in prune.errors[:20]:
            lines.append(f"  {err}")
        if len(prune.errors) > 20:
            lines.append(f"  ... and {len(prune.errors) - 20} more.")
    if prune.dry_run and prune.deleted_files:
        lines.append("(dry run; pass --apply to actually delete)")
    return "\n".join(lines)
