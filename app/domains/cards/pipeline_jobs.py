"""Card Factory pipeline job workers (``domains.cards``).

Same shape as other ``domains/*/pipeline_jobs.py`` modules:

    fn(job: Job, cancel: threading.Event, **kwargs) -> float | None

Each worker validates inputs, drives a pipeline op via a ``JobProgressSink``,
and writes results back through repository functions.

Pipeline imports are deferred inside each worker so web boot stays cheap.
"""

from __future__ import annotations

import json
import threading

from jobs import cost_ledger
from jobs.runner import Job, JobProgressSink, get_runner


# ── cost estimates exposed to the UI without importing the pipeline ──
DERIVE_PROMPTS_COST_USD: float = 0.03   # one GPT-4o call over catalog text
GENERATE_FRAMES_COST_USD: float = 0.15  # 3 × gpt-image-2 inpaint calls
GENERATE_CARDS_COST_USD_PER_SLOT: float = 0.08  # 1 × illustration inpaint per slot
# Rough gpt-image-2 low-quality whole-card edit (unify pass); verify vs pricing.
FINAL_UNIFY_COST_USD: float = 0.011


# ────────────────────────── derive-prompts ──────────────────────────


def derive_prompts_job(
    job: Job,
    cancel: threading.Event,
    *,
    deck_id: str,
    board_id: str | None,
    openai_key: str,
) -> float | None:
    """Call GPT-4o to fill per-slot prompts from the linked board context."""
    from cardfactory.ops.derive_prompts import derive_slot_prompts
    import domains.cards.repository as cards_repo

    deck = cards_repo.get_deck(deck_id)
    if deck is None:
        raise RuntimeError(f"Deck {deck_id!r} not found")

    # Load board catalog if linked
    catalog: dict | None = None
    if board_id:
        try:
            from domains.boards import services as svc_boards
            catalog = svc_boards.load_catalog_dict(board_id)
        except Exception:
            catalog = None

    sink = JobProgressSink(job, get_runner())

    payloads = derive_slot_prompts(
        slot_count=deck.slot_count,
        style_prompt=deck.style_prompt or "",
        palette_json=deck.palette_json,
        catalog=catalog,
        openai_key=openai_key,
        sink=sink,
    )

    cards_repo.bulk_update_slot_prompts(deck_id, payloads)

    cost = DERIVE_PROMPTS_COST_USD
    cost_ledger.record(
        operation="card_derive_prompts",
        target=deck_id,
        units=1,
        usd=cost,
    )
    return cost


# ────────────────────────── generate-frames ──────────────────────────


def generate_frames_job(
    job: Job,
    cancel: threading.Event,
    *,
    deck_id: str,
    openai_key: str,
) -> float | None:
    """Generate 3 chrome candidates and write frame candidate rows."""
    from cardfactory.config import provider_name
    from cardfactory.providers.factory import select_provider
    from cardfactory.ops.generate_frames import generate_frames
    from domains.cards.canvas import default_canvas_size
    import domains.cards.repository as cards_repo
    import domains.cards.workspace as deck_ws

    deck = cards_repo.get_deck(deck_id)
    if deck is None:
        raise RuntimeError(f"Deck {deck_id!r} not found")

    provider = select_provider(provider_name(), openai_key=openai_key or None)

    palette_colors: list[tuple[int, int, int]] = []
    if deck.palette_json:
        try:
            palette_colors = [tuple(c) for c in json.loads(deck.palette_json)]
        except Exception:
            pass

    canvas = default_canvas_size()
    output_dir = deck_ws.frame_candidates_dir(deck_id, job.id)

    sink = JobProgressSink(job, get_runner())

    candidates = generate_frames(
        deck_id=deck_id,
        job_id=job.id,
        canvas=canvas,
        style_prompt=deck.style_prompt or "",
        palette_colors=palette_colors,
        provider=provider,
        output_dir=output_dir,
        sink=sink,
    )

    for c in candidates:
        cards_repo.insert_frame_candidate(
            deck_id=deck_id,
            job_id=job.id,
            candidate_index=c["candidate_index"],
            rel_path=c["rel_path"],
            inner_rect=c["inner_rect"],
            m_chrome_paint_hash=c.get("m_chrome_paint_hash"),
            provider=c["provider"],
            model_id=c["model_id"],
        )

    cost = GENERATE_FRAMES_COST_USD
    cost_ledger.record(
        operation="card_generate_frames",
        target=deck_id,
        units=len(candidates),
        usd=cost,
    )
    return cost


