"""Card Factory pipeline configuration.

All runtime knobs are read from environment variables so that the app
layer can override them per-request without coupling to the pipeline's
import-time state.
"""

from __future__ import annotations

import os


def provider_name() -> str:
    """Name of the image provider to use.

    ``CARD_FACTORY_PROVIDER`` overrides; default is ``openai``.
    Tests override this to ``mock`` via ``conftest.py``.
    """
    return os.environ.get("CARD_FACTORY_PROVIDER", "openai").strip().lower()


# ────────────────────────── canvas geometry ──────────────────────────

#: Default frame margin fraction (each side). 10% gives a 80%×80% interior.
DEFAULT_FRAME_MARGIN: float = 0.10

#: Number of chrome candidates generated per frame-gate job.
FRAME_CANDIDATE_COUNT: int = 3

#: Default full-cards-per-deck.
DEFAULT_SLOT_COUNT: int = 6

#: Prompt discipline — align with boardfactory pixel language (flat fills, no photo).
PIXEL_DISCIPLINE_CHROME: str = (
    "Pixel art only: crisp hard pixel edges, flat color fills, minimal ramping, "
    "no photorealism, no smooth airbrush, no 3D-render lighting, no photograph. "
    "Retro 16-bit collectible-card frame aesthetic. "
)

#: Prepended to every chrome / frame candidate prompt (after pixel discipline, before palette + user style).
#: Makes the outer border *segmentably* distinct from the interior and keeps holes truly transparent for alpha+CC masks.
CHROME_INTERIOR_VALUE_AND_ALPHA_LEAD: str = (
    "VALUE SEPARATION (critical): The outer frame, rim, and stats plaque chrome must read **noticeably darker "
    "and more desaturated** than the **interior** where art will go. The illustration window and stats glyph "
    "regions are **fully empty** — reserve **brighter, more saturated** colours **only** for painted chrome "
    "and ornaments *outside* those holes. Even within a tight palette, maintain **clear value/luminance contrast** "
    "between border chrome and the transparent interior so the inner edge is unambiguous.\n\n"
    "ALPHA / CUTOUT DISCIPLINE: The illustration aperture and procedural-stats glyph plate must be **perfectly "
    "transparent** (RGBA alpha 0) — no fog, smoke, haze, gradient fill, or low-opacity colour wash inside those "
    "forbidden zones. Decorative inner bezel or mat **may** sit in the allowed chrome ring (outside the inset "
    "holes); do not leak opaque pixels into the cutout.\n\n"
)

PIXEL_DISCIPLINE_ILLUSTRATION: str = (
    "Subject must be pixel art matching the board: hard edges, flat fills, "
    "limited shading bands, indexed-colour look — absolutely no photorealism, "
    "no photo textures, no glossy 3D, no soft gradients. Single cohesive style. "
    "Do not outline the composition with a rectangular border or ‘card within a card’ frame line. "
)

#: Stats plate alpha when sampling from the committed frame (0–255).
STATS_BAND_ALPHA: int = 100

#: Default maximum frame alpha treated as “window” for mask refine (see :func:`frame_hole_alpha_threshold`).
#: Lower = tighter hole (semi-transparent filigree counts as chrome; less illustration bleed).
DEFAULT_FRAME_HOLE_ALPHA_THRESHOLD: int = 18


def frame_hole_alpha_threshold() -> int:
    """Upper bound for frame alpha that still counts as the editable window.

    Pixels with frame alpha **above** this are cleared from ``m_art`` / ``m_stats`` /
    ``m_integrated`` (template intersected with true hole). Softer rims use
    :func:`frame_chrome_stamp_alpha_threshold` for the final chrome stamp so model pixels
    do not sit visibly on top of semi-transparent filigree.
    """
    raw = os.environ.get("CARD_FACTORY_FRAME_HOLE_ALPHA", "").strip()
    if raw:
        try:
            return max(0, min(255, int(raw)))
        except ValueError:
            pass
    return DEFAULT_FRAME_HOLE_ALPHA_THRESHOLD


#: Default chrome stamp: ``alpha > 0`` restores every non-clear frame pixel over interiors.
#: Increase (e.g. 8) only if a noisy committed PNG falsely tags hole pixels with alpha 1–3.
DEFAULT_FRAME_CHROME_STAMP_ALPHA: int = 0


def frame_chrome_stamp_alpha_threshold() -> int:
    """Minimum frame alpha that **wins** in :func:`steps.composite.apply_committed_frame_authority`.

    The final stamp uses ``frame_png`` wherever ``alpha > this``. Keep this **lower** than
    :func:`frame_hole_alpha_threshold` so anti-aliased / translucent filigree replaces inpainted
    “sticker” edges instead of blending them over chrome.

    Env override: ``CARD_FACTORY_CHROME_STAMP_ALPHA`` (integer, clamped ``0..254``).
    """
    raw = os.environ.get("CARD_FACTORY_CHROME_STAMP_ALPHA", "").strip()
    if raw:
        try:
            return max(0, min(254, int(raw)))
        except ValueError:
            pass
    return DEFAULT_FRAME_CHROME_STAMP_ALPHA


#: After compositing, optional whole-card img2img to soften seams (very conservative).
UNIFY_FINISHED_CARD_PROMPT: str = (
    "MINOR COHESION PASS ONLY on this exact finished trading card. "
    "Preserve all layout and geometry. Do not move, resize, replace, or re-type any "
    "text or numerals — every glyph must remain identical. "
    "Keep pixel-art / flat-game-art — no photorealism, no redrawn characters, no new props. "
    "Only subtly harmonise colour temperature and soften obvious seams between the "
    "pre-existing frame, centre artwork, and stats band. Treat this as a light colour grade, "
    "not a redesign."
)


