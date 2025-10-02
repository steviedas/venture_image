# syntax=docker/dockerfile:1.7

# Base: Python 3.12 with uv
FROM ghcr.io/astral-sh/uv:python3.12-bookworm

# Keep Python lean & chatty
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_SYSTEM_PYTHON=1

WORKDIR /app

# --- Layer 1: project metadata + lockfile (maximizes cache) ---
# Hatchling needs README.md because pyproject declares `readme = "README.md"`
COPY pyproject.toml README.md uv.lock* ./

# Install deps (prefer frozen if uv.lock exists)
RUN uv sync --no-dev --frozen || uv sync --no-dev

# --- Layer 2: source code + project install (editable for entry points) ---
COPY src ./src

# Register entry points inside the environment
RUN uv pip install -e .

# --- Runtime defaults (env can be overridden in compose) ---
ENV PORT=8000 \
    VI_INPUT_ROOT=/data/input \
    VI_OUTPUT_ROOT=/data/output \
    VI_DEBUG=false

# Data dirs (bind-mounted in docker-compose)
RUN mkdir -p /data/input /data/output

EXPOSE 8000

# Start FastAPI via uvicorn
CMD ["uv", "run", "uvicorn", "vi_app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
