"""Mock card provider — offline placeholder for tests.

Generates deterministic placeholder images so the full pipeline can
run without an API key or network access.
"""

from __future__ import annotations

from PIL import Image, ImageDraw


_CHROME_BORDER_COLOR = (40, 30, 20, 255)     # dark brown frame ring
_CHROME_BG_COLOR = (0, 0, 0, 0)             # transparent interior
_ILLUSTRATION_COLOR = (120, 160, 200, 255)   # steel-blue art placeholder
_STATS_BG_COLOR = (60, 50, 40, 255)          # dark plaque for stats


class MockCardProvider:
    """Returns simple colored rectangles — no network, no GPU."""

    def model_id(self) -> str:
        return "mock"

    def generate_chrome_candidate(
        self,
        *,
        canvas: tuple[int, int],
        m_chrome_paint: Image.Image,
        prompt: str,
        palette_colors: list[tuple[int, int, int]],
    ) -> Image.Image:
        """Draw a solid border using the paint mask as a stencil."""
        w, h = canvas
        result = Image.new("RGBA", (w, h), _CHROME_BG_COLOR)
        draw = ImageDraw.Draw(result)

        # Paint the border ring wherever the chrome mask is opaque.
        mask_arr = m_chrome_paint.convert("L")
        border_layer = Image.new("RGBA", (w, h), _CHROME_BORDER_COLOR)
        result = Image.composite(border_layer, result, mask_arr)
        return result

    def generate_illustration(
        self,
        *,
        canvas: tuple[int, int],
        m_art: Image.Image,
        prompt: str,
        palette_colors: list[tuple[int, int, int]],
        style_reference: Image.Image | None = None,
    ) -> Image.Image:
        """Return a flat steel-blue rectangle inside the art mask."""
        w, h = canvas
        result = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        fill = Image.new("RGBA", (w, h), _ILLUSTRATION_COLOR)
        mask_l = m_art.convert("L")
        result = Image.composite(fill, result, mask_l)
        return result

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
        """Tint the union mask so single-pass integration code paths stay testable."""
        out = source_image.convert("RGBA")
        if out.size != canvas:
            out = out.resize(canvas, Image.NEAREST)
        fill = Image.new("RGBA", canvas, _ILLUSTRATION_COLOR)
        return Image.composite(fill, out, edit_mask.convert("L"))

    def unify_finished_card(
        self,
        *,
        card: Image.Image,
        canvas: tuple[int, int],
        palette_colors: list[tuple[int, int, int]],
    ) -> Image.Image:
        """Offline — no second-generation pass."""
        if card.size != canvas:
            return card.resize(canvas, Image.NEAREST)
        return card.copy()