def final_unify_enabled() -> bool:
    """Whole-card polish step (OpenAI img2img).

    **On by default** — no env var required. Tests and local runs can set
    ``CARD_FACTORY_FINAL_UNIFY=0`` (or ``false`` / ``no`` / ``off``) to skip.
    Any other value, including unset or empty, keeps unify enabled.
    """
    raw = os.environ.get("CARD_FACTORY_FINAL_UNIFY", "").strip().lower()
    return raw not in ("0", "false", "no", "off")


def single_pass_card_enabled() -> bool:
    """One inpaint over art ∪ stats (frame-sampled tints), then typography + frame.

    **On by default** — no env var required. Set ``CARD_FACTORY_SINGLE_PASS_CARD=0``
    (or ``false`` / ``no`` / ``off``) to use the legacy multi-layer path
    (separate illustration + stats band + ``layer_composite``).

    When single-pass wins, ``final_unify_enabled`` is skipped for that slot (avoid
    stacking two whole-card passes).
    """
    raw = os.environ.get("CARD_FACTORY_SINGLE_PASS_CARD", "").strip().lower()
    return raw not in ("0", "false", "no", "off")


#: Alpha for frame-sampled **art** placeholder in single-pass source (stats uses STATS_BAND_ALPHA).
SINGLE_PASS_ART_PLACEHOLDER_ALPHA: int = 90

#: Pixels preserved as an inner mat ring between the illustration aperture and the frame chrome.
#: ``clamp_forbidden_zones`` insets the illustration clear-rect by this amount so the model's
#: inner border decoration survives; card assembly fills the ring with a frame-sampled colour.
#: 0 disables the mat (legacy behaviour — plain rectangular hole).
ILLUSTRATION_INNER_MAT_PX: int = 12

#: Erode the seeded transparent hole (connected component) by this many pixels for paint masks
#: and for the second wipe during frame hardening — keeps art inside the organic bezel.
INTERIOR_HOLE_ERODE_PX: int = 6

#: BFS for hole extraction is limited to ``inner_rect`` expanded by this padding (card pixels).
INTERIOR_CC_BBOX_PAD_PX: int = 48

#: If the seeded transparent component is smaller than this (px²), fall back to rectangular inner hull.
INTERIOR_CC_MIN_AREA_PX: int = 200

#: After single-pass blend, replace the outer N pixels of the paint mask with a flat mat colour.
#: **Default 0** — a non-zero value is a visible rectangular outline (often reads as 'black border'
#: when mat sampling is dark); enable only if you explicitly want to eat model-drawn rim lines.
SINGLE_PASS_EDGE_STRIP_PX: int = 0

#: Prepended to the user illustration line for single-pass (art ∪ stats) inpaint.
SINGLE_PASS_INPAINT_PROMPT_LEAD: str = (
    "Trading card INTERIOR only — never paint the outer chrome, ornamental rim, or card silhouette "
    "(those come from the committed frame). Work only inside the masked interior.\n\n"
    "VALUE HARMONY: Match the committed frame’s **value structure** — interior scene should read **somewhat "
    "lighter and more lively** than the dark/desaturated border chrome so the art feels *inside* the bezel, "
    "not like a separate sticker. You may use the full palette; avoid a flat slab that is uniformly as dark as "
    "the frame.\n\n"
    "INTEGRATED INTERIOR (critical): The upper illustration window and lower stats band are ONE scene, "
    "not two separate rectangles or UI panels. Do not use a flat poster block on top and a different "
    "flat color slab below; avoid a harsh horizontal seam, arbitrary maroon/grey fill bands, or "
    "\"floating sticker\" art that stops at a ruler-straight cut. The lower plaque must read as the "
    "same world as the main subject — continuous background, consistent lighting direction, and "
    "materials that could exist in the same tableaux (e.g. icing, parchment, enamel inlay, carved "
    "stone, candy glass) — while staying visually calm so stats text can be added later.\n\n"
    "NO panel chrome: absolutely no thin black, dark brown, or grey **line or stroke** tracing a "
    "rectangle around the scene; no comic-book border, drop-shadow box, UI frame, poster edge, or "
    "picture mat outline. The scene should soften into the edges with environment and colour, not a drawn frame.\n\n"
    "NO horizontal white (or near-white) gutter bar splitting upper and lower — floors, walls, and "
    "ground plane must continue naturally across the full interior height; characters must not be "
    "cut in half by a blank strip.\n\n"
    "Carry subtle motifs, gradients, or environmental storytelling across the boundary so upper and "
    "lower feel connected. A soft vignette, decorative in-world divider, or natural terrain fold is "
    "fine; a stark two-tone split is not.\n\n"
    "The translucent tinted regions in the edit source are palette hints from the real frame — "
    "harmonise with them; do not replace them with large unrelated solid fills.\n\n"
    "NO readable letters, digits, words, logos, or typography anywhere in the interior — leave glyphs "
    "entirely to post.\n\n"
    "Subject and composition: follow the user line below for the main focus while honouring all constraints above."
)

#: Prompt prefix injected before every illustration prompt (§6.3).
NO_FRAME_PROMPT_PREFIX: str = (
    "Do not draw a card frame, decorative border, outer rim, or edge treatment; "
    "generate only the interior artwork that will sit inside an existing frame. "
)
