FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    EMBED_CACHE_DIR=/models/fastembed \
    HF_HOME=/models/hf
WORKDIR /app
COPY services/hospital-rag/pyproject.toml services/hospital-rag/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
# Bake the embedding model and tokenizer into the image so startup needs no download.
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='/models/fastembed'); from tokenizers import Tokenizer; Tokenizer.from_pretrained('BAAI/bge-small-en-v1.5')"
COPY services/hospital-rag/src ./src
RUN uv sync --frozen --no-dev
EXPOSE 8001
CMD ["uvicorn", "hospital_rag.main:app", "--host", "0.0.0.0", "--port", "8001"]
