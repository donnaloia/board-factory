# Tech specs

Product and feature specifications for Board Factory. Each subdirectory is one feature area.

| Path | Status | Served by app |
|------|--------|----------------|
| [board-layout/prose.md](board-layout/prose.md) | Live | Yes — explanatory sections on each board's **Tech spec** page (`…/board-games/{slug}/spec`) |
| [card-factory/spec.md](card-factory/spec.md) | Draft | No — planning; layout JSON/SVG in this folder |
| [space-animations/spec.md](space-animations/spec.md) | Draft | No — planning |
| [tokens/proposal.md](tokens/proposal.md) | Proposal | No — pre-implementation alignment |

**Live geometry** for boards always comes from the database (`board_games.body_json`), not from these files. Only `board-layout/prose.md` is loaded at runtime; tables and diagrams on the Tech spec page are generated from the catalog.

Repo-wide architecture and diagrams: [docs/architecture.md](../docs/architecture.md).

Product backlog (not yet specced or built): [docs/TODO.md](../docs/TODO.md).
