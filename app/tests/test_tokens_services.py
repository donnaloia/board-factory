"""Tests for the tokens domain service layer.

Covers: create, delete, gate assertions, design lock / unlock, relink board,
and the optional-board explore palette fallback.
OKLch palette math is covered separately in the pipeline tests.
"""

from __future__ import annotations

import pytest

import domains.tokens.services as svc_tokens
import domains.tokens.repository as tokens_repo
from domains.tokens.workspace import (
    token_root,
    candidates_dir,
    canonical_png_path,
    read_design_lock,
    write_design_lock,
)


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def user_and_board(seeded_board):
    from infrastructure.db import session_scope
    from domains.boards.models import OwnedBoardRecord

    with session_scope() as session:
        ob = session.get(OwnedBoardRecord, seeded_board.id)
    return ob.user_id, seeded_board.id


@pytest.fixture
def token(user_and_board):
    user_id, board_id = user_and_board
    return svc_tokens.create_token(
        user_id=user_id,
        linked_board_id=board_id,
        display_name="Test Pawn",
        slug="test-pawn",
        locomotion_profile="walk",
    )


@pytest.fixture
def unlinked_token(user_and_board):
    user_id, _ = user_and_board
    return svc_tokens.create_token(
        user_id=user_id,
        linked_board_id=None,
        display_name="Free Pawn",
        slug="free-pawn",
        locomotion_profile="walk",
    )


# ── create / list / delete ────────────────────────────────────────────────────


def test_create_token_makes_workspace(token):
    root = token_root(token.id)
    assert root.exists()


def test_create_token_appears_in_list(token, user_and_board):
    user_id, _ = user_and_board
    tokens = svc_tokens.list_tokens(user_id)
    assert any(t.id == token.id for t in tokens)


def test_create_token_rejects_duplicate_slug(user_and_board):
    user_id, board_id = user_and_board
    svc_tokens.create_token(
        user_id=user_id,
        linked_board_id=board_id,
        slug="dupe-pawn",
        display_name="A",
    )
    with pytest.raises(svc_tokens.TokenExists):
        svc_tokens.create_token(
            user_id=user_id,
            linked_board_id=board_id,
            slug="dupe-pawn",
            display_name="B",
        )


def test_create_token_rejects_invalid_slug(user_and_board):
    user_id, board_id = user_and_board
    with pytest.raises(ValueError, match="slug"):
        svc_tokens.create_token(
            user_id=user_id,
            linked_board_id=board_id,
            slug="INVALID SLUG!",
            display_name="X",
        )


def test_create_token_derives_slug_from_display_name(user_and_board):
    user_id, board_id = user_and_board
    t = svc_tokens.create_token(
        user_id=user_id,
        linked_board_id=board_id,
        display_name="Sugar Plum Fairy",
        locomotion_profile="walk",
    )
    assert t.slug == "sugar-plum-fairy"
    assert t.path_slug == "sugar-plum-fairy"


def test_create_token_derived_slug_collision_suffix(user_and_board):
    user_id, board_id = user_and_board
    a = svc_tokens.create_token(
        user_id=user_id,
        linked_board_id=board_id,
        display_name="Hello World",
        locomotion_profile="walk",
    )
    b = svc_tokens.create_token(
        user_id=user_id,
        linked_board_id=board_id,
        display_name="Hello World",
        locomotion_profile="walk",
    )
    assert a.path_slug == "hello-world"
    assert b.path_slug == "hello-world-2"


def test_create_token_requires_display_when_slug_omitted(user_and_board):
    user_id, _ = user_and_board
    with pytest.raises(ValueError, match="display_name"):
        svc_tokens.create_token(
            user_id=user_id,
            display_name="",
            slug=None,
            locomotion_profile="walk",
        )


def test_create_unlinked_token_succeeds(unlinked_token):
    assert unlinked_token.linked_board_id is None
    assert token_root(unlinked_token.id).exists()


def test_delete_token_removes_row(token, user_and_board):
    user_id, _ = user_and_board
    svc_tokens.delete_token(user_id, token.id)
    assert tokens_repo.get_token(token.id) is None


def test_delete_token_clears_filesystem(token, user_and_board):
    user_id, _ = user_and_board
    svc_tokens.delete_token(user_id, token.id)
    assert not token_root(token.id).exists()


def test_get_token_raises_for_unknown_id():
    with pytest.raises(svc_tokens.TokenNotFound):
        svc_tokens.get_token("00000000-0000-0000-0000-000000000000")


# ── design gate ───────────────────────────────────────────────────────────────


def test_design_locked_defaults_false(token):
    assert token.design_locked is False


def test_assert_design_locked_raises_when_unlocked(token):
    with pytest.raises(svc_tokens.DesignGateError):
        svc_tokens.assert_design_locked(token)


def test_resolve_design_explore_without_lock(token):
    row = tokens_repo.get_token(token.id)
    assert row is not None
    style, pal = svc_tokens.resolve_design_explore_inputs(row)
    assert style == "Pixel art character token: Test Pawn"
    assert "body_neutral" in pal and isinstance(pal["body_neutral"], list)


