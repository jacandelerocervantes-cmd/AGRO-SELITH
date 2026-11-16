FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock ./
COPY packages ./packages
RUN uv sync --frozen --no-dev --no-install-project

COPY apps/api ./apps/api
COPY pipelines ./pipelines
COPY knowledge ./knowledge
COPY config ./config
COPY scripts ./scripts
RUN uv sync --frozen --no-dev

ENV MILPA_DEMO=1 PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
# Migra la base y luego sirve la API. MILPA_SEED=1 siembra la base agronómica y los usuarios de prueba.
CMD ["sh", "-c", "cd apps/api && alembic upgrade head && cd /app && if [ \"$MILPA_SEED\" = \"1\" ]; then python apps/api/seed.py knowledge; fi && exec uvicorn milpa_api.main:app --app-dir apps/api --host 0.0.0.0 --port 8000"]
