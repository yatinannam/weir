FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"
WORKDIR /app
COPY services/weir/pyproject.toml services/weir/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY services/weir/src ./src
RUN uv sync --frozen --no-dev
COPY db/migrations /app/db/migrations
COPY configs /app/configs
EXPOSE 8000
CMD ["uvicorn", "weir.main:app", "--host", "0.0.0.0", "--port", "8000"]
