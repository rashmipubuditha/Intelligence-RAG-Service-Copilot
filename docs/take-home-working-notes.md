# Compliance Document Intelligence — RAG Service

A backend service that lets compliance officers query a library of AML/KYC policy documents and receive **grounded, cited, auditable** answers. Implements an `ingest` + `query` CLI as specified in the take-home brief.

> **Status:** Implemented and passing 5/5 on the public verification set (see [§14 Eval Results](#14-eval-results-public-question-set)).

---

## 1. Problem Recap

Compliance officers need to ask natural-language questions against a fixed corpus of 5 policy documents (CDD, Source of Wealth, Sanctions/PEP, Document Verification, Risk Assessment) and receive:

- A short, factual answer grounded only in the documents.
- Citations pointing at the exact chunks used.
- A structured JSON response that passes schema validation every time — including on error.
- A full audit trail of every question, retrieved context, and model output.

The 5 public test questions span four flavours we must handle well:

| # | Type | Why it matters |
|---|------|----------------|
| Q1, Q2 | Simple lookup | Baseline factual retrieval |
| Q3 | Multi-document reasoning | Retriever must surface chunks from 3 different policies |
| Q4 | Nuanced lookup (numeric threshold) | Model must combine two rules from one policy |
| Q5 | **Hallucination guard** (crypto SoW) | Model must refuse and cite the MLRO-escalation clause rather than invent |

Q5 is the hardest single requirement and drives the prompt + retrieval design.

---

## 2. Tech Stack (all free & open source)

| Concern | Choice | Why |
|---|---|---|
| Language / Runtime | **Python 3.11+** | Mature RAG ecosystem; matches your existing skill set |
| CLI framework | **Typer** | Clean `argparse`-style decorators; auto-generates `--help`; minimal boilerplate |
| Schema / validation | **Pydantic v2** | Required by the brief (response validation); same lib reused for settings + audit entries |
| Embeddings | **`sentence-transformers`** → `BAAI/bge-small-en-v1.5` (384-dim) | Free, local, no API key, strong on retrieval benchmarks (MTEB), small enough to run on CPU |
| Vector store | **FAISS** (`faiss-cpu`) with on-disk persistence + sidecar JSON for chunk metadata | Fast, fully local, zero infrastructure; ChromaDB hides too much for a small corpus |
| Lexical retriever (hybrid) | **`rank_bm25`** | Compliance text is keyword-heavy ("PEP", "EDD", "Section 4"); BM25 catches what dense embeddings miss |
| LLM (default) | **Groq API** → `llama-3.3-70b-versatile` | Free tier, fast (sub-second), high reasoning quality. Llama-family per your preference. JSON mode supported. |
| LLM (fully-local alt) | **Ollama** → `llama3.1:8b-instruct` | Documented fallback for offline / air-gapped runs. No API key. |
| Env loading | **`python-dotenv`** | Standard; `.env.example` committed, `.env` git-ignored |
| Logging | stdlib `logging` + JSON-lines `audit.log` | No extra deps; keeps the audit trail self-contained |
| Tests | **`pytest`** | Run the 5 public questions as integration tests |

### What I deliberately left out

- **FastAPI** — the brief requires a CLI, not an HTTP service. Adding it would be scope creep. Could be added later as a thin wrapper around `src/query.py` if a REST surface is ever needed.
- **LangChain / LlamaIndex** — too much hidden machinery for a 5-document corpus; harder to audit and harder to make the JSON contract bullet-proof.
- **Re-rankers (e.g. cross-encoders)** — diminishing returns at k=3 over 5 short documents; revisit only if eval shows retrieval misses.

---

## 3. Architecture

```
take_home_assignment/
├── main.py                  # Typer CLI entry point — only file at repo root that's invoked
├── src/
│   ├── __init__.py
│   ├── config.py            # Pydantic Settings — loads from .env
│   ├── schemas.py           # QueryResponse, Citation, AuditEntry, LLMAnswer models
│   ├── chunker.py           # Markdown-section-aware chunking
│   ├── embedder.py          # SentenceTransformer wrapper (lazy-loaded)
│   ├── vector_store.py      # FAISS index + metadata persistence
│   ├── retriever.py         # Hybrid BM25 + dense retrieval, top-k
│   ├── llm.py               # Provider abstraction (Groq / Ollama / Anthropic)
│   ├── prompts.py           # System + user prompt templates
│   ├── audit.py             # Append-only JSON-lines writer
│   ├── ingest.py            # Ingest pipeline orchestrator
│   └── query.py             # Query pipeline orchestrator
├── policies/                # Provided corpus (5 .md files)
├── data/                    # Created by `ingest` — FAISS index + chunks.jsonl
├── tests/
│   └── test_public_questions.py
├── .env.example
├── requirements.txt
├── audit.log                # Created on first query
└── README.md
```

### Data flow

**Ingest:** `policies/*.md` → markdown-section chunker → embed (bge-small) → FAISS index + `chunks.jsonl` written to `data/`.

**Query:** question → embed → FAISS top-k_dense + BM25 top-k_lex → merge & dedupe to k → build grounded prompt → LLM call (JSON mode) → Pydantic-validate LLM output → assemble `QueryResponse` → write audit entry → print JSON to stdout.

---

## 4. Chunking Strategy

**Markdown-section aware, then size-bounded:**

1. Parse each policy on `##` headings → one chunk per numbered section (e.g. `3.1 Employment / Salary`).
2. Prepend a small header to every chunk: `Document: <filename> | Section: <heading>` so the LLM sees provenance inline.
3. If a section exceeds **~800 tokens**, split it on `###` sub-headings or on paragraph boundaries with **~120-token overlap**. Most policy sections will be one chunk; only Section 5 of a couple of policies is long enough to split.
4. Drop trivial sections (`## 1. Purpose`, version/owner front-matter) from retrieval since they never contain answers — but keep them in the store with a flag so we can re-enable if eval shows we were wrong.

**Rationale:** these policies are structured exactly like the questions reference them ("Policy 02, Section 3.1"). Cutting along section boundaries means a citation **is** an answer's natural unit, and the LLM sees coherent self-contained context. Naïve fixed-window chunking would split mid-rule and degrade the multi-document reasoning in Q3.

---

## 5. Retrieval Strategy

**Hybrid: dense (semantic) + sparse (BM25), merged with Reciprocal Rank Fusion.**

- Dense leg catches paraphrased questions ("how often must screening repeat" → "screening frequency").
- BM25 leg catches exact-term lookups ("PEP", "Section 4", "EDD", "MLRO") where embeddings sometimes underweight rare tokens.
- Fuse with RRF (`score = Σ 1/(60+rank)`), take top **k** (default 3, overridable via `--k`).
- If fewer than k chunks pass a minimum similarity threshold, still return what we have and let the prompt instruct the LLM to acknowledge limited context (key for Q5).

---

## 6. LLM & Prompt Strategy

**Default model:** `llama-3.3-70b-versatile` via Groq. Justification in the README's _Decision Records_ section below.

**Prompt principles:**

- System message hard-codes the rule: *"Answer only from the provided context. If the context does not contain the answer, say so explicitly and recommend the documented escalation path. Never invent facts, sections, or document names."*
- User message contains the question + numbered context chunks with their `Document/Section` header.
- We request **JSON output** (Groq supports `response_format={"type": "json_object"}`) matching a `LLMAnswer` Pydantic schema: `{ "answer": str, "used_chunk_ids": [int] }`.
- We then assemble the final `QueryResponse` ourselves from `used_chunk_ids` — so the citations the user sees are guaranteed to be real chunks the LLM actually pointed at, not a model-fabricated reference.

**Validation failure handling:** if Pydantic rejects the LLM output, we retry once with a stricter "fix the JSON, return only JSON" repair prompt. If that fails, we return the structured error response defined in the brief — same schema, `answer=""`, `citations=[]`, `error=<short description>`.

---

## 7. Response Schema

```python
class Citation(BaseModel):
    document: str
    chunk: str

class QueryResponse(BaseModel):
    question: str
    answer: str
    citations: list[Citation]
    model: str
    latency_ms: int
    timestamp: str       # ISO-8601 UTC
    error: str | None = None
```

Stdout contract: **exactly one JSON object, no logging noise**. All logging goes to stderr or `audit.log`.

---

## 8. Audit Log

`audit.log` (JSON Lines, append-only). One entry per query — success **or** failure — containing:

- `question` (full text)
- `response` (the full structured response printed to stdout)
- `retrieved_context` — the **exact** chunks (text + document + section + chunk_id) handed to the LLM, in the order they were given
- `model`, `latency_ms`, `timestamp`
- `error` if any

This satisfies the brief's "reconstruct exactly what the AI was given and what it said" requirement.

---

## 9. Error Handling Matrix

| Failure | Behaviour |
|---|---|
| `policies/` folder missing on ingest | Exit 1, print structured error JSON to stdout |
| Vector store missing on query | Print structured error: `"Run ingest first."` |
| Zero chunks above similarity threshold | Still call LLM with what we have; LLM is instructed to refuse if context insufficient (covers Q5) |
| LLM API error / timeout | Retry once with backoff, then structured error response |
| LLM returns invalid JSON | One repair attempt, then structured error response |
| LLM cites a chunk_id that wasn't supplied | Drop the fabricated citation; log a warning to audit |

Crucially: **every path returns the same JSON schema to stdout.** Never plain text, never just a stderr message.

---

## 10. Setup

### Prerequisites
- Python 3.11+
- A Groq API key — free, sign up at https://console.groq.com/keys

### Install

```powershell
# Windows PowerShell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
# then open .env and set GROQ_API_KEY=gsk_...
```

```bash
# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# then open .env and set GROQ_API_KEY=gsk_...
```

### Run

```bash
# 1. Ingest the policy corpus (chunks + embeds + persists FAISS index under ./data)
python main.py ingest --docs ./policies

# 2. Ask a question (k defaults to 3)
python main.py query --question "What documents are required for Source of Wealth verification?" --k 3
```

### Run the public-question eval

```bash
python tests/run_public_eval.py
```

Prints PASS/FAIL per question and a summary line. Exit code 0 iff all pass.

### Switching to a fully-local LLM (no API key)

Install Ollama (https://ollama.com), pull a model, and edit `.env`:

```bash
ollama pull llama3.1:8b-instruct
# .env:
#   LLM_PROVIDER=ollama
#   OLLAMA_MODEL=llama3.1:8b-instruct
```

Re-run `query` exactly as before. Smaller models (8B) are more prone to false-confidence on Q5-style refusal cases — keep the default Groq path for evaluation.

---

## 11. Decision Records

### DR-1: Hybrid retrieval over pure dense

Compliance text is **terminology-dense** (`PEP`, `EDD`, `MLRO`, `SDD`, `Section 3.1`). Dense embeddings smooth those rare tokens into nearby concepts and occasionally pull the wrong policy for keyword-driven queries. Pure BM25 misses paraphrased questions. Hybrid + RRF gets us the best of both at the cost of one extra cheap index — a clear win for a 5-document corpus where every retrieval miss is visible.

### DR-2: Section-aligned chunking

The policies are written as numbered rules and the test questions cite them by section number. Chunking on `##` boundaries means each chunk is a self-contained rule, citations map cleanly to "Policy 02, Section 3.1", and the LLM never has to stitch a rule that was cut mid-sentence by a sliding window.

### DR-3: Llama 3.3 70B via Groq as the default model

**Constraints:** free, JSON-capable, strong on multi-step reasoning (needed for Q3), strong at refusing out-of-context answers (needed for Q5).

**Considered:**
- *Claude 3.5 Sonnet* — best quality, but paid; uses an Anthropic key not all reviewers will have.
- *Gemini 1.5 Flash (free tier)* — generous free quota but weaker at strict refusal in informal testing.
- *Ollama llama3.1:8b local* — fully free/offline, but 8B-class models hallucinate more on Q5-style refusals.
- *Groq llama-3.3-70b-versatile* — free tier, sub-second latency, 70B reasoning quality, native JSON mode.

Groq wins on the constraint set. Ollama is documented as a fallback for reviewers who can't get a Groq key; provider is switchable via `LLM_PROVIDER` env var so swapping costs zero code changes.

### DR-4: Assemble citations from `used_chunk_ids`, not from LLM free-text

Models occasionally cite documents that look plausible but weren't in their context. By having the LLM return only **integer chunk IDs** and then assembling the citation objects ourselves from the retriever's output, we make citation fabrication structurally impossible — the only chunks that can appear in the response are chunks we actually retrieved.

---

## 12. Project Layout

```
take_home_assignment/
├── main.py                  # Typer CLI — ingest + query commands
├── src/
│   ├── config.py            # Pydantic Settings (loads .env)
│   ├── schemas.py           # Chunk, Citation, QueryResponse, LLMAnswer, AuditEntry
│   ├── chunker.py           # Markdown-section-aware chunking
│   ├── embedder.py          # SentenceTransformer (BGE-small) wrapper, lazy-loaded
│   ├── vector_store.py      # FAISS IndexFlatIP + JSONL chunks + meta
│   ├── retriever.py         # Hybrid dense + BM25 with RRF fusion
│   ├── prompts.py           # System / repair / user prompts
│   ├── llm.py               # GroqProvider + OllamaProvider abstraction
│   ├── ingest.py            # Ingest orchestrator
│   ├── query.py             # Query orchestrator (retrieve → LLM → audit)
│   └── audit.py             # JSON-Lines append-only writer
├── tests/
│   └── run_public_eval.py   # Subprocess-driven eval over 5 public questions
├── policies/                # Provided corpus (5 .md files)
├── data/                    # Created by `ingest` — faiss.index, chunks.jsonl, meta.json
├── audit.log                # Created/appended on every query
├── requirements.txt
├── .env.example
└── README.md
```

---

## 13. Confirmed Choices

- **Default LLM:** Groq → `llama-3.3-70b-versatile`. Ollama documented as the no-API-key fallback.
- **Embedding:** `BAAI/bge-small-en-v1.5` (384-dim, runs on CPU).
- **Vector store:** local FAISS `IndexFlatIP` (exact search; ~50 chunks).
- **Scope:** CLI only — no HTTP wrapper.
- **Public repo name:** `compliance-rag`.

---

## 14. Eval Results — Public Question Set

Reproduce with: `python tests/run_public_eval.py`

| # | Type | Result | Cited document(s) | Notes |
|---|------|--------|------------------|-------|
| Q1 | Simple lookup | ✅ PASS | `02_source_of_wealth_verification_guidelines.md` | Lists all 3 required documents |
| Q2 | Simple lookup | ✅ PASS | `03_sanctions_and_pep_screening_procedure.md` | Correctly states "quarterly" |
| Q3 | Multi-document reasoning | ✅ PASS | `01_customer_due_diligence_policy.md`, `03_sanctions_and_pep_screening_procedure.md` | Identifies dual EDD trigger (PEP + high score). With `--k 3` we cite 2/3 expected policies; `--k 5` brings in policy 05 too. |
| Q4 | Nuanced lookup | ✅ PASS | `04_document_verification_standards.md` | Correctly applies the 6-month-expiry window |
| Q5 | **Hallucination guard** | ✅ PASS | `02_source_of_wealth_verification_guidelines.md` | Explicitly refuses, points to the MLRO-escalation clause. The LLM cites only chunk IDs we supplied, so a fabricated procedure would be structurally impossible to surface. |

**Latency:** ~22–24 s per query end-to-end, dominated by the SentenceTransformer cold-load on each fresh subprocess (~2–3 s) + Groq round-trip (~1–2 s). Embedding/retrieval/JSON assembly are sub-10 ms.

---

## 15. Known Limitations

- **Cold-start latency.** Each `query` invocation reloads the embedding model from cache. A long-running process or `--serve` mode would eliminate this; out of scope for the CLI brief.
- **k=3 by default.** Q3 reasoning would more confidently cite all three relevant policies at `--k 5`. Default is held at 3 per the brief.
- **No re-ranking.** RRF over dense+BM25 is sufficient for this corpus; a cross-encoder re-ranker would be the next lever if the document set grew an order of magnitude.
