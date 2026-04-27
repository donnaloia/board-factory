"""Rich-based progress UX for the Board Factory CLI.

Long-running CLI commands wrap their work in `step()` for a labeled section,
`spinner()` for unknown-duration single operations, and `progress_bar()` for
batch loops. Each step's outcome is collected in `RunStats` so the run command
can print a final summary panel and append a one-line entry to workspace/logs/run.log.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)

console = Console()


def fmt_duration(seconds: float) -> str:
    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def fmt_money(usd: float) -> str:
    if usd == 0:
        return "$0.00"
    if usd < 0.01:
        return f"${usd:.4f}"
    return f"${usd:.2f}"


@dataclass
class StepStats:
    name: str
    started: float = field(default_factory=time.monotonic)
    items: int = 0
    failures: list[str] = field(default_factory=list)
    extras: dict[str, str] = field(default_factory=dict)

    def elapsed(self) -> float:
        return time.monotonic() - self.started


@dataclass
class RunStats:
    started: float = field(default_factory=time.monotonic)
    steps: list[StepStats] = field(default_factory=list)
    label: str = ""

    def total_elapsed(self) -> float:
        return time.monotonic() - self.started


def print_run_header(title: str, info: dict[str, str]) -> None:
    body = "\n".join(f"[bold]{k}:[/bold] {v}" for k, v in info.items())
    console.print(Panel(body, title=f"[bold cyan]{title}", border_style="cyan", expand=False))


def print_run_footer(run: RunStats, next_steps: str = "") -> None:
    rows = [f"[bold]Total time:[/bold] {fmt_duration(run.total_elapsed())}", ""]
    for s in run.steps:
        status = "[red]✗[/red]" if s.failures else "[green]✓[/green]"
        details = f"{s.items} items"
        if s.failures:
            details += f", [red]{len(s.failures)} failed[/red]"
        if s.extras:
            details += "  " + "  ".join(f"[dim]{k}=[/dim]{v}" for k, v in s.extras.items())
        rows.append(f"  {status} {s.name:<14} {fmt_duration(s.elapsed()):>8}   {details}")
    if next_steps:
        rows.append("")
        rows.append(next_steps)
    console.print(Panel("\n".join(rows), title="[bold green]Done", border_style="green", expand=False))


@contextmanager
def step(run: RunStats, label: str) -> Iterator[StepStats]:
    n = len(run.steps) + 1
    s = StepStats(name=label)
    run.steps.append(s)
    console.rule(f"[bold cyan][{n}] {label}", style="cyan")
    try:
        yield s
    finally:
        elapsed = fmt_duration(s.elapsed())
        if s.failures:
            console.print(
                f"[yellow]⚠[/yellow]  {label} finished with "
                f"[red]{len(s.failures)} failures[/red] in {elapsed} "
                f"({s.items} items completed)"
            )
            for f in s.failures[:10]:
                console.print(f"   [red]✗[/red] {f}")
            if len(s.failures) > 10:
                console.print(f"   [dim]... {len(s.failures) - 10} more[/dim]")
        else:
            extras = ""
            if s.extras:
                extras = "  " + "  ".join(f"[dim]{k}=[/dim]{v}" for k, v in s.extras.items())
            console.print(f"[green]✓[/green]  {label} ({s.items} items in {elapsed}){extras}")


@contextmanager
def spinner(message: str) -> Iterator[None]:
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold]{task.description}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as prog:
        prog.add_task(message, total=None)
        yield


class _BarHandle:
    def __init__(self, prog: Progress, task_id: int):
        self._prog = prog
        self._task = task_id

    def set_current(self, current: str) -> None:
        self._prog.update(self._task, description=current)

    def advance(self, n: int = 1) -> None:
        self._prog.advance(self._task, n)

    def write(self, msg: str) -> None:
        self._prog.console.print(msg)


@contextmanager
def progress_bar(label: str, total: int) -> Iterator[_BarHandle]:
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold]{task.description}"),
        BarColumn(bar_width=None),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as prog:
        task = prog.add_task(label, total=total)
        yield _BarHandle(prog, task)


def append_run_log(run: RunStats, log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a") as f:
        f.write(f"\n=== {datetime.now().isoformat(timespec='seconds')} ")
        if run.label:
            f.write(f"label={run.label} ")
        f.write(f"total={fmt_duration(run.total_elapsed())} ===\n")
        for s in run.steps:
            f.write(
                f"  [{s.name:<14}] {s.items:>4} items, "
                f"{len(s.failures):>3} failures, "
                f"{fmt_duration(s.elapsed())}"
            )
            if s.extras:
                f.write("  " + "  ".join(f"{k}={v}" for k, v in s.extras.items()))
            f.write("\n")
            for fl in s.failures:
                f.write(f"      FAIL: {fl}\n")
