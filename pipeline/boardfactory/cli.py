"""Board Factory CLI entrypoint.

Each subcommand wraps one or more pipeline steps. The top-level `run` command
chains style → catalog validation → generate (all three categories) → cleanup,
which is the maximum work that can be done unattended. Everything after cleanup
requires human review and is invoked separately (states, preview, export).
"""

from __future__ import annotations

import sys

import click

from . import __version__, config
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


def _load_catalog() -> Catalog:
    if not config.CATALOG_PATH.exists():
        raise click.UsageError(
            f"Catalog not found at {config.CATALOG_PATH.relative_to(config.REPO_ROOT)}. "
            f"Copy catalog/example.yml to catalog/board.yml and edit it."
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


@click.group(help="Board Factory — pixel-art board game asset pipeline.")
@click.version_option(__version__)
def cli() -> None:
    config.ensure_dirs()


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
    do_style_lock(run, cat)
    print_run_footer(run)
    append_run_log(run, config.LOGS_DIR / "run.log")


@cli.command(help="Step 3: generate candidates for all three asset categories.")
def generate() -> None:
    cat = _load_catalog()
    provider = get_provider()
    run = RunStats(label="generate")
    _print_header("Generate", cat)
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
