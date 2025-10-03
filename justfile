install:
    uv sync --all-extras --group dev

lint:
    uv run ruff check --fix

format:
    uv run ruff format

local-api:
    uv run uvicorn vi_app.api.main:app --reload --host 127.0.0.1 --port 8000

launch-api-dev:
    docker compose --profile dev up --build -d

launch-api-prod:
    docker compose --profile prod up --build -d

down:
    docker stop $(docker ps -q) || true

clean:
    docker image prune -a -f
    docker volume prune -f
    docker network prune -f
    docker system prune -a --volumes -f

reset:
    #!/usr/bin/env bash
    set -euo pipefail
    dir="data/output"
    mkdir -p "$dir"
    find "$dir" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
