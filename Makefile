.PHONY: help install ingest serve query test test-all lint format eval eval-full
.PHONY: eval-sweep rebuild clean doc docker-build docker-up docker-dev docker-down
.PHONY: docker-logs docker-shell docker-test docker-eval docker-reset

PY ?= python

help:
	@echo "install     Install runtime + dev dependencies"
	@echo "ingest      Index ./policies"
	@echo "serve       Run the API (http://127.0.0.1:8000/docs)"
	@echo "query       Ask one question (Q=\"...\")"
	@echo "test        Fast suite — no network, no API key"
	@echo "test-all    Include slow/live tests"
	@echo "lint        ruff check + format check"
	@echo "format      Apply ruff formatting"
	@echo "eval        Retrieval-only evaluation (deterministic, offline)"
	@echo "eval-full   Full evaluation incl. generation metrics (needs an LLM)"
	@echo "eval-sweep  Compare reranking on/off"
	@echo "rebuild     Rebuild FAISS + BM25 from the chunk registry"
	@echo "clean       Remove the local index, database and reports"
	@echo ""
	@echo "docker-build  Build both images"
	@echo "docker-up     Production shape: nginx + API (http://localhost:3000)"
	@echo "docker-dev    Dev shape: Vite HMR + uvicorn --reload"
	@echo "docker-down   Stop containers (the data volume is kept)"
	@echo "docker-logs   Follow logs from both services"
	@echo "docker-shell  Shell into the running backend container"
	@echo "docker-test   Run the backend test suite inside the container"
	@echo "docker-eval   Run retrieval-only evaluation inside the container"
	@echo "docker-reset  Stop and DESTROY the data volume (corpus + audit log)"
	@echo ""
	@echo "doc           Regenerate and verify the technical reference document"

install:
	$(PY) -m pip install -r requirements-dev.txt

ingest:
	$(PY) main.py ingest --docs ./policies

serve:
	$(PY) main.py serve --reload

query:
	$(PY) main.py query --question "$(or $(Q),What documents are required for customer due diligence?)" --k 5

test:
	$(PY) -m pytest tests -q

test-all:
	$(PY) -m pytest tests -q -m "slow or live or not slow"

lint:
	$(PY) -m ruff check backend eval tests main.py
	$(PY) -m ruff format --check backend eval tests main.py

format:
	$(PY) -m ruff format backend eval tests main.py
	$(PY) -m ruff check --fix backend eval tests main.py

eval:
	$(PY) -m eval.run --mode retrieval_only

eval-full:
	$(PY) -m eval.run --mode full --judge

eval-sweep:
	@echo "--- RRF only (baseline) ---"
	@$(PY) -m eval.run --mode retrieval_only --rerank false --quiet | grep -E "^\| (recall@[15]|precision@3|mrr|ndcg@5)"
	@echo "--- with cross-encoder rerank ---"
	@$(PY) -m eval.run --mode retrieval_only --rerank true --quiet | grep -E "^\| (recall@[15]|precision@3|mrr|ndcg@5)"

rebuild:
	$(PY) main.py rebuild-index

clean:
	rm -rf data/index data/app.db data/uploads eval/reports/*.json eval/reports/*.md
	@echo "Removed index, database and reports. Re-run 'make ingest'."

# --- docker -----------------------------------------------------------------
# `docker compose up` applies docker-compose.override.yml automatically, so the
# production shape must name the base file explicitly.

docker-build:
	docker compose -f docker-compose.yml build

docker-up:
	docker compose -f docker-compose.yml up --build -d
	@echo ""
	@echo "UI:   http://localhost:3000"
	@echo "API:  http://localhost:8000/api/health"
	@echo "Docs: http://localhost:8000/docs"
	@echo ""
	@echo "First boot indexes the sample corpus; follow it with: make docker-logs"

docker-dev:
	docker compose up --build

docker-down:
	docker compose -f docker-compose.yml down

docker-logs:
	docker compose -f docker-compose.yml logs -f --tail=80

docker-shell:
	docker compose -f docker-compose.yml exec backend sh

docker-test:
	docker compose -f docker-compose.yml exec -w /app backend python -m pytest tests -q

docker-eval:
	docker compose -f docker-compose.yml exec -w /app backend python -m eval.run --mode retrieval_only --quiet

# Destroys the corpus AND the audit trail. Never the default for that reason.
docker-reset:
	docker compose -f docker-compose.yml down -v

# --- documentation ----------------------------------------------------------
doc:
	$(PY) scripts/generate_project_doc.py
	$(PY) scripts/verify_project_doc.py
