"""Views — pure view-model builders consumed by templates.

A "view" here is a side-effect-free function that takes a domain dict
(typically a catalog) and returns a structure ready for Jinja iteration.
The HTTP layer assembles request context; this layer turns domain data
into render-ready rows. No DB calls, no FastAPI imports.

Layout (per ``app/ARCHITECTURE.md``):

  * ``spec_data.py``  — Tables for the spec page (designs, density rollup).
  * ``board_svg.py``  — Inline SVG renderer for the board view.
"""
