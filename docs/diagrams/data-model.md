# Data model — relational tables

The Board Factory database holds **users, ownership, the board catalog,
the per-cell history index, persisted job snapshots, and the cost
ledger**. Generated PNGs live on disk under each board's `workspace/`.

The schema is the same on PostgreSQL (default in Compose) and SQLite
(local file mode) — Alembic migrations target both.

## Schema

```mermaid
erDiagram
  users ||--o{ user_secrets : "owns"
  users ||--o{ browser_sessions : "logged in via"
  users ||--o{ owned_boards : "owns"

  users {
    string id PK "32-hex"
    string email UK
    string password_hash
    string display_name
    string icon_glyph
    string icon_color
    bigint created_ms
    bigint last_login_ms
  }

  user_secrets {
    int id PK
    string user_id FK
    string kind "openai · pixellab · …"
    text ciphertext
  }

  browser_sessions {
    string sid PK
    string user_id FK
    bigint created_ms
    bigint last_seen_ms
  }

  owned_boards {
    string board_id PK "slug"
    string user_id FK
    bigint created_ms
  }

  board_games {
    string board_id PK "slug"
    text body_json "Pydantic Catalog (style + spaces + panels + centerpiece + frame + generation)"
    bigint updated_ms
    text palette_json "from style_lock; materialized to disk on job start"
    text palette_gpl_text
    bigint style_lock_updated_ms
  }

  asset_versions {
    int id PK
    string board_id "slug — soft FK"
    string category "spaces · panels · centerpiece"
    string asset_id "design id, panel id, or 'centerpiece'"
    string basename "<ts>__<seq>.png"
    string rel_path UK "history/<cat>/<asset_id>/<basename>"
    string sha256 "for byte-equality detection of live"
    bigint ts_ms
    text meta_json "operation, prompt, extras"
  }

  job_runs {
    string id PK "12-hex from uuid4"
    string label "human-friendly"
    string operation "generate.spaces · regen.panels · …"
    string target "asset id or category"
    string status "queued · running · done · failed · killed"
    float progress "0..1"
    float eta_s
    float cost_estimate
    float cost_actual
    float started_at
    float ended_at
    text error
    text log_json
  }

  cost_entries {
    int id PK
    float ts
    string op "regen.spaces · generate.all · …"
    string target
    int units
    float usd
  }
```

## Why each table exists

| Table | Purpose | Key design notes |
|---|---|---|
| `users` | Authenticated identities. | Create the first user via **Register** on a fresh install, or restore a dev database snapshot that already includes users. |
| `user_secrets` | Per-user, per-provider secret material (OpenAI / PixelLab keys). | Stored as ciphertext, decrypted at request time when starting a pipeline job. Multiple `kind` values per user are supported. |
| `browser_sessions` | Server-side sessions for the cookie auth middleware. | TTL handled at the application layer via `last_seen_ms`. |
| `owned_boards` | Many-to-one mapping from board slug → owning user. | Boards on disk without an `owned_boards` row are not visible. `backfill_owned_boards_if_empty` attaches every disk board to the oldest user when the table is empty. |
| `board_games` | One row per board. Column-typed header fields and `body_json` (perimeter layout, frame, etc.); per-cell data lives in `cells`. | The catalog is an aggregate; `body_json` is validated with Pydantic. Palette columns are written by the style-lock / workspace flow. |
| `asset_versions` | Index of every PNG in `workspace/history/`, with `cell_id` linking to `cells`. | Inserts are idempotent on `(board_uuid, rel_path)`; the app sets `cells.live_asset_version_id` to the row that was promoted to `live/`. |
| `job_runs` | Persisted terminal snapshots of every job. | `JobRunner` keeps active jobs in memory; on completion, `services.job_runs.persist_terminal` writes the row so the tray survives process restarts. Queued or in-flight jobs at restart time are lost — there's no broker. |
| `cost_entries` | One row per provider call that spent money. | `cost_ledger.summary()` aggregates these into the lifetime + session-since-startup costs the UI shows. Pure local-compute steps (style_lock, cleanup, states, compositor, export) do not write rows. |

## What is **not** in the database

Deliberately on disk only:

- Generated PNGs (`workspace/history/`, `workspace/live/`).
- Style assets (`workspace/style/palette.{json,gpl}`, `style_sheet.png`).
  The DB also holds `palette_json` / `palette_gpl_text` — the on-disk
  copy is the canonical thing the pipeline reads; the DB copy lets a
  fresh clone re-materialize them without re-running style_lock.
- Composited previews (`workspace/preview/board_idle.png`, `board_active.png`).
- Engine export (`data/boards/<id>/export/`).

This split keeps the database small and PNGs out of `pg_dump` while
letting the row count (rather than the byte count) drive every query.

## Foreign-key story

| Constraint | Behavior |
|---|---|
| `user_secrets.user_id → users.id` | `ON DELETE CASCADE`. Deleting a user removes their stored API keys. |
| `browser_sessions.user_id → users.id` | `ON DELETE CASCADE`. Session rows die with the user. |
| `owned_boards.user_id → users.id` | `ON DELETE CASCADE`. Removing a user releases their board ownership records (the on-disk board directory is unaffected). |
| `asset_versions.board_id`, `cost_entries`, `job_runs` | **No** database FK to `board_games`. The application layer enforces consistency; this lets us reseed Postgres while keeping `data/boards/` on disk intact, and lets us record cost / job rows for boards that don't yet have a catalog row. |

## Migrations

Schema is applied with a **single** Alembic revision, `0001_full_schema`, which
creates all application tables from the SQLAlchemy ORM. There is no long
revision chain in the repo. See `app/migrations/README` and `db/snapshots/README.md`
for empty-DB vs snapshot-restore workflows.
