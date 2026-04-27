SERVICE ?= boardfactory-cli

HOST_DIRS := mockup catalog board_assets \
             workspace/style workspace/candidates workspace/cleaned \
             workspace/approved workspace/refinements workspace/preview workspace/logs

.PHONY: _dirs up down logs shell run style catalog generate cleanup \
        states preview export clean protect-keys unprotect-keys

_dirs:
	@mkdir -p $(HOST_DIRS)

up: | _dirs
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

shell: | _dirs
	docker compose run --rm $(SERVICE) bash

run: | _dirs
	docker compose run --rm $(SERVICE) boardfactory run

style: | _dirs
	docker compose run --rm $(SERVICE) boardfactory style

catalog: | _dirs
	docker compose run --rm $(SERVICE) boardfactory catalog

generate: | _dirs
	docker compose run --rm $(SERVICE) boardfactory generate

cleanup: | _dirs
	docker compose run --rm $(SERVICE) boardfactory cleanup

states: | _dirs
	docker compose run --rm $(SERVICE) boardfactory states

preview: | _dirs
	docker compose run --rm $(SERVICE) boardfactory preview

export: | _dirs
	docker compose run --rm $(SERVICE) boardfactory export

clean:
	rm -rf workspace/style/* workspace/candidates/* workspace/cleaned/* \
	       workspace/approved/* workspace/refinements/* workspace/preview/* workspace/logs/*

# Run once after editing docker-compose.yml with your API keys.
protect-keys:
	@git update-index --skip-worktree docker-compose.yml && \
	  echo "✓ docker-compose.yml will now be ignored by git locally."

unprotect-keys:
	@git update-index --no-skip-worktree docker-compose.yml && \
	  echo "✓ docker-compose.yml is back to normal git tracking."