def test_resolve_design_explore_for_unlinked_token_uses_neutral_palette(unlinked_token):
    """Unlinked tokens have no board to seed from; the fallback palette is used."""
    row = tokens_repo.get_token(unlinked_token.id)
    assert row is not None
    style, pal = svc_tokens.resolve_design_explore_inputs(row)
    assert style == "Pixel art character token: Free Pawn"
    # _fallback_palette() in domains.tokens.palette is non-empty
    assert pal["body_neutral"]
    assert pal["accent_primary"]
    assert pal["highlight_neutral"]


def test_resolve_design_explore_prefers_lock_file(token):
    write_design_lock(
        token.id,
        {
            "style_sentence": "Custom locked style",
            "token_palette": {
                "body_neutral": ["#010203"],
                "accent_primary": ["#abcdef"],
                "highlight_neutral": ["#ffffff"],
            },
        },
    )
    row = tokens_repo.get_token(token.id)
    assert row is not None
    style, pal = svc_tokens.resolve_design_explore_inputs(row)
    assert style == "Custom locked style"
    assert pal["body_neutral"] == ["#010203"]


def test_commit_canonical_raises_without_candidate(token, user_and_board):
    user_id, _ = user_and_board
    with pytest.raises(svc_tokens.DesignGateError, match="Candidate"):
        svc_tokens.commit_canonical(
            user_id=user_id,
            token_id=token.id,
            candidate_index=0,
            style_sentence="Pixel art knight",
            board_palette_colors=[(200, 170, 120), (100, 80, 50)],
        )


def test_commit_canonical_locks_design(token, user_and_board):
    user_id, _ = user_and_board
    from PIL import Image

    cdir = candidates_dir(token.id)
    Image.new("RGBA", (96, 128), (180, 140, 100, 255)).save(
        str(cdir / "candidate_0.png")
    )

    updated = svc_tokens.commit_canonical(
        user_id=user_id,
        token_id=token.id,
        candidate_index=0,
        style_sentence="Pixel art knight, gold armour",
        board_palette_colors=[(200, 170, 120), (100, 80, 50), (240, 235, 220)],
    )
    assert updated.design_locked is True
    assert canonical_png_path(token.id).exists()

    lock = read_design_lock(token.id)
    assert lock is not None
    assert lock["style_sentence"] == "Pixel art knight, gold armour"
    assert "token_palette" in lock
    assert "body_neutral" in lock["token_palette"]


def test_unlock_design_clears_lock(token, user_and_board):
    user_id, _ = user_and_board
    from PIL import Image

    cdir = candidates_dir(token.id)
    Image.new("RGBA", (96, 128), (180, 140, 100, 255)).save(
        str(cdir / "candidate_0.png")
    )
    svc_tokens.commit_canonical(
        user_id=user_id,
        token_id=token.id,
        candidate_index=0,
        style_sentence="style",
        board_palette_colors=[(100, 100, 100)],
    )
    unlocked = svc_tokens.unlock_design(user_id, token.id)
    assert unlocked.design_locked is False


# ── relink board ──────────────────────────────────────────────────────────────


def test_relink_board_succeeds_when_unlocked(unlinked_token, user_and_board):
    user_id, board_id = user_and_board
    updated = svc_tokens.relink_board(user_id, unlinked_token.id, board_id)
    assert updated.linked_board_id == board_id


def test_relink_board_clears_when_passed_none(token, user_and_board):
    user_id, _ = user_and_board
    updated = svc_tokens.relink_board(user_id, token.id, None)
    assert updated.linked_board_id is None


def test_relink_board_blocked_when_locked(token, user_and_board):
    user_id, _ = user_and_board
    from PIL import Image

    cdir = candidates_dir(token.id)
    Image.new("RGBA", (96, 128), (180, 140, 100, 255)).save(
        str(cdir / "candidate_0.png")
    )
    svc_tokens.commit_canonical(
        user_id=user_id,
        token_id=token.id,
        candidate_index=0,
        style_sentence="style",
        board_palette_colors=[(100, 100, 100)],
    )
    with pytest.raises(svc_tokens.DesignGateError, match="design is locked"):
        svc_tokens.relink_board(user_id, token.id, None)


def test_relink_board_rejects_non_owner(token):
    with pytest.raises(svc_tokens.TokenAuthError):
        svc_tokens.relink_board("other-user-id", token.id, None)


# ── owner auth gate ───────────────────────────────────────────────────────────


def test_create_token_rejects_unowned_board(user_and_board):
    """When the caller passes a ``linked_board_id`` they don't own, the
    create-flow raises ``BoardAuthError`` (the legacy CASCADE auth check now
    only fires for the optional link, not for every create)."""
    _, board_id = user_and_board
    with pytest.raises(svc_tokens.BoardAuthError):
        svc_tokens.create_token(
            user_id="other-user-id",
            linked_board_id=board_id,
            slug="should-fail",
            display_name="X",
        )


def test_create_unlinked_token_skips_board_auth_check(test_user):
    """No board passed → no board-ownership check, just the FK to users."""
    t = svc_tokens.create_token(
        user_id=test_user.id,
        display_name="Standalone",
        slug="standalone",
    )
    assert t.linked_board_id is None
    assert t.owner_user_id == test_user.id


def test_delete_token_rejects_non_owner(token):
    with pytest.raises(svc_tokens.TokenAuthError):
        svc_tokens.delete_token("other-user-id", token.id)
