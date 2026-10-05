# syntax=docker/dockerfile:1
# =============================================================================
# Backend image — FastAPI + FAISS + sentence-transformers
#
# Two decisions dominate this file:
#
# 1. CPU-only PyTorch. The default torch wheel on PyPI bundles CUDA and weighs
#    ~2.5 GB. Installing from PyTorch's CPU index first means pip keeps that
#    build when sentence-transformers later declares torch as a dependency,
#    which removes roughly 2 GB from the image for a service that never touches
#    a GPU.
#
# 2. Model weights are baked into the image at build time (~220 MB for
#    bge-small plus the cross-encoder). The container therefore starts with no
#    network access and no user request ever pays a download. This matters
#    concretely: the cross-encoder cold load was measured at 10.8 s, and that
#    must never land on a first query.
#
# The result is a larger image that starts fast and runs offline, which is the
# right trade for a demo someone clicks once.
# =============================================================================

# -----------------------------------------------------------------------------
# Stage 1 — build dependencies into a self-contained virtualenv
# -----------------------------------------------------------------------------
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

# build-essential is needed by a few wheels; it stays in the builder stage only.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# CPU torch FIRST, from PyTorch's CPU index. Order matters: install it after
# requirements.txt and pip will already have resolved the CUDA build.
RUN pip install --upgrade pip \
    && pip install --index-url https://download.pytorch.org/whl/cpu torch

# requirements-dev.txt includes requirements.txt and adds pytest, so the image
# can run its own suite (`make docker-test`). That costs a few tens of MB and
# buys a test run against the exact interpreter and wheels that ship.
COPY requirements.txt requirements-dev.txt /tmp/
RUN pip install -r /tmp/requirements-dev.txt

# -----------------------------------------------------------------------------
# Stage 2 — download model weights into the HuggingFace cache
# -----------------------------------------------------------------------------
FROM builder AS models

ENV PATH="/opt/venv/bin:$PATH" \
    HF_HOME=/opt/hf \
    HF_HUB_DISABLE_PROGRESS_BARS=1 \
    HF_HUB_DISABLE_TELEMETRY=1

# Pinned by name; the digest is whatever the hub serves at build time. Pass
# --build-arg EMBEDDING_MODEL=... to bake a different model.
#
# ARG values are not visible to processes inside RUN, so they are promoted to ENV
# — otherwise the override would be silently ignored and the default baked.
ARG EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
ARG RERANK_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2
ENV EMBEDDING_MODEL=${EMBEDDING_MODEL}
ENV RERANK_MODEL=${RERANK_MODEL}

RUN python - <<'PY'
import os
from sentence_transformers import CrossEncoder, SentenceTransformer

embedding = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
rerank = os.environ.get("RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")

# Encoding once forces the full download rather than just the config.
SentenceTransformer(embedding).encode(["warm up"])
CrossEncoder(rerank).predict([("warm", "up")])
print("baked:", embedding, "and", rerank)
PY

# -----------------------------------------------------------------------------
# Stage 3 — runtime
# -----------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

LABEL org.opencontainers.image.title="Compliance Intelligence Copilot — API" \
      org.opencontainers.image.description="Grounded, citation-backed RAG over AML/KYC compliance documents" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    HF_HOME=/opt/hf \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    TRANSFORMERS_VERBOSITY=error \
    HF_HUB_DISABLE_PROGRESS_BARS=1 \
    TOKENIZERS_PARALLELISM=false \
    DATA_DIR=/app/data \
    AUDIT_LOG_PATH=/app/data/audit.log \
    LOG_FORMAT=json

# curl is the only runtime addition, used by HEALTHCHECK.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
COPY --from=models /opt/hf /opt/hf

# Non-root. Created before the data directory so a fresh named volume mounted at
# /app/data inherits this ownership from the image.
RUN useradd --create-home --shell /usr/sbin/nologin --uid 10001 appuser

WORKDIR /app

COPY --chown=appuser:appuser backend ./backend
COPY --chown=appuser:appuser eval ./eval
COPY --chown=appuser:appuser policies ./policies
COPY --chown=appuser:appuser main.py ./main.py
# tests/ and pyproject.toml are included so the image can verify itself:
# `make docker-test` runs the real suite inside the container. pyproject.toml
# also carries the pytest pythonpath configuration the suite depends on.
COPY --chown=appuser:appuser tests ./tests
COPY --chown=appuser:appuser pyproject.toml ./pyproject.toml
COPY --chown=appuser:appuser scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# sed strips carriage returns: a Windows checkout with core.autocrlf would
# otherwise ship a "bash\r" shebang that fails with "no such file or directory".
RUN mkdir -p /app/data/index /app/data/uploads \
    && chown appuser:appuser /app \
    && chown -R appuser:appuser /app/data \
    && sed -i 's/\r$//' /usr/local/bin/docker-entrypoint.sh \
    && chmod +x /usr/local/bin/docker-entrypoint.sh

USER appuser

EXPOSE 8000

# Liveness, not readiness: a readiness probe that fails while the corpus is
# empty would make the container restart, which does not index anything.
HEALTHCHECK --interval=15s --timeout=5s --start-period=90s --retries=4 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
# Started through main.py rather than the uvicorn CLI: `serve` passes
# log_config=None so structlog owns the log format, and the CLI has no way to
# express that (`--log-config /dev/null` raises "is an empty file" at start-up).
CMD ["python", "/app/main.py", "serve", "--host", "0.0.0.0", "--port", "8000"]
