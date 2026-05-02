# Postgres snapshots (optional, early development)

Compose keeps the real database in the **`postgres_data` Docker volume**, not in git. To **commit a copy** of the DB for another machine or backup:

## Create / refresh the snapshot

With the stack running (`make up`):

```bash
make db-snapshot
```

This writes **`postgres_dev.sql`** in this directory (plain SQL, includes schema + data).

Then:

```bash
git add db/snapshots/postgres_dev.sql
git commit -m "Snapshot dev Postgres"
```

### Defaults

The Makefile uses the same defaults as `docker-compose.yml`: user `boardfactory`, database `boardfactory`. Override with `POSTGRES_USER` / `POSTGRES_DB` in your environment if you changed them.

### Security

The dump includes **users, password hashes, sessions, and API key fields** stored in the DB. Treat it like credentials until you stop committing it.

## Restore on a fresh clone

1. `make up` and wait for Postgres to be healthy.
2. **Either** run migrations once (`make db-upgrade`) **or** skip if you will only restore — a full `pg_dump` already contains tables and `alembic_version`.
3. Apply the snapshot:

   ```bash
   make db-restore
   ```

4. Restart the app container if needed (`docker compose restart board-factory`).

If the DB already had data, `--clean` in the dump will drop objects first; this is meant for **dev** machines.

## When you are done checking it in

- Remove `postgres_dev.sql` from git: `git rm --cached db/snapshots/postgres_dev.sql` (and delete or keep locally).
- Add `postgres_dev.sql` to `.gitignore` if you want to keep generating snapshots locally without tracking.
