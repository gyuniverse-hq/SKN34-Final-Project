FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.13 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY . .

FROM python:3.12-slim
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app
WORKDIR /app
COPY --from=build --chown=10001:10001 /app /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER 10001
EXPOSE 8000
# PORT is set by Render; Kubernetes and Compose use 8000. RUN_MIGRATIONS=true is for hosts without a
# separate migration step (Render free plan); Kubernetes uses an initContainer, Compose a migrate service.
CMD ["sh", "-c", "if [ \"$RUN_MIGRATIONS\" = true ]; then alembic upgrade head; fi && exec uvicorn app.main:app --host 0.0.0.0 --port \"${PORT:-8000}\" --proxy-headers --forwarded-allow-ips '*'"]
