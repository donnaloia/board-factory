.PHONY: up down down-force down-nuclear logs shell rebuild clean protect-keys unprotect-keys test db-upgrade db-current db-stamp db-snapshot db-restore backfill-live-fk

# Compose labels use this project id (defaults to this repo directory name). Override if you use COMPOSE_PROJECT_NAME.
COMPOSE_LABEL_PROJECT ?= board-factory

up:
	docker compose up -d

# SIGKILL containers first: `docker compose down` alone can stall waiting on SIGTERM
# (uvicorn --reload, Postgres checkpointing, bind-mount sync on Docker Desktop).
# Then remove networks/containers with no extra graceful wait.
down:
	docker compose kill 2>/dev/null || true
	docker compose down --timeout 0 --remove-orphans

down-force: down

# When `docker compose` itself blocks talking to the engine, bypass Compose for teardown.
# Run from repo root. If this still hangs, restart Docker Desktop (daemon wedged).
down-nuclear:
	docker kill $$(docker ps -q --filter label=com.docker.compose.project=$(COMPOSE_LABEL_PROJECT)) 2>/dev/null || true
	docker rm -f $$(docker ps -aq --filter label=com.docker.compose.project=$(COMPOSE_LABEL_PROJECT)) 2>/dev/null || true
	@nets=$$(docker network ls -q -f name=$(COMPOSE_LABEL_PROJECT)_default); \
	  [ -z "$$nets" ] || docker network rm $$nets 2>/dev/null || true

logs:
	docker compose logs -f board-factory

# One-off shell inside the running board-factory container, useful for debugging
# the boardfactory pipeline against a real board on disk.
shell:
	docker compose exec board-factory bash

# Pull latest UI assets without a full image rebuild. Templates / static /
# python files are bind-mounted, so most edits land live; this only matters
# when you change requirements or the Dockerfile.
rebuild:
	docker compose build board-factory && docker compose up -d --force-recreate board-factory

clean:
	rm -rf data/boards/*/workspace/style/* \
	       data/boards/*/workspace/preview/* \
	       data/boards/*/workspace/logs/*

# Run once after editing docker-compose.yml with your API keys.
protect-keys:
	@git update-index --skip-worktree docker-compose.yml && \
	  echo "docker-compose.yml will now be ignored by git locally."

unprotect-keys:
	@git update-index --no-skip-worktree docker-compose.yml && \
	  echo "docker-compose.yml is back to normal git tracking."

# ── Tests ───────────────────────────────────────────────────────────────────
# Run the test suite inside the running board-factory container. The image must
# be up first (`make up`).
test:
	docker compose exec -T board-factory pip install --no-cache-dir -q -r /repo/app/requirements.txt
	docker compose exec -T board-factory sh -c 'cd /app && PYTHONPATH=/app:/repo/pipeline python -m pytest -q /repo/app/tests/'

# Apply Alembic migrations against the configured Postgres database.
# Safe to run repeatedly.
db-upgrade:
	docker compose exec -T board-factory sh -c 'cd /repo/app && alembic upgrade head'

# Reconcile ``workspace/history`` → ``asset_versions``, then attach NULL
# ``cells.live_asset_version_id`` to the newest version per cell. Idempotent.
backfill-live-fk:
	docker compose exec -T board-factory sh -c 'cd /app && PYTHONPATH=/app:/repo/pipeline python -c "\
from assets.repository import backfill_all_boards_with_catalog; \
from domains.cells.repository import backfill_live_asset_version_ids; \
backfill_all_boards_with_catalog(); \
print(backfill_live_asset_version_ids())"'

# Print which migration the DB is currently on.
db-current:
	docker compose exec -T board-factory sh -c 'cd /repo/app && alembic current'

# After squashing migrations: point alembic_version at the new baseline. We use
# psql instead of ``alembic stamp`` because Alembic refuses to run when the DB
# still references a deleted revision id (e.g. 0020_cells_live_asset_version).
db-stamp:
	docker compose exec -T postgres psql \
	  -U "$${POSTGRES_USER:-boardfactory}" \
	  -d "$${POSTGRES_DB:-boardfactory}" \
	  -v ON_ERROR_STOP=1 \
	  -c "UPDATE alembic_version SET version_num = '0001_full_schema';"

# ── Postgres snapshot (optional; see db/snapshots/README.md) ───────────────
# Plain-SQL dump for small dev DBs. Uses compose service `postgres`; override
# POSTGRES_USER / POSTGRES_DB if needed. --no-owner --no-acl improves portability.

SNAPSHOT_SQL ?= db/snapshots/postgres_dev.sql

db-snapshot:
	@mkdir -p db/snapshots
	docker compose exec -T postgres pg_dump \
	  -U "$${POSTGRES_USER:-boardfactory}" \
	  -d "$${POSTGRES_DB:-boardfactory}" \
	  --clean --if-exists --no-owner --no-acl \
	  > $(SNAPSHOT_SQL)
	@echo "Wrote $(SNAPSHOT_SQL) — review size and secrets before git add"

# Destructive: replays a committed snapshot into the running Postgres (dev only).
db-restore:
	@test -f $(SNAPSHOT_SQL) || (echo "Missing $(SNAPSHOT_SQL). Run make db-snapshot first." && exit 1)
	cat $(SNAPSHOT_SQL) | docker compose exec -T postgres psql \
	  -U "$${POSTGRES_USER:-boardfactory}" \
	  -d "$${POSTGRES_DB:-boardfactory}"
	@echo "Restore finished — consider: docker compose restart board-factory"
