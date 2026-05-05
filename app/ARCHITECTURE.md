# `app/` architecture

This codebase is organized **vertical-slice / domain-driven**: top-level
folders inside `app/` are *domains*; each domain holds the same fixed set
of *technical layers*. The goal is "everything you need to change one
feature lives in one folder."

## Domains

A domain is a noun the product reasons about. Today:

| Domain | Owns |
| --- | --- |
| `boards/`    | Board entity, ownership, paths, catalog config (style, generation, frame, layout), style-lock palette. |
| `cells/`     | Spaces, feature panels, and the centerpiece. The unit of *art produced for a board*. |
| `assets/`    | Per-cell history rows, live PNGs, asset URLs, the `/asset/...` HTTP routes. |
| `prompts/`   | Resolved prompts for a cell — live source pointer, mockup-prompt builder. |
| `auth/`      | Users, sessions, API-key secrets, the auth middleware, provider-status checks. |
| `jobs/`      | The async job runner, pipeline adapters, cost ledger, terminal-job snapshots. |

A new domain only earns its place when it's a noun the product team would
say in a sprint review. "Search" is a domain. "Helpers" is not.

## Layers (within each domain)

Each domain folder uses the **same set of file names**, no synonyms.
If a domain doesn't need a layer, that file simply doesn't exist; do
not invent a new word.

| Layer | File | Purpose |
| --- | --- | --- |
| `repository.py` | DB I/O: opens `session_scope`, returns ORM rows or domain dicts. No HTTP. |
| `services.py`   | Use cases: orchestrate repository calls, apply business rules. What routes call. No HTTP. |
| `routes.py`     | FastAPI endpoints. Thin: parse request → call service → return response. |

ORM models for **all** domains live together in `models/` (see
"Auxiliary top-level packages" below) so foreign keys resolve at
import time and contributors can see the full schema in one file. A
domain still owns its own *data* — those classes are read/written only
through that domain's `repository.py`.

Two pragmatic exceptions to "one services.py per domain":

* **`jobs/`** keeps `runner.py`, `pipeline_adapters.py`, and
  `cost_ledger.py` as separate descriptive files. The runtime, the
  pipeline-glue, and the cost ledger are different enough that
  jamming them into one `services.py` makes greppability worse, not
  better. They are still "the services layer" — just three files
  instead of one.
* **`prompts/`** keeps `live.py`, `live_source.py`, and `mockup.py`
  as separate descriptive files. Same reasoning: each handles a
  distinct prompt-building concern with no shared state.

Banned synonyms: `handlers.py`, `controllers.py`, `api.py`, `dao.py`,
`gateway.py`, `manager.py`, `helpers.py`, `utils.py`. If you find
yourself reaching for one of these, the file probably belongs in a
different layer or domain.

## Cross-domain rules

The dependency graph is acyclic:

```
auth   <─── (depended on by everything; depends on nothing)

boards <─── cells, assets, prompts, jobs
cells  <─── assets, prompts, jobs
assets <─── prompts, jobs
prompts <── jobs
jobs   ──> orchestrator; depends on everything
```

Practical rules:

* `auth/` never imports from another domain.
* `boards/` never imports from `cells/`, `assets/`, `prompts/`, `jobs/`.
* If a service needs data from another domain, it goes through that
  domain's `services.py` (not its `repository.py` directly). One door.

## Auxiliary top-level packages

A few packages exist alongside the domains because they hold genuinely
cross-cutting code that doesn't belong to any one domain:

* `infrastructure/` — DB engine + ``BoardStore`` + file-IO helpers.
* `models/`         — SQLAlchemy ORM table definitions for **all** domains.
                      Kept together so foreign keys resolve at import time
                      and so contributors can see the full schema in one
                      file. Each domain still owns its own *data* — these
                      classes are read/written through that domain's
                      `repository.py`.
* `views/`          — Pure Jinja view-models (no FastAPI, no DB), shared
                      across domain templates.
* `routes/`         — FastAPI routers. Some routers are tightly coupled to
                      a single domain and live in `<domain>/routes.py`;
                      others are cross-domain (`home`, `auth login flow`)
                      and live here.

## Composition root

`app/server.py` is the only place that wires domains together: it
mounts each domain's `routes.py` on the FastAPI app, registers
middleware, and starts the boot hooks in `app/boot.py`. Nothing else
should know about FastAPI's `app` instance.

## Why this matters

The thing that kills DDD layouts is naming drift. When one domain
calls its HTTP layer `handlers.py`, another `routes.py`, and a third
`api.py`, a global search for "handlers" misses two-thirds of the
codebase. Locking the names down once means every reader, every grep,
every refactor scales linearly.
