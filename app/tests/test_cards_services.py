"""Tests for the cards domain service layer.

Verifies: create/link/delete, gate assertions, frame commit.
"""

from __future__ import annotations

import pytest

import domains.cards.services as svc_cards
import domains.cards.repository as cards_repo
from domains.cards.workspace import deck_root


# ────────────────────────── fixtures ──────────────────────────


@pytest.fixture
def user_and_board(seeded_board):
    """Return (user_id, board_id) for a board that already exists."""
    from infrastructure.db import session_scope
    from domains.boards.models import OwnedBoardRecord

    with session_scope() as session:
        ob = session.get(OwnedBoardRecord, seeded_board.id)
    return ob.user_id, seeded_board.id


@pytest.fixture
def deck(user_and_board):
    user_id, _ = user_and_board
    return svc_cards.create_deck(user_id, "test-deck", "Test Deck")


# ────────────────────────── create / list / delete ──────────────────────────


def test_create_deck_creates_workspace_and_slots(deck, user_and_board):
    user_id, _ = user_and_board
    assert deck.path_slug == "test-deck"
    assert deck.status == "draft"
    root = deck_root(deck.id)
    assert root.exists()
    slots = cards_repo.list_slots(deck.id)
    assert len(slots) == 6


def test_create_deck_rejects_duplicate_slug(user_and_board):
    user_id, _ = user_and_board
    svc_cards.create_deck(user_id, "unique-slug", "First")
    with pytest.raises(svc_cards.DeckExists):
        svc_cards.create_deck(user_id, "unique-slug", "Second")


def test_create_deck_rejects_invalid_slug(user_and_board):
    user_id, _ = user_and_board
    with pytest.raises(svc_cards.InvalidDeckId):
        svc_cards.create_deck(user_id, "UPPERCASE", "Bad")


def test_list_decks(deck, user_and_board):
    user_id, _ = user_and_board
    decks = svc_cards.list_decks(user_id)
    assert any(d.id == deck.id for d in decks)


def test_delete_deck_removes_workspace(deck, user_and_board):
    user_id, _ = user_and_board
    root = deck_root(deck.id)
    assert root.exists()
    svc_cards.delete_deck(user_id, deck.id)
    assert not root.exists()
    assert cards_repo.get_deck(deck.id) is None


# ────────────────────────── board linking ──────────────────────────


def test_link_board_copies_style(deck, user_and_board):
    user_id, board_id = user_and_board
    # Seed style_prompt on the board row
    import domains.boards.repository as boards_repo
    boards_repo.set_style_prompt(board_id, "pixel art fantasy")

    svc_cards.link_board(user_id, deck.id, board_id)
    row = cards_repo.get_deck(deck.id)
    assert row.linked_board_id == board_id
    assert row.style_prompt == "pixel art fantasy"
    assert row.status == "frame_pending"


def test_link_board_rejects_foreign_deck(deck, user_and_board):
    """Wrong user must not link into someone else's deck (treated as missing deck)."""
    _, board_id = user_and_board
    with pytest.raises(svc_cards.DeckNotFound):
        svc_cards.link_board("other-user", deck.id, board_id)


# ────────────────────────── gate assertions ──────────────────────────


def test_assert_board_linked_raises_when_missing(deck):
    row = cards_repo.get_deck(deck.id)
    with pytest.raises(svc_cards.FrameGateError):
        svc_cards.assert_board_linked(row)


def test_assert_frame_committed_raises_when_missing(deck):
    row = cards_repo.get_deck(deck.id)
    with pytest.raises(svc_cards.FrameGateError):
        svc_cards.assert_frame_committed(row)


# ────────────────────────── frame commit ──────────────────────────


def test_commit_frame_sets_committed_frame_id(deck, user_and_board, isolated_repo):
    user_id, board_id = user_and_board

    # Fake a candidate PNG on disk
    from domains.cards.workspace import frame_candidates_dir, deck_root
    from PIL import Image

    fake_job_id = "testjob"
    out_dir = frame_candidates_dir(deck.id, fake_job_id)
    img = Image.new("RGBA", (720, 1008), (128, 0, 0, 255))
    img.save(str(out_dir / "candidate_0.png"))

    candidate = cards_repo.insert_frame_candidate(
        deck_id=deck.id,
        job_id=fake_job_id,
        candidate_index=0,
        rel_path=f"frames/candidates/job_{fake_job_id}/candidate_0.png",
        inner_rect={"x": 72, "y": 101, "w": 576, "h": 806},
        m_chrome_paint_hash="abc123",
        provider="mock",
        model_id="mock",
    )

    svc_cards.commit_frame(user_id, deck.id, candidate.id)

    updated = cards_repo.get_deck(deck.id)
    assert updated.committed_frame_id == candidate.id
    assert updated.status == "card_pending"

    # Committed frame file should exist on disk
    from domains.cards.workspace import committed_frame_path
    assert committed_frame_path(deck.id).exists()


def test_live_preview_urls_follow_slot_order(deck, user_and_board):
    from domains.cards.workspace import card_live_rel

    cards_repo.set_slot_live(
        deck.id,
        2,
        live_rel_path=card_live_rel(2),
        live_frame_commit_id=None,
    )
    cards_repo.set_slot_live(
        deck.id,
        0,
        live_rel_path=card_live_rel(0),
        live_frame_commit_id=None,
    )
    urls = svc_cards.live_preview_urls_for_deck_index(
        deck.id,
        "/users/u/card-factory/ab",
        max_urls=6,
    )
    assert len(urls) == 2
    assert urls[0].endswith("/api/cards/0/live")
    assert urls[1].endswith("/api/cards/2/live")


def test_rename_deck_title(deck, user_and_board):
    user_id, _ = user_and_board
    assert svc_cards.rename_deck(user_id, deck.id, "  My Deck  ") == "My Deck"
    row = cards_repo.get_deck(deck.id)
    assert row.project_name == "My Deck"


def test_rename_deck_rejects_empty(deck, user_and_board):
    user_id, _ = user_and_board
    with pytest.raises(ValueError, match="empty"):
        svc_cards.rename_deck(user_id, deck.id, "   ")
