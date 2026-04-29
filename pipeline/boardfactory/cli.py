"""Board Factory CLI entrypoint.

Each subcommand wraps one or more pipeline steps. The top-level `run` command
chains style → catalog validation → generate (all three categories) → cleanup,
which is the maximum work that can be done unattended. Everything after cleanup
requires human review and is invoked separately (states, preview, export).
"""

from __future__ import annotations

import os
import sys

import click

from . import __version__, boards, config
from .geometry import MockupAspectMismatch, validate_mockup_dimensions
from .progress import (
    RunStats,
    append_run_log,
    console,
    fmt_money,
    print_run_footer,
    print_run_header,
)
from .providers import get_provider
from .schemas import Catalog
from .steps.cleanup import do_cleanup
from .steps.compositor import do_preview
from .steps.export import do_export
from .steps.generate import (
    do_generate_centerpiece,
    do_generate_panels,
    do_generate_spaces,
)
from .steps.states import do_states
from .steps.style_lock import do_style_lock


def _resolve_board() -> str:
    """Pick the active board id. Order: --board flag (handled by Click) →
    BOARDFACTORY_BOARD env → only existing board → migrate legacy → error."""
    env_board = (os.environ.get("BOARDFACTORY_BOARD") or "").strip()
    if env_board:
        return env_board
    only = boards.default_board_id()
    if only:
        return only
    # First-run migration of the classic flat layout.
    migrated = boards.migrate_legacy_flat_layout()
    if migrated:
        console.print(f"[yellow]→[/yellow] Migrated legacy layout to boards/{migrated.id}/")
        return migrated.id
    raise click.UsageError(
        "No board found. Create one with `boardfactory new <board-id>` or set "
        "BOARDFACTORY_BOARD."
    )


def _load_catalog() -> Catalog:
    if not config.CATALOG_PATH.exists():
        raise click.UsageError(
            f"Catalog not found at {config.CATALOG_PATH}. "
            f"This board has no catalog.yml yet."
        )
    return Catalog.load(config.CATALOG_PATH)


def _print_header(label: str, catalog: Catalog) -> None:
    print_run_header(
        f"Board Factory · {label}",
        {
            "project": catalog.project,
            "provider": config.PROVIDER_NAME,
            "palette size": str(catalog.style.palette_size),
            "board": f"{catalog.board_size[0]}×{catalog.board_size[1]}",
            "designs": str(len(catalog.all_space_designs())),
            "panels": str(len(catalog.all_panels())),
        },
    )


def _validate_mockup(catalog: Catalog) -> None:
    """Check the mockup file against the catalog before running any step that uses it.

    Aspect ratio drift > 5% raises a hard error (img2img references would be
    visibly stretched). Dimension differences within tolerance just print a
    note since the pipeline scales bboxes from canvas to mockup space at crop
    time and that's fine for any roughly-correct aspect ratio.
    """
    mockup_path = config.BOARD_ROOT / catalog.style.reference_image
    try:
        mockup_size, warnings = validate_mockup_dimensions(
            mockup_path,
            canvas_size=catalog.board_size,
            strict=True,
        )
    except FileNotFoundError as e:
        raise click.UsageError(str(e)) from None
    except MockupAspectMismatch as e:
        raise click.UsageError(
            f"Mockup aspect ratio is incompatible with the catalog's canvas.\n\n{e}"
        ) from None

    for w in warnings:
        console.print(f"[yellow]![/yellow] {w}")


@click.group(help="Board Factory — pixel-art board game asset pipeline.")
@click.version_option(__version__)
@click.option(
    "--board", "board_id",
    default=None,
    help="Board id to operate on (overrides BOARDFACTORY_BOARD).",
)
@click.pass_context
def cli(ctx: click.Context, board_id: str | None) -> None:
    if board_id:
        config.set_board(board_id)
    else:
        # Defer to env / discovery, but allow board-list / new commands to skip.
        if ctx.invoked_subcommand not in ("list", "new"):
            config.set_board(_resolve_board())
            config.ensure_dirs()


@cli.command(name="list", help="List boards under boards/.")
def list_cmd() -> None:
    found = boards.list_boards()
    if not found:
        # Try a migration on first list-call.
        migrated = boards.migrate_legacy_flat_layout()
        if migrated:
            console.print(f"[yellow]→[/yellow] Migrated legacy layout to boards/{migrated.id}/")
            found = boards.list_boards()
    if not found:
        console.print("[dim]no boards yet — create one with `boardfactory new <id>`[/dim]")
        return
    for b in found:
        flag = "✓" if b.has_catalog else "·"
        console.print(f"  {flag} [bold]{b.id}[/bold]  [dim]{b.project}[/dim]")


@cli.command(help="Create a new empty board.")
@click.argument("board_id")
@click.option("--name", "project_name", default=None, help="Display name (default: board id).")
def new(board_id: str, project_name: str | None) -> None:
    info = boards.create_board(board_id, project_name=project_name)
    console.print(f"[green]✓[/green] Created board [bold]{info.id}[/bold] at boards/{info.id}/")


