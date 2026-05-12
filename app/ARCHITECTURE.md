# `app/` architecture

This codebase is organized **vertical-slice / domain-driven**: top-level
folders inside `app/` are *domains*; each domain holds the same fixed set
of *technical layers*. The goal is "everything you need to change one
feature lives in one folder."

## Domains

Bounded-context packages live under **`domains/`** (import paths like
``domains.boards``, ``domains.cells``). Other top-level folders such as
``home/`` and ``auth/`` are still domain-shaped but not nested under
``domains/`` yet.

A domain is a noun the product reasons about. Today:

| Domain | Owns |
| --- | --- |
| `domains/boards/`    | Board entity, ownership, paths, catalog config (style, generation, frame, layout), style-lock palette. |
| `home/`      | Root ``/`` board picker HTML + ``/api/boards`` create/delete JSON. |
| `domains/cards/` | Card Factory — decks/sets, layout templates, routes & services linking to `board_games` for palette/style; jobs delegate to `pipeline/cardfactory/`. |
| `domains/cells/`     | Spaces, feature panels, centerpiece; ``live_asset_version_id`` references ``asset_versions`` for sidebar metadata. |
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
| `models.py`     | SQLAlchemy table mappings for that domain. Subclass `Base` from `infrastructure.orm`. |
| `repository.py` | DB I/O: opens `session_scope`, returns ORM rows or domain dicts. No HTTP. |
| `services.py`   | Use cases: orchestrate repository calls, apply business rules. What routes call. No HTTP. |
| `routes_html.py` | FastAPI endpoints that return Jinja ``TemplateResponse`` (pages only). |
| `routes_api.py`  | JSON, SSE, streaming/binary, and non-page writes. Form POSTs that redirect (login, etc.) live here too. |

If a domain has no persisted tables, `models.py` is omitted. Cross-table
foreign keys use string names (`"board_games.id"`, etc.); the database is
still one physical schema, but each domain's ORM types live with that
domain. A domain still owns its *data* — those classes are read/written
only through that domain's `repository.py`.

Older git history may show a single ``routes.py``; new work uses
``routes_html`` + ``routes_api`` (plus ``routes_common`` where shared
``Depends`` types help — see ``domains/boards/``).

Two pragmatic exceptions to "one services.py per domain":

* **`auth/`** uses ``routes_html.py`` (login/register/forgot GET pages) and
  ``routes_api.py`` (session form POSTs + ``/api/profile`` JSON).
* **`home/`** uses ``routes_html.py`` (root ``/`` board picker) and
  ``routes_api.py`` (``POST/DELETE /api/boards``).
* **`domains/boards/`** splits HTTP into ``routes_html.py`` (Jinja pages under
  ``/users/.../board-games/...``) and ``routes_api.py`` (JSON, form actions, image streams)
  so HTML concerns stay separate from pipeline/API endpoints. Shared
  ``Depends`` wiring lives in ``routes_common.py``.
* **`jobs/`** keeps `runner.py`, `pipeline_adapters.py`, `cost_ledger.py`,
  and ``routes_api.py`` (job tray JSON + SSE + cost summary). The runtime,
  the pipeline-glue, and the cost ledger are different enough that
  jamming them into one `services.py` makes greppability worse, not
  better.
* **Mockup** image prompt composition lives in ``domains/boards/mockup_prompt.py``.
  **Side-panel active prompt** is assembled in ``infrastructure.deps`` from
  ``asset_versions`` + ``cells`` (and ``boardfactory.assets.read_meta`` for legacy
  sidecars), not a separate ``prompts/`` package.

Banned synonyms: `handlers.py`, `controllers.py`, `api.py`, `dao.py`,
`gateway.py`, `manager.py`, `helpers.py`, `utils.py`. If you find
yourself reaching for one of these, the file probably belongs in a
different layer or domain.

## Cross-domain rules

The dependency graph is acyclic:

```
auth   <─── (depended on by everything; depends on nothing)

domains.boards <─── domains.cells, assets, jobs
domains.cells  <─── assets, jobs
assets <── jobs
jobs   ──> orchestrator; depends on everything
```

Practical rules:

* `auth/` never imports from another domain.
* `domains/boards/` never imports `domains/cells/` **services** or **repository**
  (catalog assembly may use shared ORM types from ``domains.cells.models``).
* For behavior in another domain, call that domain's ``services.py``, not its
  ``repository.py``, unless the shared-ORM exception above applies.

## Auxiliary top-level packages

A few packages exist alongside the domains because they hold genuinely
cross-cutting code that doesn't belong to any one domain:

* `infrastructure/` — DB engine, shared ``DeclarativeBase`` (``orm.py``),
                      ``BoardStore`` + file-IO helpers.
* `frontend/`       — Jinja ``templates/``, static assets (``static/``; URL
                      ``/static`` in ``server.py``), and ``views/`` (pure
                      view-model + SVG helpers for the board UI — no FastAPI, no DB).
* `infrastructure/deps` — Auth guards, board URL resolution, template context
                      dicts, job enqueue, side-panel JSON builders, etc. Used by
                      every domain router; not a route table.
* `exporter/` — **Geometry**, **`interaction_graph`**, **asset wiring**, **polish**, **``project.json``**;
                      **GET** ``…/export/project-bundle.zip`` lives on **boards** routes (temp zip, no exporter routes). See ``docs/project-export-spec.md`` §9.

## Composition root

`app/server.py` is the only place that wires domains together: it
mounts each domain's ``routes_html`` / ``routes_api`` routers on the FastAPI app,
registers middleware, and starts the boot hooks in `app/boot.py`. Nothing else
should know about FastAPI's `app` instance.

## Why this matters

The thing that kills DDD layouts is naming drift. When one domain
calls its HTTP layer `handlers.py`, another `routes.py`, and a third
`api.py`, a global search for "handlers" misses two-thirds of the
codebase. Locking the names down once means every reader, every grep,
every refactor scales linearly.
