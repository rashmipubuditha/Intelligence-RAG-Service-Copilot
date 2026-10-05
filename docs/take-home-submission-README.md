# Compliance Document Intelligence — RAG Service

A local Retrieval-Augmented Generation (RAG) service for AML/KYC compliance documents. A compliance officer asks a natural-language question, the system retrieves the most relevant policy sections, and an LLM produces a grounded answer with verifiable citations. Every query is recorded in an append-only audit log.

**Status:** Implemented and passing 5/5 on the public verification question set.

---

## Table of Contents

1. [Setup](#1-setup)
2. [Usage](#2-usage)
3. [Architecture Overview](#3-architecture-overview)
4. [What I Built — Step by Step](#4-what-i-built--step-by-step)
5. [Decision Records](#5-decision-records)
6. [Eval Results](#6-eval-results)
7. [Project Layout](#7-project-layout)
8. [Error Handling](#8-error-handling)
9. [Known Limitations](#9-known-limitations)

---

## 1. Setup

### Prerequisites

- Python 3.11 or newer
- A free Groq API key from https://console.groq.com/keys

### Install (Windows / PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
# open .env in any editor and paste your key: GROQ_API_KEY=gsk_...
```

### Install (macOS / Linux)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# open .env in any editor and paste your key: GROQ_API_KEY=gsk_...
```

That is the entire setup. No database, no Docker, no cloud account beyond the free Groq key.

---

## 2. Usage

### Step 1 — Ingest the policy corpus (run once)

```bash
python main.py ingest --docs ./policies
```

Reads every `.md` file under `./policies`, chunks them, embeds them with a local SentenceTransformer model, and writes a FAISS index plus chunk metadata to `./data/`. Prints a JSON summary of what was indexed.

### Step 2 — Ask a compliance question

```bash
python main.py query --question "What documents are required for Source of Wealth verification when wealth comes from employment income?" --k 3
```

`--k` controls how many chunks are retrieved (defaults to 3 if omitted).

Output is a single JSON object printed to stdout, matching this schema:

```json
{
  "question": "...",
  "answer": "...",
  "citations": [
    {
      "document": "02_source_of_wealth_verification_guidelines.md",
      "chunk": "..."
    }
  ],
  "model": "llama-3.3-70b-versatile",
  "latency_ms": 22414,
  "timestamp": "2026-05-16T08:14:09Z",
  "error": null
}
```

### Step 3 — Run the eval over the 5 public test questions

```bash
python tests/run_public_eval.py
```

Reports PASS / FAIL per question and prints a summary. Exit code 0 if all pass.

### Optional — Fully offline mode with Ollama (no API key)

```bash
# Install Ollama from https://ollama.com, then:
ollama pull llama3.1:8b-instruct
# In .env, change:
#   LLM_PROVIDER=ollama
#   OLLAMA_MODEL=llama3.1:8b-instruct
```

Re-run `query` exactly as before. Smaller local models are more prone to false-confidence on the Q5 refusal case; keep the default Groq path for evaluation.

---

## 3. Architecture Overview

The service is a Python CLI with two commands. Both share the same underlying components.

### Ingest pipeline (run once)

```
policies/*.md
     |
     v
[chunker]   split each policy on `## ` headings, sub-split if too long
     |
     v
[embedder]  encode each chunk with BGE-small (384-dim vectors)
     |
     v
[vector_store]  FAISS IndexFlatIP + chunks.jsonl + meta.json saved to ./data/
```

### Query pipeline (every question)

```
question
     |
     v
[retriever]  dense search (FAISS) + sparse search (BM25), fused via RRF, top k
     |
     v
[prompts]    build SYSTEM + USER prompt with numbered chunks
     |
     v
[llm]        Groq Llama 3.3 70B in JSON mode (or Ollama)
     |
     v
[query]      validate LLMAnswer schema, repair-retry once if invalid,
             drop fabricated chunk IDs, assemble Citation objects
     |
     v
[audit]      append one JSON-Lines entry to audit.log
     |
     v
stdout       single JSON object matching the response schema
```

### Key technical choices (full justifications in §5)

| Concern        | Choice                                                                |
| -------------- | --------------------------------------------------------------------- |
| CLI framework  | Typer                                                                 |
| Validation     | Pydantic v2 (response + LLM output + audit entries)                   |
| Embeddings     | `BAAI/bge-small-en-v1.5` via sentence-transformers (local, CPU, free) |
| Vector store   | FAISS IndexFlatIP, persisted to disk                                  |
| Retrieval      | Hybrid dense + BM25, fused with Reciprocal Rank Fusion                |
| LLM (default)  | Groq → `llama-3.3-70b-versatile`                                      |
| LLM (fallback) | Ollama → `llama3.1:8b-instruct` (offline)                             |
| Audit          | JSON Lines, append-only                                               |

---

## 4. What I Built — Step by Step

I built the project in six milestones, each adding a layer to the system.

### Milestone 1 — Project scaffolding and schemas

Created the directory layout, `requirements.txt`, `.env.example`, and the Pydantic schemas in `src/schemas.py` for `Chunk`, `RetrievedChunk`, `Citation`, `QueryResponse`, `LLMAnswer`, and `AuditEntry`. Wrote `src/config.py` to load all settings from `.env` via pydantic-settings. The settings layer makes the LLM provider switchable (Groq ↔ Ollama) without any code change.

### Milestone 2 — Ingest path (chunker → embedder → vector store)

Built three components:

- `src/chunker.py` splits each policy on `## ` headings. Sections that exceed roughly 300 words are further split on `### ` sub-headings, and if that's not possible, on paragraph boundaries with a 60-word overlap. Every chunk gets a header line prepended: `Document: <filename> | Section: <heading>`, so when the LLM sees the chunk later it also sees the provenance.
- `src/embedder.py` is a thin lazy-loaded wrapper around `BAAI/bge-small-en-v1.5`. The model is downloaded once (cached by HuggingFace), runs entirely on CPU, and returns L2-normalized float32 vectors.
- `src/vector_store.py` wraps a FAISS `IndexFlatIP`. Persistence is three files: `faiss.index` (binary), `chunks.jsonl` (one chunk per line, in the same order as the FAISS rows), and `meta.json` (dimension and count, validated on load).
- `src/ingest.py` is a small orchestrator that wires those three together into a single `run_ingest()` function.

Verified the chunker against the actual policies before integrating it: 5 documents produce 46 chunks, with the two oversize sections (Policy 02 §3 and Policy 05 §3) correctly sub-split on their `###` sub-headings.

### Milestone 3 — Hybrid retriever

`src/retriever.py` runs two retrievers in parallel:

- Dense: embed the question and ask FAISS for the 20 most similar chunks by cosine similarity.
- Sparse: run BM25 (via `rank_bm25`) over the same chunks and take the top 20.

Their raw scores live on different scales and can't be added directly, so the two ranked lists are fused using Reciprocal Rank Fusion: `score = sum over each list of 1 / (60 + rank)`. The fused top k (default 3) is returned.

The decision to go hybrid was a direct response to the test questions. Compliance text is terminology-dense (PEP, EDD, MLRO, "Section 4"). Pure dense retrieval smooths rare tokens into adjacent concepts; pure BM25 misses paraphrased questions. RRF gives both legs without having to calibrate raw scores.

### Milestone 4 — LLM and prompts

- `src/prompts.py` defines the SYSTEM prompt (grounding rules + refusal rules + JSON output instruction), a REPAIR prompt (used as a second attempt if the LLM returns broken JSON), and a `build_user_prompt()` function that formats the retrieved chunks with `[CHUNK <id>]` markers.
- `src/llm.py` defines an abstract `LLMProvider` with two concrete implementations: `GroqProvider` (default, uses Groq's native JSON mode) and `OllamaProvider` (POSTs to a local Ollama server using its `format: "json"` option). A `build_provider()` factory picks the right one based on `LLM_PROVIDER` in the env.

The prompt is the project's main lever against hallucination. It tells the LLM explicitly to refuse if the answer isn't in the context, and to recommend the documented escalation path (typically: escalate to the MLRO).

### Milestone 5 — Query orchestrator, audit log, CLI

- `src/query.py` is the heart of the project. It loads the vector store, retrieves the top k, builds the prompt, calls the LLM with one repair-retry on validation failure, drops any chunk IDs the LLM fabricated, assembles `Citation` objects from the surviving IDs, writes an audit entry, and returns a `QueryResponse`. Every code path — including every failure path — returns the same schema.
- `src/audit.py` is a one-function module that appends an `AuditEntry` to `audit.log` as JSON Lines. Append-only by design; an audit log you can rewrite is not an audit log.
- `main.py` is the Typer CLI exposing the two commands. It silences HuggingFace warnings at import time so stdout stays clean, and wraps everything in a last-resort try/except so even an unhandled exception still produces a valid JSON response on stdout.

### Milestone 6 — Eval

`tests/run_public_eval.py` invokes `main.py query ...` as a subprocess for each of the 5 public test questions and asserts:

- stdout is valid JSON matching the schema,
- the citation includes the expected primary-source document,
- the answer contains the expected keywords,
- for Q5 specifically, the answer contains a refusal / escalation signal (`MLRO`, `escalate`, `not covered`, etc.).

All 5 pass.

---

## 5. Decision Records

The brief asks for at least one decision record; here are the four substantive non-trivial choices made and why.

### DR-1: Hybrid retrieval (dense + BM25) over pure dense

**Choice.** The retriever runs both a dense (semantic) search via FAISS and a sparse (keyword) search via BM25, then fuses the two ranked lists with Reciprocal Rank Fusion.

**Why:** Compliance documents use special terminology (PEP, EDD, MLRO, etc.) that are rare but important.

- If I only searched by meaning (semantic search), the system might confuse these special terms with similar concepts and find the wrong policy.
- If I only searched by exact keywords (BM25), I'd miss questions that use different words but mean the same thing (e.g., "how often must we screen?" vs "frequency of checks").
- By combining both approaches, I get the best of both worlds. The two ranked lists are merged using a simple math formula that doesn't require me to tune different score systems against each other.

### DR-2: Split documents by section, not by arbitrary word count

**What I chose:** Break each policy document at the section headings (`## ` and `### `), rather than cutting every 500 characters regardless of content.

**Why:** Policies are written as numbered rules ("Policy 02, Section 3.1"), and people ask questions referencing those sections. If I cut a rule into pieces, the system would have to reassemble it, which is messy and error-prone. By respecting section boundaries, each piece is a complete rule—it makes sense on its own, and the citation I show to the user is exactly what they expect to read.

- Some sections are longer than ideal, so I split the really long ones (over ~300 words) at sub-headings or paragraph breaks to keep pieces manageable.
- This keeps citations clean and trustworthy.

### DR-3: Groq Llama 3.3 70B as the default LLM

**What I chose:** Use Groq's free API to run the Llama 3.3 70B language model as the main AI engine. Optionally allow Ollama (a local, offline model) as a fallback.

**Why:** The language model needs to:

1. **Be free** – For the assignment I choosed a free option
2. **Reason through complex scenarios** – like Q3 which requires checking multiple policies together
3. **Know when to say "I don't know"** – like Q5, where cryptocurrency isn't covered in the policies (it shouldn't make up an answer)
4. **Output clean, structured answers** – so the system doesn't waste time parsing messy text

I considered other options:

- Claude 3.5 Sonnet: Great quality but costs money and requires an API key reviewers might not have
- Gemini Flash: Free but showed weaker refusal patterns in testing
- Local Ollama: Fully offline but smaller models tend to hallucinate more

Groq hits all four requirements, is fast, and is easy to swap for another provider just by changing one environment variable.

### DR-4: Citations assembled from chunk IDs, not from LLM free text

**Choice.** The LLM is asked to return a JSON object containing only `{"answer": "...", "used_chunk_ids": [<ints>]}`. The code then assembles each `Citation` by looking up those integer IDs against the chunks the retriever actually returned. Any chunk ID the LLM produces that wasn't in the retrieved set is discarded and a warning is written to stderr.

**Why.** Free-form LLM-authored citations are the single biggest hallucination risk in a compliance product. Models will occasionally cite a confident-looking section that doesn't exist or quote text that was never in the context. By making the LLM hand us only integer IDs, fabricated citations become structurally impossible — the only chunks that can survive into the final response are chunks the retriever actually produced from the indexed data. This is what gives the audit log its real value: every cited chunk in the response can be traced back to a row in `chunks.jsonl`.

---

## 6. Eval Results

Reproduce with: `python tests/run_public_eval.py`

| #   | Type                     | Result  | Cited document(s)                                                                    |
| --- | ------------------------ | ------- | ------------------------------------------------------------------------------------ |
| Q1  | Simple lookup            | ✅ PASS | `02_source_of_wealth_verification_guidelines.md`                                     |
| Q2  | Simple lookup            | ✅ PASS | `03_sanctions_and_pep_screening_procedure.md`                                        |
| Q3  | Multi-document reasoning | ✅ PASS | `01_customer_due_diligence_policy.md`, `03_sanctions_and_pep_screening_procedure.md` |
| Q4  | Nuanced lookup           | ✅ PASS | `04_document_verification_standards.md`                                              |
| Q5  | Hallucination guard      | ✅ PASS | `02_source_of_wealth_verification_guidelines.md`                                     |

**On Q5 specifically:** the model explicitly states "the context does not contain enough information" and points to the policy's escalation clause (chunk references the MLRO procedure for unrecognised wealth sources). It does not invent a cryptocurrency-specific procedure.

**Latency:** ~22–24 seconds per query end-to-end. Most of that is the SentenceTransformer model loading from cache on each fresh subprocess (~2–3 s) plus the Groq round-trip (~1–2 s). Chunking, retrieval, and JSON assembly are all sub-10 ms.

---

## 7. Project Layout

```
take_home_assignment/
├── main.py                          # Typer CLI: ingest + query
├── src/
│   ├── __init__.py
│   ├── config.py                    # Pydantic Settings (loads .env)
│   ├── schemas.py                   # All Pydantic models
│   ├── chunker.py                   # Markdown-section-aware chunking
│   ├── embedder.py                  # SentenceTransformer (BGE-small) wrapper
│   ├── vector_store.py              # FAISS persistence layer
│   ├── retriever.py                 # Hybrid dense + BM25 with RRF
│   ├── prompts.py                   # System, repair, user prompts
│   ├── llm.py                       # GroqProvider + OllamaProvider
│   ├── ingest.py                    # Ingest orchestrator
│   ├── query.py                     # Query orchestrator (the main flow)
│   └── audit.py                     # JSON-Lines append-only writer
├── tests/
│   └── run_public_eval.py           # Subprocess-based eval over 5 questions
├── policies/                        # Provided corpus (5 markdown files)
├── data/                            # Created by `ingest` (FAISS + chunks)
├── audit.log                        # Created/appended on every query
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md                        # This file
```

---

## 8. Error Handling

Every code path returns the same JSON schema. Errors are surfaced through the `error` field; we never print plain text to stdout or exit with only a stderr message.

| Failure                              | Behaviour                                                                                            |
| ------------------------------------ | ---------------------------------------------------------------------------------------------------- |
| `policies/` folder missing on ingest | Exit 1, structured JSON error printed to stdout                                                      |
| Vector store missing on query        | Structured response: `error: "Vector store not found at ... Run ingest first."`                      |
| Zero chunks retrieved                | LLM still called with empty context; the prompt instructs explicit refusal                           |
| LLM API error / timeout              | Single repair retry, then structured error response                                                  |
| LLM returns invalid JSON             | Single repair retry with stricter system prompt, then structured error response                      |
| LLM cites a chunk_id we didn't send  | The fabricated ID is dropped from citations; a warning is written to stderr                          |
| Audit log write fails                | Logged to stderr; query response is still returned (audit failure must not crash the user's request) |

---

## 9. Known Limitations

- **Cold-start latency.** Each `query` invocation reloads the embedding model from cache (~2–3 s). A long-running daemon process would eliminate this, but the brief specifies a CLI.
- **`--k 3` default.** Q3's reasoning would cite all three relevant policies more confidently at `--k 5`. The default is held at 3 per the brief.
- **No cross-encoder re-ranker.** Over 46 chunks the marginal benefit is small. Re-ranking is the next lever to add if the document corpus grew an order of magnitude.

---