@cli.command(help="Validate the catalog YAML against the schema.")
def catalog() -> None:
    cat = _load_catalog()
    console.print(f"[green]✓[/green] Catalog valid: [bold]{cat.project}[/bold]")
    console.print(f"   {len(cat.all_space_designs())} unique board space designs")
    total_positions = sum(len(d.positions) for d in cat.all_space_designs())
    console.print(f"   {total_positions} board space positions")
    console.print(f"   {len(cat.all_panels())} feature panels")
    console.print(f"   centerpiece at {cat.centerpiece.bbox}")


@cli.command(help="Step 1: extract the shared palette + style sheet from the mockup.")
def style() -> None:
    cat = _load_catalog()
    run = RunStats(label="style")
    _print_header("Style Lock", cat)
    _validate_mockup(cat)
    do_style_lock(run, cat)
    print_run_footer(run)
    append_run_log(run, config.LOGS_DIR / "run.log")


@cli.command(help="Step 3: generate candidates for all three asset categories.")
def generate() -> None:
    cat = _load_catalog()
    provider = get_provider()
    run = RunStats(label="generate")
    _print_header("Generate", cat)
    _validate_mockup(cat)
    spent = 0.0
    spent += do_generate_spaces(run, cat, provider)
    spent += do_generate_panels(run, cat, provider)
    spent += do_generate_centerpiece(run, cat, provider)
    next_steps = (
        f"[bold]Total estimated cost:[/bold] {fmt_money(spent)}\n"
        f"[bold]Next:[/bold] [cyan]make cleanup[/cyan] then open [cyan]http://localhost:8473[/cyan]"
    )
    print_run_footer(run, next_steps)
    append_run_log(run, config.LOGS_DIR / "run.log")


@cli.command(help="Step 4: snap candidates to the locked palette and pixel grid.")
def cleanup() -> None:
    run = RunStats(label="cleanup")
    cat = _load_catalog()
    _print_header("Cleanup", cat)
    do_cleanup(run)
    next_steps = "[bold]Next:[/bold] open [cyan]http://localhost:8473[/cyan] to review"
    print_run_footer(run, next_steps)
    append_run_log(run, config.LOGS_DIR / "run.log")


@cli.command(help="Step 6: build active variants for approved tiles.")
def states() -> None:
    cat = _load_catalog()
    run = RunStats(label="states")
    _print_header("State Generation", cat)
    do_states(run, cat)
    print_run_footer(run, "[bold]Next:[/bold] [cyan]make preview[/cyan]")
    append_run_log(run, config.LOGS_DIR / "run.log")


@cli.command(help="Step 7: composite the assembled board for visual review.")
def preview() -> None:
    cat = _load_catalog()
    run = RunStats(label="preview")
    _print_header("Composite Preview", cat)
    _validate_mockup(cat)
    do_preview(run, cat)
    print_run_footer(run, "[bold]Next:[/bold] [cyan]make export[/cyan]")
    append_run_log(run, config.LOGS_DIR / "run.log")


@cli.command(help="Step 8: copy approved assets to board_assets/ with manifest.")
def export() -> None:
    cat = _load_catalog()
    run = RunStats(label="export")
    _print_header("Export", cat)
    do_export(run, cat)
    print_run_footer(run, f"[bold]Done.[/bold] Assets in [cyan]{config.EXPORT_DIR.relative_to(config.REPO_ROOT)}/[/cyan]")
    append_run_log(run, config.LOGS_DIR / "run.log")


@cli.command(help="End-to-end: style → catalog → generate → cleanup. Stops for review.")
def run() -> None:
    cat = _load_catalog()
    provider = get_provider()
    rs = RunStats(label="run")
    _print_header("Full Run", cat)
    _validate_mockup(cat)

    do_style_lock(rs, cat)
    spent = 0.0
    spent += do_generate_spaces(rs, cat, provider)
    spent += do_generate_panels(rs, cat, provider)
    spent += do_generate_centerpiece(rs, cat, provider)
    do_cleanup(rs)

    next_steps = (
        f"[bold]Total estimated cost:[/bold] {fmt_money(spent)}\n"
        f"[bold]Next:[/bold] open [cyan]http://localhost:8473[/cyan] to review and approve\n"
        f"Then: [cyan]make states[/cyan] → [cyan]make preview[/cyan] → [cyan]make export[/cyan]"
    )
    print_run_footer(rs, next_steps)
    append_run_log(rs, config.LOGS_DIR / "run.log")


def main() -> None:
    try:
        cli(standalone_mode=True)
    except click.UsageError as e:
        console.print(f"[red]✗[/red] {e}")
        sys.exit(2)
    except Exception as e:
        console.print(f"[red]✗ Error:[/red] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