# ────────────────────────── generate-cards ──────────────────────────


def generate_cards_job(
    job: Job,
    cancel: threading.Event,
    *,
    deck_id: str,
    slot_indices: list[int],
    openai_key: str,
) -> float | None:
    """Assemble full card PNGs for the requested slots."""
    import tempfile
    from pathlib import Path

    from cardfactory.config import final_unify_enabled, provider_name, single_pass_card_enabled
    from cardfactory.providers.factory import select_provider
    from cardfactory.ops.generate_cards import generate_one_card
    from domains.cards.canvas import default_canvas_size
    import domains.cards.repository as cards_repo
    import domains.cards.workspace as deck_ws

    deck = cards_repo.get_deck(deck_id)
    if deck is None:
        raise RuntimeError(f"Deck {deck_id!r} not found")
    if deck.committed_frame_id is None:
        raise RuntimeError(f"Deck {deck_id!r} has no committed frame — run frame gate first.")

    frame_row = cards_repo.get_frame_candidate(deck.committed_frame_id)
    if frame_row is None:
        raise RuntimeError(f"Committed frame candidate {deck.committed_frame_id} missing from DB.")

    provider = select_provider(provider_name(), openai_key=openai_key or None)

    palette_colors: list[tuple[int, int, int]] = []
    if deck.palette_json:
        try:
            palette_colors = [tuple(c) for c in json.loads(deck.palette_json)]
        except Exception:
            pass

    canvas = default_canvas_size()
    committed_frame_png = deck_ws.committed_frame_path(deck_id)
    inner_rect = dict(frame_row.inner_rect_json)

    realized_cost = 0.0
    units = 0

    for slot_index in slot_indices:
        if cancel.is_set():
            break

        slot = cards_repo.get_slot(deck_id, slot_index)
        if slot is None:
            continue

        stat_lines = list(slot.stat_lines_json or [])
        illustration_prompt = slot.illustration_prompt or f"Card {slot_index + 1} illustration."

        sink = JobProgressSink(job, get_runner())

        # Cards have no on-disk history (one slot = one row + one live PNG).
        # The pipeline still requires a ``history_dir`` argument, so we hand
        # it a system tempdir that disappears with the context. No bytes
        # leak into the deck workspace.
        with tempfile.TemporaryDirectory(prefix="card_history_discard_") as tmp:
            out_path = generate_one_card(
                deck_id=deck_id,
                slot_index=slot_index,
                frame_commit_id=deck.committed_frame_id,
                committed_frame_png=committed_frame_png,
                committed_inner_rect=inner_rect,
                canvas=canvas,
                illustration_prompt=illustration_prompt,
                stat_lines=stat_lines,
                palette_colors=palette_colors,
                provider=provider,
                output_path=deck_ws.card_live_path(deck_id, slot_index),
                masks_dir=deck_ws.card_masks_dir(deck_id, slot_index),
                history_dir=Path(tmp),
                sink=sink,
            )

        rel = deck_ws.card_live_rel(slot_index)
        cards_repo.set_slot_live(
            deck_id,
            slot_index,
            live_rel_path=rel,
            live_frame_commit_id=deck.committed_frame_id,
        )
        realized_cost += GENERATE_CARDS_COST_USD_PER_SLOT
        units += 1
        if (
            final_unify_enabled()
            and not single_pass_card_enabled()
            and provider_name() == "openai"
            and FINAL_UNIFY_COST_USD > 0
        ):
            cost_ledger.record(
                operation="card_unify",
                target=deck_id,
                units=1,
                usd=FINAL_UNIFY_COST_USD,
            )
            realized_cost += FINAL_UNIFY_COST_USD

    # Mark deck complete when all slots are done
    all_slots = cards_repo.list_slots(deck_id)
    if all(s.live_rel_path for s in all_slots):
        cards_repo.set_deck_status(deck_id, "complete")

    cost_ledger.record(
        operation="card_generate_cards",
        target=deck_id,
        units=units,
        usd=realized_cost,
    )
    return realized_cost
