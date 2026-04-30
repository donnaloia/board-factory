.PHONY: up down logs shell rebuild clean protect-keys unprotect-keys

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f review-ui

# One-off shell inside the running review-ui container, useful for debugging
# the pipeline library against a real board on disk.
shell:
	docker compose exec review-ui bash

# Pull latest UI assets without a full image rebuild. Templates / static /
# python files are bind-mounted, so most edits land live; this only matters
# when you change requirements or the Dockerfile.
rebuild:
	docker compose build review-ui && docker compose up -d --force-recreate review-ui

clean:
	rm -rf boards/*/workspace/style/* \
	       boards/*/workspace/refinements/* \
	       boards/*/workspace/preview/* \
	       boards/*/workspace/logs/*

# Run once after editing docker-compose.yml with your API keys.
protect-keys:
	@git update-index --skip-worktree docker-compose.yml && \
	  echo "docker-compose.yml will now be ignored by git locally."

unprotect-keys:
	@git update-index --no-skip-worktree docker-compose.yml && \
	  echo "docker-compose.yml is back to normal git tracking."
