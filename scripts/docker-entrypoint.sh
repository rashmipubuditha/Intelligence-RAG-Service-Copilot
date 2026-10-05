#!/usr/bin/env bash
# =============================================================================
# Backend container entrypoint.
#
# Seeds the sample corpus on first boot so `docker compose up` produces a
# working demo rather than an empty index with a 503 on every question.
#
# Idempotent by design: seeding is skipped when chunks already exist, so a
# restart against an existing volume is fast and does not re-ingest. Set
# SEED_CORPUS=false to start empty (the right choice when mounting a real
# corpus), or SEED_CORPUS=force to re-ingest regardless.
# =============================================================================
set -euo pipefail

SEED_CORPUS="${SEED_CORPUS:-true}"
SEED_DOCS="${SEED_DOCS:-/app/policies}"

log() { printf '{"event":"entrypoint","message":"%s"}\n' "$1" >&2; }

if [ "${SEED_CORPUS}" != "false" ]; then
  # Ask the application itself whether anything is indexed — this also creates
  # the database and applies migrations, so the first query never races them.
  indexed="$(python - <<'PY'
import sys
sys.path.insert(0, "/app/backend")
try:
    from app.container import AppContainer

    container = AppContainer()
    print(container.chunks.count())
    container.db.close()
except Exception as exc:  # a broken store must not block start-up silently
    print(f"error:{exc}", file=sys.stderr)
    print(-1)
PY
)"

  if [ "${indexed}" = "-1" ]; then
    log "could not read the chunk count; starting without seeding"
  elif [ "${SEED_CORPUS}" = "force" ] || [ "${indexed}" = "0" ]; then
    if [ -d "${SEED_DOCS}" ]; then
      log "indexing sample corpus from ${SEED_DOCS} (currently ${indexed} chunks)"
      # Failure here is non-fatal: the API should still start and report
      # index_not_ready rather than crash-looping.
      if python /app/main.py ingest --docs "${SEED_DOCS}" >/dev/null; then
        log "corpus indexed"
      else
        log "seeding failed; the API will start and report index_not_ready"
      fi
    else
      log "seed directory ${SEED_DOCS} not found; skipping"
    fi
  else
    log "${indexed} chunks already indexed; skipping seed"
  fi
else
  log "SEED_CORPUS=false; starting with whatever is on the volume"
fi

log "starting: $*"
exec "$@"
