"""CardProvider Protocol — contract for chrome and illustration generation."""

from __future__ import annotations

from typing import Protocol

from PIL import Image


class CardProvider(Protocol):
    """Image provider for Card Factory.

    All methods receive PIL ``Image`` objects and return PIL ``Image`` objects
    (RGBA, canvas-sized). The pipeline handles file I/O and compositing;
    providers deal only with pixels.
    """

    def model_id(self) -> str:
        """Human-readable identifier recorded in manifests (e.g. ``'gpt-image-2'``)."""
        ...

    def generate_chrome_candidate(
        self,
        *,
        canvas: tuple[int, int],
        m_chrome_paint: Image.Image,
        prompt: str,
        palette_colors: list[tuple[int, int, int]],
    ) -> Image.Image:
        """Generate one chrome (border + stats surround) candidate.

        ``m_chrome_paint`` — RGBA mask; white pixels are where paint is allowed.
        Returns an RGBA image; forbidden zones (illustration ∪ stats glyph box)
        will be zeroed by the caller after this returns.
        """
        ...

    def generate_illustration(
        self,
        *,
        canvas: tuple[int, int],
        m_art: Image.Image,
        prompt: str,
        palette_colors: list[tuple[int, int, int]],
        style_reference: Image.Image | None = None,
    ) -> Image.Image:
        """Generate the card illustration constrained to ``m_art``.

        ``prompt`` should already include the §6.3 no-frame prefix.
        ``style_reference`` — full committed frame at ``canvas`` size; inpaint
        source uses it when the provider supports img2img fidelity (OpenAI).
        Returns an RGBA image; pixels outside ``m_art`` may be arbitrary —
        the compositor zeroes them before compositing.
        """
        ...

    def unify_finished_card(
        self,
        *,
        card: Image.Image,
        canvas: tuple[int, int],
        palette_colors: list[tuple[int, int, int]],
    ) -> Image.Image:
        """Optional conservative whole-card pass after layer compositing."""
        ...

    def paint_integrated_card(
        self,
        *,
        canvas: tuple[int, int],
        source_image: Image.Image,
        edit_mask: Image.Image,
        prompt: str,
        palette_colors: list[tuple[int, int, int]],
        style_reference: Image.Image | None = None,
    ) -> Image.Image:
        """Inpaint the union of art + stats so interior reads as one piece (frame in source).

        ``source_image`` is typically frame-sampled tints composited under/over the
        committed frame; ``edit_mask`` marks pixels the model may change.
        """
        ...
