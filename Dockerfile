FROM node:22-bookworm-slim AS web
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /usr/local/bin/uv
WORKDIR /app
ENV PYTHONPATH=/app/backend PYTHONUNBUFFERED=1 UV_PYTHON_DOWNLOADS=never PATH="/app/.venv/bin:$PATH"
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project && useradd --system --uid 10001 appuser
COPY backend/ backend/
COPY migrations/ migrations/
COPY alembic.ini ./
COPY --from=web /build/frontend/dist/ frontend/dist/
USER appuser
EXPOSE 8000
CMD ["python", "-m", "serentable.server"]
