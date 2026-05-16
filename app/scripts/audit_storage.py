"""CLI: audit on-disk artifacts against DB pointers; optionally delete orphans.

Invoke via ``make audit-storage`` (runs inside the board-factory container).

Default: report only (read-only).

Flags:

* ``--apply``  delete every **tracked** orphan file across boards, decks, and
               tokens (files with no DB row).
* ``--prune-stale``  delete transient generation leftovers (proposals,
                     previews, legacy ``workspace/tokens/``, card masks, …).
* ``--json``   machine-readable JSON (includes prune stats when flags set).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from infrastructure.storage_audit import (
    prune_orphan_files,
    prune_stale_workspace,
    render_prune_summary,
    render_text,
    run_audit,
)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="audit_storage",
        description=(
            "Compare files on disk against DB pointers. "
            "With --apply, delete tracked orphan files. "
            "With --prune-stale, delete transient generation leftovers."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Delete tracked orphan files after reporting (default: dry run).",
    )
    parser.add_argument(
        "--prune-stale",
        action="store_true",
        help="Delete transient workspace leftovers (proposals, previews, …).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of the human-readable report.",
    )
    return parser.parse_args(argv)


def _to_jsonable(report, prune, stale_prune) -> dict:
    return {
        "boards_root": str(report.boards_root),
        "decks_root": str(report.decks_root),
        "tokens_root": str(report.tokens_root),
        "summary": {
            bucket: {
                "lifecycle": s.lifecycle,
                "file_count": s.file_count,
                "total_bytes": s.total_bytes,
                "orphan_count": s.orphan_count,
                "orphan_bytes": s.orphan_bytes,
            }
            for bucket, s in report.summarize().items()
        },
        "dangling": [asdict(d) for d in report.dangling],
        "orphans": [asdict(f) for f in report.orphan_files()],
        "prune": asdict(prune),
        "prune_stale": asdict(stale_prune),
    }


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    report = run_audit()
    prune = prune_orphan_files(report, apply=args.apply)
    stale_prune = prune_stale_workspace(report, apply=args.prune_stale)

    if args.json:
        print(json.dumps(_to_jsonable(report, prune, stale_prune), indent=2, sort_keys=True))
    else:
        print(render_text(report))
        if prune.deleted_files or prune.errors:
            print(render_prune_summary(prune))
        if stale_prune.deleted_files or stale_prune.errors:
            lines = render_prune_summary(stale_prune).replace("Orphan prune", "Stale prune")
            print(lines)
    return 1 if prune.errors or stale_prune.errors else 0


if __name__ == "__main__":
    sys.exit(main())
