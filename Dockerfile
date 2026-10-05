# syntax=docker/dockerfile:1
# =============================================================================
# Single-container image for Hugging Face Spaces (Docker SDK).
#
# A Space runs exactly one container on one port, so this image folds the two
# Compose services into one: the frontend is compiled here and FastAPI serves
# it (STATIC_DIR), which replaces nginx. Local development and the Compose stack
# keep using backend/Dockerfile and frontend/Dockerfile — when the Python build
# steps change there, mirror them here.
#
# What the Space runtime dictates:
#   * port 7860
#   * the container runs as uid 1000
#   * the disk is wiped on every restart, so the entrypoint re-seeds the sample
#     corpus on each boot and nothing uploaded at runtime is durable
#
# Secrets (Space settings → Variables and secrets): GROQ_API_KEY, API_KEY.
# =============================================================================

# -----------------------------------------------------------------------------
# Stage 1 — compile the frontend
# -----------------------------------------------------------------------------
FROM node:22-alpine AS frontend

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# -----------------------------------------------------------------------------
# Stage 2 — Python dependencies (CPU-only torch first; see backend/Dockerfile)
# -----------------------------------------------------------------------------
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN pip install --upgrade pip \
    && pip install --index-url https://download.pytorch.org/whl/cpu torch

COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

# -----------------------------------------------------------------------------
# Stage 3 — bake model weights so the Space starts without downloading them
# -----------------------------------------------------------------------------
FROM builder AS models

ENV HF_HOME=/opt/hf \
    HF_HUB_DISABLE_PROGRESS_BARS=1 \
    HF_HUB_DISABLE_TELEMETRY=1

# Retried because a dropped hub connection would otherwise fail the whole build;
# files already fetched stay in the cache, so each attempt resumes.
RUN python - <<'PY'
import time

from sentence_transformers import CrossEncoder, SentenceTransformer

for attempt in range(1, 6):
    try:
        SentenceTransformer("BAAI/bge-small-en-v1.5").encode(["warm up"])
        CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2").predict([("warm", "up")])
        break
    except Exception as exc:
        if attempt == 5:
            raise
        print(f"model download attempt {attempt} failed: {exc!r}; retrying", flush=True)
        time.sleep(10)
PY

# -----------------------------------------------------------------------------
# Stage 4 — runtime
# -----------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

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
    STATIC_DIR=/app/static \
    LOG_FORMAT=json \
    # Anyone may ask questions and browse; uploads, deletes and settings need
    # API_KEY. If the API_KEY secret is missing, nobody can write.
    PUBLIC_READ=true \
    # The Space page embeds the app in an iframe on huggingface.co.
    FRAME_ANCESTORS=https://huggingface.co

COPY --from=builder /opt/venv /opt/venv
COPY --from=models /opt/hf /opt/hf

# Spaces run the container as uid 1000.
RUN useradd --create-home --uid 1000 user

WORKDIR /app

COPY --chown=user:user backend ./backend
COPY --chown=user:user eval ./eval
COPY --chown=user:user policies ./policies
COPY --chown=user:user main.py ./main.py
COPY --chown=user:user --from=frontend /app/dist ./static
COPY --chown=user:user scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# Source maps are a debugging aid; they have no place on a public demo.
RUN mkdir -p /app/data/index /app/data/uploads \
    && chown -R user:user /app/data \
    && chown user:user /app \
    && find /app/static -name '*.map' -delete \
    && sed -i 's/\r$//' /usr/local/bin/docker-entrypoint.sh \
    && chmod +x /usr/local/bin/docker-entrypoint.sh

USER user

EXPOSE 7860

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["python", "/app/main.py", "serve", "--host", "0.0.0.0", "--port", "7860"]
