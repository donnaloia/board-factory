"""Token domain — service layer.

Short, top-down chains of named calls. Each public function expresses the
business flow; non-trivial work is factored into private helpers.

Gate invariants (fail-fast):
  ``assert_design_locked`` — required before clip generation.
  ``assert_token_owned``   — required for every per-token write.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from domains.tokens import repository as tokens_repo
from domains.tokens import workspace as token_ws
from domains.tokens.models import TokenRecord
from domains.tokens.palette import (
    TokenPalette,
    compute_token_palette,
    palette_to_dict,
)


# ── exceptions ────────────────────────────────────────────────────────────────

class TokenNotFound(LookupError):
    pass


class TokenExists(ValueError):
    pass


class DesignGateError(RuntimeError):
    """Raised when a pre-condition for an operation is not met."""


class TokenAuthError(PermissionError):
    """Raised when the user does not own the requested token."""


class BoardAuthError(PermissionError):
    """Raised when the user does not own the requested board (for relink)."""


# ── value types ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TokenSummary:
    id: str
    owner_user_id: str
    linked_board_id: str | None
    path_slug: str
    slug: str
    display_name: str
    locomotion_profile: str
    facing_policy: str
    canvas_w: int
    canvas_h: int
    frame_fps: int
    design_locked: bool
    live_run_id: str | None
    created_ms: int
    updated_ms: int


def _to_summary(row: TokenRecord) -> TokenSummary:
    return TokenSummary(
        id=row.id,
        owner_user_id=row.owner_user_id,
        linked_board_id=row.linked_board_id,
        path_slug=row.path_slug,
        slug=row.slug,
        display_name=row.display_name,
        locomotion_profile=row.locomotion_profile,
        facing_policy=row.facing_policy,
        canvas_w=row.canvas_w,
        canvas_h=row.canvas_h,
        frame_fps=row.frame_fps,
        design_locked=row.design_locked,
        live_run_id=row.live_run_id,
        created_ms=row.created_ms,
        updated_ms=row.updated_ms,
    )


def _slug_valid(slug: str) -> bool:
    return bool(re.match(r"^[a-z0-9][a-z0-9-]{0,62}$", slug))


# ── gate assertions ───────────────────────────────────────────────────────────

def assert_design_locked(token: TokenRecord | TokenSummary) -> None:
    if not token.design_locked:
        raise DesignGateError(
            f"Token {token.slug!r} must have a committed design lock before "
            "clip generation or publish. Use the 'Lock Design' action first."
        )


def assert_token_owned(user_id: str, token: TokenRecord | TokenSummary) -> None:
    if token.owner_user_id != user_id:
        raise TokenAuthError(
            f"User {user_id!r} does not own token {token.id!r}."
        )


def assert_board_owned(user_id: str, board_uuid: str) -> None:
    """Authorize a user-board link (relink / commit). Tokens may have no
    board at all; the caller decides whether to require this check."""
    from domains.boards import repository as boards_repo
    if not boards_repo.user_owns_board(user_id, board_uuid):
        raise BoardAuthError(
            f"User {user_id!r} does not own board {board_uuid!r}."
        )


def board_palette_rgb_tuples(board_uuid: str) -> list[tuple[int, int, int]]:
    """Load the board workspace ``palette.json`` as RGB 8-bit tuples."""
    from infrastructure.files import workspace as fs_ws

    p = fs_ws.palette_json_path(board_uuid)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text("utf-8"))
    except Exception:
        return []

    if isinstance(data, list):
        hexes = data
    elif isinstance(data, dict):
        hexes = data.get("colors") or data.get("palette") or []
    else:
        return []

    out: list[tuple[int, int, int]] = []
    for h in hexes:
        h = str(h).strip().lstrip("#")
        if len(h) == 6:
            try:
                out.append((int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)))
            except ValueError:
                pass
    return out


def resolve_design_explore_inputs(row: TokenRecord) -> tuple[str, dict]:
    """``style_sentence`` and JSON-safe ``token_palette`` for design explore.

    Uses ``design_lock.json`` when present (e.g. after a prior lock / unlock).
    Otherwise derives the palette from the linked board (if any) or falls back
    to a neutral default; the style line is always a default built from the
    token's display name / slug.
    """
    lock = token_ws.read_design_lock(row.id)
    if lock is not None:
        style = str(lock.get("style_sentence") or "").strip()
        palette = lock.get("token_palette") or {}
        return style, palette

    if row.linked_board_id:
        board_colors = board_palette_rgb_tuples(row.linked_board_id)
    else:
        board_colors = []  # palette.compute_token_palette returns neutral fallback
    token_palette = compute_token_palette(board_colors)
    style = _default_explore_style_sentence(row)
    return style, palette_to_dict(token_palette)


# ── CRUD ──────────────────────────────────────────────────────────────────────

def create_token(
    *,
    user_id: str,
    display_name: str,
    slug: str | None = None,
    linked_board_id: str | None = None,
    locomotion_profile: str = "walk",
    facing_policy: str = "flip_x",
    canvas_w: int = 96,
    canvas_h: int = 128,
    frame_fps: int = 12,
) -> TokenSummary:
    if linked_board_id:
        assert_board_owned(user_id, linked_board_id)

    slug_in = (slug or "").strip()
    dn = (display_name or "").strip()
    if not slug_in:
        if not dn:
            raise ValueError(
                "display_name is required when slug is omitted (slug is "
                "derived from it)."
            )
        slug_resolved = _allocate_unique_path_slug(user_id, dn)
    else:
        slug_resolved = slug_in

    _validate_create_inputs(slug_resolved, locomotion_profile, facing_policy)
    _assert_path_slug_free(user_id, slug_resolved)

    row = tokens_repo.create_token(
        owner_user_id=user_id,
        linked_board_id=linked_board_id,
        path_slug=slug_resolved,
        slug=slug_resolved,
        display_name=dn,
        locomotion_profile=locomotion_profile,
        facing_policy=facing_policy,
        canvas_w=canvas_w,
        canvas_h=canvas_h,
        frame_fps=frame_fps,
    )
    token_ws.create_token_skeleton(row.id)
    return _to_summary(row)


def get_token(token_id: str) -> TokenSummary:
    row = tokens_repo.get_token(token_id)
    if row is None:
        raise TokenNotFound(token_id)
    return _to_summary(row)


def get_token_by_path(user_id: str, path_slug: str) -> TokenSummary:
    row = tokens_repo.get_token_by_path(user_id, path_slug)
    if row is None:
        raise TokenNotFound(path_slug)
    return _to_summary(row)


def list_tokens(user_id: str) -> list[TokenSummary]:
    return [_to_summary(r) for r in tokens_repo.list_tokens_for_user(user_id)]


def delete_token(user_id: str, token_id: str) -> None:
    row = tokens_repo.get_token(token_id)
    if row is None:
        raise TokenNotFound(token_id)
    assert_token_owned(user_id, _to_summary(row))
    tokens_repo.delete_token(token_id)
    token_ws.delete_token_tree(token_id)


def relink_board(
    user_id: str, token_id: str, linked_board_id: str | None
) -> TokenSummary:
    """Change (or clear) the source board for this token.

    Only allowed while the design is unlocked, since the palette would
    otherwise diverge from the frozen ``design_lock.json``.
    """
    row = _load_token_or_raise(token_id)
    assert_token_owned(user_id, _to_summary(row))
    if row.design_locked:
        raise DesignGateError(
            "Cannot change the linked board after the design is locked. "
            "Unlock the design first."
        )
    if linked_board_id:
        assert_board_owned(user_id, linked_board_id)
    tokens_repo.set_linked_board(token_id, linked_board_id)
    return get_token(token_id)


# ── design lock ───────────────────────────────────────────────────────────────

def commit_canonical(
    *,
    user_id: str,
    token_id: str,
    candidate_index: int,
    style_sentence: str,
    board_palette_colors: list[tuple[int, int, int]],
) -> TokenSummary:
    """Promote a candidate image to canonical and write design_lock.json.

    Computes the token palette from ``board_palette_colors`` using OKLch math.
    The caller (route handler) sources palette colors from the token's
    ``linked_board_id`` when set, or passes an empty list for unlinked tokens
    (which then yields the neutral fallback palette).
    """
    row = _load_token_or_raise(token_id)
    assert_token_owned(user_id, _to_summary(row))

    _promote_candidate_to_canonical(row, candidate_index)

    token_palette = compute_token_palette(board_palette_colors)
    lock_data = _build_design_lock(row, style_sentence, token_palette)
    token_ws.write_design_lock(row.id, lock_data)

    tokens_repo.set_design_locked(token_id, True)
    return get_token(token_id)


def unlock_design(user_id: str, token_id: str) -> TokenSummary:
    """Clear the design lock so the user can re-explore candidates."""
    row = _load_token_or_raise(token_id)
    assert_token_owned(user_id, _to_summary(row))
    tokens_repo.set_design_locked(token_id, False)
    return get_token(token_id)


# ── publish ───────────────────────────────────────────────────────────────────

def publish_run(user_id: str, token_id: str, run_id: str) -> TokenSummary:
    """Record that ``run_id`` is now live for this token."""
    row = _load_token_or_raise(token_id)
    assert_token_owned(user_id, _to_summary(row))
    assert_design_locked(row)
    tokens_repo.set_live_run_id(token_id, run_id)
    return get_token(token_id)


# ── cost estimates ────────────────────────────────────────────────────────────

def estimate_explore_cost_usd() -> float:
    from tokenfactory.config import DESIGN_EXPLORE_COST_USD
    return DESIGN_EXPLORE_COST_USD


def estimate_clip_cost_usd() -> float:
    from tokenfactory.config import GENERATE_CLIP_COST_USD
    return GENERATE_CLIP_COST_USD


# ── payload builder ───────────────────────────────────────────────────────────

def _token_asset_url(token_asset_base: str, rel: str) -> str:
    """Map a per-token-root relative path (forward slashes) to a URL.

    Files are served by ``GET …/asset/{rest}`` under the token's URL prefix
    (see ``routes_api.token_asset``).
    """
    rest = rel.strip().lstrip("/")
    base = token_asset_base.rstrip("/")
    return f"{base}/asset/{rest}"


def _token_disk_frame_index(path: Path) -> int:
    stem = path.stem
    if stem.startswith("frame_"):
        try:
            return int(stem[len("frame_"):])
        except ValueError:
            pass
    return 0


def _clip_frame_thumbnails(
    token_id: str,
    clip_name: str,
    *,
    token_asset_base: str,
) -> list[dict]:
    """On-disk frames from ``generate_clip`` → asset URLs for the filmstrip."""
    d = token_ws.clip_frames_dir(token_id, clip_name)
    if not d.is_dir():
        return []
    paths = sorted(
        (p for p in d.glob("frame_*.png") if p.is_file()),
        key=_token_disk_frame_index,
    )
    out: list[dict] = []
    for p in paths:
        idx = _token_disk_frame_index(p)
        rel = token_ws.clip_frame_rel(clip_name, f"frame_{idx}.png")
        out.append({"index": idx, "url": _token_asset_url(token_asset_base, rel)})
    return out


def _clip_frames_payload(
    token_id: str,
    locomotion_profile: str,
    *,
    token_asset_base: str,
) -> dict[str, list[dict]]:
    """Map clip name → ordered frame thumbnails (empty until generated)."""
    return {
        cn: _clip_frame_thumbnails(token_id, cn, token_asset_base=token_asset_base)
        for cn in _planned_clip_names(locomotion_profile)
    }


def pick_preview_clip(
    token_id: str,
    locomotion_profile: str,
    *,
    token_asset_base: str,
    design_lock: dict | None = None,
) -> dict | None:
    """First clip that has on-disk frames — for list-card looping previews."""
    if design_lock and design_lock.get("clips"):
        clip_names = list(design_lock["clips"])
    else:
        clip_names = _planned_clip_names(locomotion_profile)
    for clip_name in clip_names:
        frames = _clip_frame_thumbnails(
            token_id, clip_name, token_asset_base=token_asset_base
        )
        if frames:
            return {"clip_name": clip_name, "frames": frames}
    return None


def build_token_factory_payload(
    user_id: str,
    *,
    token_asset_base_for: callable,
) -> dict:
    """Return the full payload for the Token Factory studio page.

    ``token_asset_base_for(token_summary) -> str`` is supplied by the caller
    (route handler) to keep this module ignorant of URL shapes — it should
    return ``/users/<username>/token-factory/<path_slug>`` for each token.
    """
    tokens = list_tokens(user_id)
    items = []
    for t in tokens:
        token_asset_base = token_asset_base_for(t)
        items.append(_build_one_token_item(t, token_asset_base))
    return {"tokens": items}


def build_token_detail_payload(
    token_id: str,
    *,
    token_asset_base: str,
) -> dict:
    """Return the payload for a single-token detail view (JSON API)."""
    t = get_token(token_id)
    return _build_one_token_item(t, token_asset_base)


def _build_one_token_item(t: TokenSummary, token_asset_base: str) -> dict:
    lock = token_ws.read_design_lock(t.id)
    live_manifest = token_ws.read_live_manifest(t.id)
    canonical_exists = token_ws.canonical_png_path(t.id).exists()
    atlas_exists = token_ws.live_atlas_path(t.id).exists()
    return {
        "token": _summary_to_dict(t),
        "design_lock": lock,
        "has_canonical": canonical_exists,
        "canonical_url": (
            _token_asset_url(token_asset_base, token_ws.canonical_rel())
            if canonical_exists
            else None
        ),
        "candidates": _list_candidates(t.id, token_asset_base=token_asset_base),
        "planned_clips": _planned_clip_names(t.locomotion_profile),
        "clip_frames": _clip_frames_payload(
            t.id, t.locomotion_profile, token_asset_base=token_asset_base
        ),
        "live_atlas_url": (
            _token_asset_url(token_asset_base, token_ws.live_atlas_rel())
            if atlas_exists
            else None
        ),
        "manifest": live_manifest,
        "token_base": token_asset_base,
    }


# ── private helpers ───────────────────────────────────────────────────────────

def _load_token_or_raise(token_id: str) -> TokenRecord:
    row = tokens_repo.get_token(token_id)
    if row is None:
        raise TokenNotFound(token_id)
    return row


def _default_explore_style_sentence(row: TokenRecord) -> str:
    label = (row.display_name or "").strip()
    if not label:
        label = row.slug.replace("-", " ").strip()
    return f"Pixel art character token: {label}"


def _validate_create_inputs(
    slug: str,
    locomotion_profile: str,
    facing_policy: str,
) -> None:
    if not _slug_valid(slug):
        raise ValueError(
            f"Token slug {slug!r} must match ^[a-z0-9][a-z0-9-]{{0,62}}$."
        )
    allowed_locomotion = ("walk", "float", "fly")
    if locomotion_profile not in allowed_locomotion:
        raise ValueError(
            f"locomotion_profile must be one of {allowed_locomotion!r}, "
            f"got {locomotion_profile!r}."
        )
    allowed_facing = ("flip_x", "four_way")
    if facing_policy not in allowed_facing:
        raise ValueError(
            f"facing_policy must be one of {allowed_facing!r}, "
            f"got {facing_policy!r}."
        )


def _assert_path_slug_free(owner_user_id: str, path_slug: str) -> None:
    existing = tokens_repo.get_token_by_path(owner_user_id, path_slug)
    if existing is not None:
        raise TokenExists(
            f"A token with slug {path_slug!r} already exists for this user."
        )


def _slug_from_display_name(display_name: str) -> str:
    """Lowercase slug: spaces/underscores → hyphens; strip invalid characters."""
    s = (display_name or "").strip().lower()
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"[^a-z0-9-]+", "", s)
    s = re.sub(r"-+", "-", s).strip("-")
    if len(s) > 63:
        s = s[:63].rstrip("-")
    if not s:
        raise ValueError(
            "Could not derive a URL-safe slug from display_name; "
            "use letters or numbers."
        )
    if not _slug_valid(s):
        raise ValueError(
            f"Derived slug {s!r} is invalid; try a different display name."
        )
    return s


def _allocate_unique_path_slug(owner_user_id: str, display_name: str) -> str:
    """Pick a free path_slug, suffixing ``-2``, ``-3``, … on collision."""
    base = _slug_from_display_name(display_name)
    candidate = base
    counter = 2
    while tokens_repo.get_token_by_path(owner_user_id, candidate) is not None:
        extra = f"-{counter}"
        counter += 1
        prefix_len = 63 - len(extra)
        if prefix_len < 1:
            raise ValueError(
                "Could not allocate a unique token slug; try a shorter display name."
            )
        trimmed = base[:prefix_len].rstrip("-")
        if not trimmed:
            trimmed = "token"
        candidate = trimmed + extra
        if counter > 1000:
            raise ValueError(
                "Could not allocate a unique token slug; try a different display name."
            )
    return candidate


def _promote_candidate_to_canonical(row: TokenRecord, candidate_index: int) -> None:
    import shutil

    candidate = token_ws.candidate_path(row.id, candidate_index)
    if not candidate.exists():
        raise DesignGateError(
            f"Candidate {candidate_index} does not exist for token {row.slug!r}. "
            "Generate design candidates first (use Regenerate candidates if needed)."
        )
    canonical = token_ws.canonical_png_path(row.id)
    canonical.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(candidate, canonical)


def _build_design_lock(
    row: TokenRecord,
    style_sentence: str,
    token_palette: TokenPalette,
) -> dict:
    from tokenfactory.config import CLIPS_BY_LOCOMOTION

    clips_for_profile = CLIPS_BY_LOCOMOTION.get(row.locomotion_profile, [])
    clip_names = [clip_name for clip_name, _, _ in clips_for_profile]

    return {
        "slug": row.slug,
        "display_name": row.display_name,
        "locomotion_profile": row.locomotion_profile,
        "facing_policy": row.facing_policy,
        "canvas_w": row.canvas_w,
        "canvas_h": row.canvas_h,
        "pivot_x": row.canvas_w // 2,
        "pivot_y": int(row.canvas_h * 0.9375),  # 15/16 down → feet at bottom
        "frame_fps": row.frame_fps,
        "clips": clip_names,
        "token_palette": palette_to_dict(token_palette),
        "style_sentence": style_sentence,
    }


def _planned_clip_names(locomotion_profile: str) -> list[str]:
    from tokenfactory.config import CLIPS_BY_LOCOMOTION

    defs = CLIPS_BY_LOCOMOTION.get(locomotion_profile, [])
    return [clip_name for clip_name, _, _ in defs]


def _list_candidates(token_id: str, *, token_asset_base: str) -> list[dict]:
    cdir = token_ws.candidates_dir(token_id)
    paths = sorted(cdir.glob("candidate_*.png"))
    return [
        {
            "index": i,
            "url": _token_asset_url(token_asset_base, token_ws.candidate_rel(i)),
        }
        for i, p in enumerate(paths)
        if p.exists()
    ]


def _summary_to_dict(t: TokenSummary) -> dict:
    return {
        "id": t.id,
        "owner_user_id": t.owner_user_id,
        "linked_board_id": t.linked_board_id,
        "path_slug": t.path_slug,
        "slug": t.slug,
        "display_name": t.display_name,
        "locomotion_profile": t.locomotion_profile,
        "facing_policy": t.facing_policy,
        "canvas_w": t.canvas_w,
        "canvas_h": t.canvas_h,
        "frame_fps": t.frame_fps,
        "design_locked": t.design_locked,
        "live_run_id": t.live_run_id,
        "created_ms": t.created_ms,
        "updated_ms": t.updated_ms,
    }
