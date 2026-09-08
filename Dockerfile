# syntax=docker/dockerfile:1

FROM node:24-alpine AS frontend-builder

WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci
COPY frontend ./
RUN npm run build

FROM python:3.12.14-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.12.10 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home app

COPY pyproject.toml uv.lock README.md ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

COPY src ./src
COPY alembic.ini ./
COPY alembic ./alembic
COPY scripts/seed_data.py ./scripts/seed_data.py
COPY knowledge ./knowledge
COPY --from=frontend-builder /web/dist ./frontend/dist

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev \
    && chown -R app:app /app

USER app

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && python scripts/seed_data.py && exec uvicorn ecommerce_ai_agent.main:create_app --factory --host 0.0.0.0 --port 8000"]
