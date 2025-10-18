default:
    just --list

ps:
    docker compose ps

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

cli:
    uv run vi --help

# -------------
# DEDUP
# -------------

cli-dedup:
    uv run vi dedup

# -------------
# CLEANUP
# -------------
# patterns: pass many like: patterns='-p "\.DS_Store$" -p "(?i)Thumbs\.db$"'
cli-cleanup-remove-files path="" patterns="" prune="true" option="plan":
    PRUNE_FLAG=$([ "{{prune}}" = "true" ] && echo --prune-empty || echo --no-prune-empty); \
    uv run vi cleanup remove-files "{{path}}" {{patterns}} ${PRUNE_FLAG} --{{option}}

# names: pass many like: names='-n duplicate -n tmp'
cli-cleanup-remove-folders path="" names="-n duplicate" option="plan":
    uv run vi cleanup remove-folders "{{path}}" {{names}} --{{option}}

# suffix is regex on the filename *stem*
cli-cleanup-find-marked-dupes path="" suffix="_dupe(\\d+)$":
    uv run vi cleanup find-marked-dupes "{{path}}" --suffix "{{suffix}}" --plan

# rename inside each (sub)directory to IMG_XXXXXX ordered by date taken
cli-cleanup-rename:
    uv run vi cleanup rename

# sort images by_date/by_location, mirroring into dst
cli-cleanup-sort src="" dst="" strategy="by_date" option="plan":
    uv run vi cleanup sort "{{src}}" --dst-root "{{dst}}" --strategy "{{strategy}}" --{{option}}

# -------------
# CONVERT
# -------------

convert-folder-to-jpeg:
    uv run vi convert folder-to-jpeg

convert-webp-to-jpeg:
    uv run vi convert webp-to-jpeg
