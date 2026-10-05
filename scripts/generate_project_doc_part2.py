"""Parts 3.6 onward of the project reference document.

Split from generate_project_doc.py purely for file size; `append_remaining_parts` continues
writing into the same Doc instance.
"""

from __future__ import annotations

from typing import Any


def append_remaining_parts(doc: Any) -> None:
    part_modules_continued(doc)
    part_algorithms(doc)
    part_results(doc)
    part_decisions(doc)
    part_lessons(doc)
    part_qa(doc)
    part_glossary(doc)
    part_quickref(doc)


# ---------------------------------------------------------------------------
# Part 3 continued — services, observability, API, CLI, eval, tests, frontend
# ---------------------------------------------------------------------------


def part_modules_continued(doc: Any) -> None:
    doc.h2("3.6 services/ — business logic")

    doc.h3("services/chat_service.py")
    doc.bullets(
        [
            "**What.** Conversation memory, RAG invocation, persistence, audit, metrics, logging.",
            "**Division of responsibility.** The pipeline answers questions; this service decides what "
            "a *conversation* is — which turns form the rewrite history (the last four), what gets "
            "persisted, what gets audited, what gets counted. That separation is why the pipeline stays "
            "framework-free and directly unit-testable.",
            "**The privacy split is implemented here.** `_persist_and_record` writes the full question "
            "and full retrieved context to `audit.log`, and writes only a question **hash** and length "
            "to `query_log`. Two sinks, two purposes, one deliberate decision.",
            "**Streaming persistence happens on the terminal event**, so a cancelled stream still "
            "records whatever was produced.",
        ]
    )

    doc.h3("services/document_service.py")
    doc.bullets(
        [
            "**What.** Upload, directory ingest, list, get, chunks, section tree, original bytes, "
            "reindex, delete, activate/deactivate, metadata correction.",
            "**`ingest_directory` collects per-document failures rather than aborting the batch** — one "
            "unreadable file should not prevent the rest of a corpus from indexing. It returns indexed, "
            "skipped-duplicate and failed lists.",
            "**`set_status` is the interesting one.** Deactivating excludes a document from retrieval "
            "while keeping it inspectable. That is the honest way to supersede a policy without "
            "destroying the audit trail that references it, and it is why the status enum has "
            "`inactive` as well as `failed`.",
        ]
    )

    doc.h3("services/stats_service.py and services/evaluation_service.py")
    doc.bullets(
        [
            "**`stats_service`.** Dashboard aggregates measured from the registry, the query log and "
            "the live indices. Nothing is synthesised: where a value is unknown it is reported as zero "
            "or null rather than invented. Computes latency percentiles, refusal rate, error rate and "
            "index-consistency.",
            "**`evaluation_service`.** A thin wrapper over the `eval/` harness, deliberately thin "
            "because the same code must be runnable from the CLI with no server involved — that is how "
            "it is used in CI.",
        ]
    )

    doc.h2("3.7 observability/")
    doc.h3("observability/audit.py")
    doc.bullets(
        [
            "**What.** Append-only JSON-Lines writer. One `AuditEntry` per line.",
            "**Format deliberately unchanged from v1** so existing readers keep working; new fields "
            "(request id, retrieval parameters, evidence, token usage, timings) are additive.",
            "**This is the one place that records full question text and full retrieved context.** "
            "That is its regulatory purpose, it is local, and it is documented. An audit failure logs "
            "loudly but never breaks the user's request — a silently missing audit trail is the worst "
            "outcome.",
            "**Rotation is by size** (50 MB): the file is renamed with a timestamp and a new one "
            "started. It is never truncated or rewritten in place.",
        ]
    )
    doc.h3("observability/metrics.py")
    doc.bullets(
        [
            "**What.** In-process counters and histograms, exposed at `/api/metrics` in Prometheus "
            "text exposition format.",
            "**Why not `prometheus_client`.** A few counters do not justify a dependency. The histogram "
            "buckets (50 ms … 60 s) are chosen around the latencies this system actually exhibits: "
            "sub-100 ms retrieval and 1–20 s LLM round-trips.",
        ]
    )

    doc.h2("3.8 api/ — the HTTP boundary")
    doc.h3("api/middleware.py")
    doc.bullets(
        [
            "**`RequestContextMiddleware`.** Assigns a request id (or honours an inbound "
            "`X-Request-ID`), binds it into the structlog context, times the request, adds a "
            "`Server-Timing` header, and records metrics. Health and metrics paths are excluded from "
            "access logging because polling them would drown the signal.",
            "**`SecurityHeadersMiddleware`.** `nosniff`, `X-Frame-Options: DENY`, "
            "`Referrer-Policy: no-referrer`.",
            "**Four exception handlers** guarantee one error envelope: `AppError` (mapped by its own "
            "status, with `Retry-After` added for rate limits), `RequestValidationError` (field-level "
            "problems), `StarletteHTTPException`, and a catch-all that logs the exception and returns a "
            "generic 500. Internal detail never reaches a response body.",
        ]
    )
    doc.h3("api/deps.py and api/schemas.py")
    doc.bullets(
        [
            "**`deps.py`.** Dependency injection: container, settings, rate limiter, caller. Auth is "
            "expressed as role requirements (`RequireRead`, `RequireWrite`, `RequireAdmin`) so swapping "
            "the identity source changes `get_caller` alone and no route signatures.",
            "**`schemas.py`.** Request/response DTOs, separate from the domain models on purpose: the "
            "HTTP contract should be able to evolve without forcing a change to the RAG core's "
            "vocabulary. Examples are attached so `/docs` is usable as documentation rather than a bare "
            "schema dump.",
        ]
    )
    doc.h3("The 23 endpoints")
    doc.table(
        ["Method and path", "Purpose"],
        [
            ["`GET /api/health`", "Liveness — always 200 while serving, checks nothing else"],
            ["`GET /api/health/ready`", "Readiness: database, index, index consistency, provider, auth mode"],
            [
                "`POST /api/chat`",
                "Non-streaming grounded answer with citations, evidence, conflicts, timings",
            ],
            [
                "`POST /api/chat/stream`",
                "SSE stream: conversation → meta → retrieval → token* → citations → evidence → done",
            ],
            ["`GET /api/conversations`", "List conversations, paginated"],
            ["`GET /api/conversations/{id}`", "Transcript with per-message citations and evidence"],
            [
                "`DELETE /api/conversations/{id}`",
                "Delete transcript — the audit log deliberately retains the queries",
            ],
            ["`POST /api/documents`", "Upload 1..n documents; validated, indexed, deduplicated"],
            ["`GET /api/documents`", "List with status/type filter, search, pagination"],
            ["`GET /api/documents/{id}`", "Metadata, section tree, chunk preview"],
            ["`GET /api/documents/{id}/chunks`", "Paginated chunks — powers source inspection"],
            ["`GET /api/documents/{id}/download`", "Original file, sanitised Content-Disposition"],
            ["`PATCH /api/documents/{id}`", "Activate/deactivate, correct metadata"],
            ["`POST /api/documents/{id}/reindex`", "Re-run the pipeline; idempotent"],
            ["`DELETE /api/documents/{id}`", "Delete document and chunks from both indices"],
            ["`GET /api/stats`", "Dashboard aggregates (typed response model)"],
            ["`GET /api/evaluation/datasets`", "Available golden sets with category breakdown"],
            [
                "`POST /api/evaluation/runs`",
                "Start a run — synchronous when small and deterministic, else background",
            ],
            ["`GET /api/evaluation/runs`", "Run history for trends"],
            ["`GET /api/evaluation/runs/{id}`", "Metrics plus per-question results"],
            ["`GET /api/settings`", "Effective settings — secrets never returned"],
            ["`PATCH /api/settings`", "Session-scoped overrides, never persisted"],
            ["`GET /api/metrics`", "Prometheus text format"],
        ],
        widths=[2.2, 4.5],
    )

    doc.h2("3.9 main.py — the CLI")
    doc.bullets(
        [
            "**Preserved contract.** `ingest --docs <folder>` and `query --question <text> [--k N]` "
            "keep their exact signatures, their single-JSON-object stdout, and their JSONL audit "
            "append on every call, success or failure.",
            "**Added commands** (additive): `serve`, `evaluate`, `documents`, `reindex --id`, "
            "`rebuild-index`.",
            "**Two fixes worth mentioning.** v1's last-resort handler printed JSON but exited **0** and "
            "wrote **no audit entry** — an invisible failure in exactly the case where an audit record "
            "matters most. It now audits and exits non-zero. Separately, stdout and stderr are "
            "reconfigured to UTF-8 because policy text contains non-breaking hyphens and en dashes that "
            "a Windows cp1252 console cannot encode, which killed an otherwise perfect answer at the "
            "print statement.",
        ]
    )

    doc.h2("3.10 eval/ — the evaluation harness")
    doc.h3("eval/metrics.py")
    doc.bullets(
        [
            "**What.** Exact arithmetic for Recall@k, Precision@k, MRR, nDCG@k, hit rate, document "
            "accuracy, section accuracy, citation precision/recall, keyword compliance, forbidden "
            "content, numeric accuracy, refusal correctness, and aggregation with per-category "
            "breakdown.",
            "**Ground truth is section numbers, not heading text** ('3.1', or '05:4' to qualify a "
            "document). Rewording a heading therefore does not silently invalidate the dataset.",
            "**The matching rule is asymmetric on purpose.** A chunk from §3.1 satisfies an expectation "
            "of §3, but a chunk labelled §3 does **not** satisfy an expectation of §3.1 — citing the "
            "parent for a subsection rule gives the user worse provenance and is scored as a miss.",
        ]
    )
    doc.h3("eval/judges.py and eval/run.py")
    doc.bullets(
        [
            "**`judges.py`.** LLM-as-judge for faithfulness and answer relevance. Faithfulness is "
            "measured by **claim decomposition** rather than a holistic score: 'which of these six "
            "claims is supported by the context' is a question a model answers far more reliably than "
            "'rate this answer's groundedness', and the output can be audited claim by claim.",
            "**`run.py`.** Loads the dataset, runs `retrieval_only` or `full` mode, persists runs and "
            "per-question results, renders a markdown report, and supports a `--min-recall-at-5` CI "
            "gate.",
            "**`retrieval_only` is the mode that matters for iteration**: it exercises the real "
            "retrieval stack with no LLM, so it is deterministic, free, offline, and fast enough to "
            "gate every commit.",
            "**One honest caveat documented in the code.** In `retrieval_only` mode, follow-up "
            "questions cannot be rewritten (that needs an LLM), so the previous user turn is "
            "concatenated into the search text instead. Follow-up numbers in that mode are therefore an "
            "approximation of the live path.",
        ]
    )
    doc.h3("eval/datasets/aml_kyc_golden_v1.jsonl")
    doc.table(
        ["Category", "n", "What it tests"],
        [
            ["simple", "16", "Single section, single document"],
            ["nuanced", "8", "Thresholds, exceptions, conditional branches"],
            ["multi", "7", "Requires two or more documents to be complete"],
            ["negative", "5", "Must refuse — crypto SoW, GDPR, tax advice, internal finance"],
            ["numeric", "4", "Exact figures: 25%, 30 points, 24 hours, five years"],
            ["adversarial", "3", "Injection, citation forgery, prompt leak"],
            ["followup", "2", "Two-turn; unanswerable without query rewriting"],
        ],
        widths=[1.2, 0.5, 5.0],
    )
    doc.p(
        "Each record carries: question, category, expected answer, relevant documents, relevant "
        "sections, `must_include`, `must_not_include`, `expected_numbers`, `should_refuse`, optional "
        "`history`, and a `notes` field documenting anything subtle — including, for three records, why "
        "a label was corrected."
    )

    doc.h2("3.11 tests/ — 110 backend tests in 8.5 seconds, offline")
    doc.bullets(
        [
            "**The fakes are what make it fast.** `FakeEmbedder` is a deterministic bag-of-words "
            "hashing embedder producing L2-normalised vectors with real lexical-overlap signal — not a "
            "stub returning zeros, so retrieval tests genuinely exercise ranking. `FakeLLM` is "
            "scripted and can be told to fail, stream, or return malformed JSON. `FakeReranker` "
            "reverses the order so a test can prove reranking took effect.",
            "**Everything else is real**: routers, services, SQLite, FAISS, BM25. Each test gets its "
            "own temporary data directory, database and audit log.",
            "**No network and no API key** is the property that makes the suite usable as a per-commit gate.",
        ]
    )
    doc.table(
        ["Test area", "What it protects"],
        [
            [
                "Citation integrity",
                "Unknown ids dropped in both modes; citation text always comes from the retrieved chunk; duplicates collapse; marker survives every token-split position; empty retrieval means no citations are possible",
            ],
            [
                "Chunking",
                "The subsection regression; structure-split on small sections; heading path; stable uid across re-runs; word budget; overlap; tiny-subsection merge; empty and headingless documents",
            ],
            [
                "Metadata",
                "Front-matter parsing; eight date formats; missing fields → null; version from filename; family key; header block not indexed as content",
            ],
            [
                "Retrieval",
                "RRF arithmetic against hand-computed values; leg agreement; single-leg degradation; weighting; exact and near-duplicate collapse; token budget; paragraph-boundary truncation",
            ],
            [
                "Guardrails",
                "Evidence floor; band boundaries; refusal detection; conflict detection with numeric version ordering; the disclaimer's presence",
            ],
            [
                "Upload security",
                "Unsupported extension; spoofed `.pdf` rejected by content with nothing persisted; oversize; traversal filename; empty file",
            ],
            [
                "API",
                "Upload→index→query→delete; delete leaves all three stores consistent; reindex idempotent; deactivated document unretrievable but inspectable; dedup; 503 when nothing indexed",
            ],
            [
                "Streaming",
                "Event order; marker resolution; conversation persisted; LLM failure reported inside the stream",
            ],
            [
                "Security",
                "Write requires a valid key; wrong key 401; rate limit 429 with Retry-After; injection document flagged; injected instructions cannot fabricate citations; settings never leak secrets",
            ],
            ["Errors", "One envelope everywhere; request id present; no stack traces or paths in responses"],
        ],
        widths=[1.4, 5.3],
    )

    doc.h2("3.12 frontend/ — React 19 + TypeScript")
    doc.h3("The six pages")
    doc.table(
        ["Page", "What it does"],
        [
            [
                "Dashboard",
                "Corpus and index state, latency percentiles, refusal rate, live readiness checks, retrieval configuration, latest evaluation, recent activity by question hash",
            ],
            [
                "Chat",
                "Streaming answers; inline `[1]` chips opening the exact retrieved passage; evidence badge with expandable signals; conflict callout; suggested questions; stop/retry; deep-linkable history",
            ],
            [
                "Documents",
                "Drag-and-drop upload with per-file rejection reasons; filterable table; status pills; activate/deactivate; re-index; delete dialog explaining what survives",
            ],
            [
                "Document detail",
                "Section tree showing how the document was split; the indexed chunks themselves; full metadata; injection flags",
            ],
            [
                "Evaluation",
                "Run the golden set; deterministic and LLM-judged metrics visually separated; per-category table; per-question drill-down defaulting to failures",
            ],
            [
                "Settings",
                "Provider, model, top-k, reranking, temperature; read-only deployment config; API key stored in-browser only",
            ],
        ],
        widths=[1.3, 5.4],
    )
    doc.h3("The four decisions worth defending")
    doc.bullets(
        [
            "**Types are generated, not written.** `src/types/api.d.ts` comes from the backend's "
            "OpenAPI schema via `openapi-typescript`. A renamed Pydantic field becomes a TypeScript "
            "compile error rather than a runtime `undefined`. **This found two weak backend contracts** "
            "— `/api/stats` returned a bare `dict[str, Any]` (generating `Record<string, unknown>`, "
            "which pushes every field access back to runtime) and upload failures were "
            "`list[dict[str, str]]`. Both were fixed on the **backend** with real response models "
            "rather than cast away in the UI.",
            "**Streaming on `fetch`, not `EventSource`.** `EventSource` cannot do a POST with a JSON "
            "body and an auth header. `src/lib/stream.ts` reads the `ReadableStream` and parses SSE "
            "frames directly — about 30 lines, with `AbortController` cancellation for free. It carries "
            "the most tests of anything in the frontend because a frame-reassembly bug would be "
            "invisible in development and destructive in production.",
            "**No component library.** The needed set is small, and the one genuinely hard primitive — "
            "a modal with focus trapping, Escape handling and an inert background — is the native "
            "`<dialog>` element, which gets that behaviour from the platform. This is a deliberate "
            "deviation from the Phase 0 plan, which named shadcn/ui.",
            "**Tailwind 4 over Tailwind 3.** Partly CSS-first `@theme` tokens and a Vite-native plugin; "
            "partly that Tailwind 3's file-watcher dependency chain carried five high-severity "
            "advisories, and v4 carries none.",
        ]
    )
    doc.h3("Honesty rules enforced in the UI, not only the API")
    doc.bullets(
        [
            "An evidence band never renders as a percentage.",
            "A null page reads 'not applicable (no pages in source format)' rather than being hidden.",
            "Unreported token usage says 'not reported', never `0`.",
            "Document status is always icon **and** label, so colour is never the only signal.",
            "Every error state shows the backend's `request_id`.",
            "The chat footer states the system reports what the documents say and is not legal advice.",
        ]
    )
    doc.h3("Accessibility and performance")
    doc.bullets(
        [
            "Skip link as the first tab stop; real `<button>` elements; visible focus rings; "
            "`aria-live` on streaming answers; labelled form controls; `<caption>` on data tables; "
            "`prefers-reduced-motion` respected; three-state theme where an explicit choice wins and "
            "otherwise the OS preference is followed live.",
            "Route-level code splitting keeps the markdown renderer out of the initial bundle. Polling "
            "is scoped to only while a document is `processing` or a run is `running`, so an idle page "
            "makes no requests.",
        ]
    )


# ---------------------------------------------------------------------------
# Part 4 — algorithms
# ---------------------------------------------------------------------------


def part_algorithms(doc: Any) -> None:
    doc.h1("Part 4 — The algorithms, with worked arithmetic")
    doc.p(
        "These are the questions where a vague answer is obvious. Each one here is short enough to "
        "reproduce on a whiteboard."
    )

    doc.h2("4.1 Dense retrieval — why cosine, and why normalisation matters")
    doc.p(
        "Each chunk is encoded by BGE-small into a 384-dimensional vector. Similarity is cosine, "
        "which measures the angle between vectors and so ignores magnitude — two passages about the "
        "same rule should score alike whether one is twice as long."
    )
    doc.code(
        """
cosine(a, b) = (a · b) / (||a|| · ||b||)

If ||a|| = ||b|| = 1  (L2-normalised at encode time)
then cosine(a, b) = a · b    <- a plain inner product

Therefore FAISS IndexFlatIP (inner product) IS cosine search,
with no extra computation, provided vectors are normalised.
""",
        caption="Why the embedder normalises and the index uses inner product",
    )
    doc.p(
        "If asked what breaks without normalisation: inner product would then reward long vectors "
        "regardless of direction, so verbose passages would systematically outrank concise ones."
    )

    doc.h2("4.2 BM25 — why a sparse leg at all")
    doc.p(
        "BM25 scores a document by term frequency, inverse document frequency and length "
        "normalisation. The practical point for this project is that it matches **literal tokens**. "
        "Compliance text is dense with rare terms — `MLRO`, `EDD`, `PEP`, `§4.2`, `31–60` — and a "
        "dense embedding smooths rare tokens toward semantically nearby concepts, which is exactly "
        "the wrong behaviour when the user asked about that specific token."
    )
    doc.p(
        "Conversely BM25 cannot match a paraphrase: 'how often must we screen?' shares almost no "
        "tokens with 'frequency of periodic screening'. Each leg fails where the other succeeds, "
        "which is the argument for hybrid retrieval. **Measured evidence:** leg overlap on the golden "
        "set is 17–27 of 30 candidates, so the legs genuinely disagree on 10–43% of the pool."
    )

    doc.h2("4.3 Reciprocal Rank Fusion — the arithmetic")
    doc.code(
        """
score(d) = SUM over each ranked list L of   weight_L / (k + rank_of_d_in_L)

with k = 60 (the conventional constant) and rank 0-based.

Worked example — two legs, three documents:

  dense ranking:   [A, B, C]
  sparse ranking:  [B, A, D]

  score(A) = 1/(60+0) + 1/(60+1) = 0.016667 + 0.016393 = 0.033060
  score(B) = 1/(60+1) + 1/(60+0) = 0.016393 + 0.016667 = 0.033060
  score(C) = 1/(60+2)            = 0.016129
  score(D) =            1/(60+2) = 0.016129

  Fused order: A, B (tied, agreed by both legs), then C, D.
""",
        caption="RRF: agreement between legs beats a strong showing in one leg",
    )
    doc.bullets(
        [
            "**Why rank fusion rather than score blending.** Cosine similarities sit in roughly "
            "0.5–0.9 while BM25 scores on this corpus run from 6 to 34 — different scales, and both "
            "corpus-dependent. Normalising them against each other would need per-corpus calibration "
            "that breaks whenever documents are added. Ranks are scale-free.",
            "**Why k = 60.** It damps the difference between adjacent ranks so that one leg's "
            "confident first place cannot dominate the other leg entirely. It comes from the original "
            "RRF paper and is exposed as `RRF_K` for tuning; the default was not changed because the "
            "golden set gave no reason to.",
            "**The maximum possible score is 2/60 ≈ 0.0333** when both legs rank a chunk first. That "
            "constant is what `normalised_score` divides by.",
        ]
    )

    doc.h2("4.4 Cross-encoder reranking")
    doc.code(
        """
Bi-encoder (retrieval):     embed(query)  .  embed(passage)      -> one dot product
                            passage vector computed BEFORE the query is known

Cross-encoder (reranking):  model(query + [SEP] + passage)       -> one relevance logit
                            reads both together, token by token

Cost: O(1) per corpus passage to index, O(n) model calls to rerank n candidates.
Hence: retrieve a shortlist cheaply, then rerank only the shortlist.
""",
        caption="The asymmetry that makes a two-stage pipeline the right shape",
    )
    doc.p(
        "The measured effect on the golden set is in Part 5. The measured **cost** produced a second "
        "decision: reranking the fused top-10 scored identically to reranking the top-30, at 566 ms "
        "versus 2,216 ms. The explanation is that RRF's recall@10 is already 0.948, so the relevant "
        "passage is almost always inside the top 10 — scoring 20 more candidates buys nothing."
    )

    doc.h2("4.5 nDCG — and a definitional choice worth owning")
    doc.code(
        """
DCG@k  = SUM over ranks 1..k of  gain_i / log2(i + 1)
IDCG@k = the same sum for the ideal ordering
nDCG@k = DCG@k / IDCG@k

Ideal count used here: min(k, max(number_of_expectations, number_of_relevant_found))
""",
        caption="Binary-gain nDCG as implemented in eval/metrics.py",
    )
    doc.callout(
        "A bug I had to reason about, and a good answer to 'did you validate your metrics?'",
        "The first implementation used `min(len(expected), k)` as the ideal count. But ground truth "
        "here is **section-level** while retrieval is **chunk-level**, so two retrieved chunks can "
        "legitimately satisfy one expectation — and then DCG summed more gains than IDCG, producing "
        "nDCG values above 1.0 (I observed 1.237 in one category). Taking the greater of 'expectations' "
        "and 'relevant found' fixes it. A borrowed metrics library would have hidden this choice; "
        "writing the arithmetic forced me to make it explicitly.",
    )

    doc.h2("4.6 Evidence banding — the rule, stated in full")
    doc.code(
        """
signals = {
  top_score                  normalised 0-1 score of the best passage
  score_margin               top_score minus second_score
  supporting_chunks          how many passages the answer actually cited
  distinct_documents         how many documents those passages came from
  cited_fraction_of_context  cited / retrieved
  answer_is_refusal          pattern-detected
}

band =
  "insufficient"  if refusal OR cited == 0 OR top < 0.30
  "strong"        if top >= 0.60 AND cited >= 2
  "moderate"      if top >= 0.45
  "weak"          otherwise
""",
        caption="Thresholds are environment variables, calibrated against the golden set",
    )
    doc.p(
        "**Why not a confidence score.** A number produced by asking a model 'how confident are you, "
        "0–100?' is uncalibrated — it correlates with fluency rather than correctness. In a compliance "
        "tool a well-formatted meaningless number is actively harmful because it invites reliance. "
        "Every signal above is returned to the client, so the band is auditable rather than magical, "
        "and a disclaimer travels with the data and is asserted by a test."
    )

    doc.h2("4.7 The citation-marker protocol")
    doc.p(
        "Streaming and fabrication-proof citations appear to conflict. v1's safety came from a single "
        "trailing JSON object containing `used_chunk_ids`, which cannot be streamed token by token. "
        "But token-by-token output is the UX users expect. The resolution:"
    )
    doc.numbered(
        [
            "Context is presented to the model as numbered blocks carrying their **real** chunk ids.",
            "The model streams markdown prose with inline `[[cid:17]]` markers after each supported claim.",
            "The server parses markers incrementally, resolves each against the retrieved set, "
            "**discards any id that was not retrieved**, and renumbers survivors to `[1]`, `[2]`, … in "
            "order of first appearance.",
            "A final `citations` SSE event carries the full citation objects.",
            "The non-streaming endpoint and the CLI keep the JSON-mode path unchanged, so the original "
            "contract still holds. Both paths converge on the same validator.",
        ]
    )
    doc.p(
        "The invariant is preserved exactly: **the model never authors citation text; it emits "
        "references into a set the server controls.**"
    )


# ---------------------------------------------------------------------------
# Part 5 — results
# ---------------------------------------------------------------------------


def part_results(doc: Any) -> None:
    doc.h1("Part 5 — Measured results")
    doc.callout(
        "Reproduce any of this",
        "`python -m eval.run --mode retrieval_only` (about 25 s, offline, no API key) for the "
        "retrieval tables. `python -m eval.run --mode full --judge` for the generation tables "
        "(about 21 minutes, roughly 135 model calls).",
    )

    doc.h2("5.1 Retrieval — shipped configuration versus baseline")
    doc.table(
        ["Metric", "RRF only (baseline)", "+ cross-encoder (shipped)", "Change"],
        [
            ["recall@1", "0.774", "**0.870**", "+12.4%"],
            ["recall@3", "0.922", "**0.952**", "+3.2%"],
            ["recall@5", "0.948", "**0.989**", "+4.3%"],
            ["precision@3", "0.3333", "**0.3555**", "+6.7%"],
            ["MRR", "0.776", "**0.863**", "+11.2%"],
            ["nDCG@5", "0.781", "**0.845**", "+8.2%"],
            ["hit rate@5", "0.867", "**0.889**", "+2.5%"],
            ["document accuracy", "0.978", "**1.000**", "+2.3%"],
            ["section accuracy", "0.948", "**0.989**", "+4.3%"],
        ],
        widths=[1.5, 1.6, 1.9, 1.0],
    )
    doc.p(
        "Read that as: **in 99% of questions the labelled section reached the top 5, and in 87% it was "
        "ranked first.** Document accuracy is 1.000 — the right document is always retrieved."
    )

    doc.h3("The caveat that cuts in the system's favour — disclose it anyway")
    doc.p(
        "The five out-of-scope questions have no labelled sections by design, so reciprocal rank "
        "returns 0 for them **by construction**. They depress the aggregate MRR without indicating any "
        "ranking failure."
    )
    doc.table(
        ["Metric", "All 45 questions", "40 answerable only"],
        [
            ["recall@5", "0.989", "0.988"],
            ["MRR", "0.863", "**0.971**"],
            ["nDCG@5", "0.845", "**0.951**"],
            ["precision@3", "0.3555", "0.400"],
        ],
        widths=[1.6, 1.6, 1.8],
    )
    doc.p(
        "**The headline tables use the all-45 figure throughout**, because excluding inconvenient "
        "questions is how benchmarks become meaningless. The answerable-only column is the fairer read "
        "of pure ranking quality, and quoting both is the honest move."
    )
    doc.p(
        "**On precision@3 (0.3555):** bounded above by the labelling scheme, not by retrieval. Most "
        "questions have one or two relevant sections, so at k=3 the ceiling is roughly 0.33–0.67 even "
        "with perfect ranking. It is reported because context pollution matters, but recall, MRR and "
        "nDCG are the decision metrics."
    )

    doc.h2("5.2 By category — where reranking actually earned its place")
    doc.table(
        ["Category", "n", "recall@5", "MRR", "section acc.", "refusal acc."],
        [
            ["simple", "16", "1.000", "1.000", "1.000", "1.000"],
            ["**multi**", "7", "**1.000**", "**1.000**", "**1.000**", "1.000"],
            ["nuanced", "8", "1.000", "1.000", "1.000", "1.000"],
            ["numeric", "4", "1.000", "1.000", "1.000", "1.000"],
            ["followup", "2", "1.000", "1.000", "1.000", "1.000"],
            ["negative", "5", "1.000", "n/a", "1.000", "1.000"],
            ["adversarial", "3", "0.833", "0.500", "0.833", "1.000"],
        ],
        widths=[1.2, 0.5, 1.0, 0.9, 1.1, 1.1],
    )
    doc.callout(
        "This is the best single story about measurement in the project",
        "On the RRF-only baseline, multi-document questions were the clear weak spot at recall@5 "
        "**0.738** — a question like 'a foreign PEP scoring 72, what applies?' has ground truth spanning "
        "five sections across three documents. With the cross-encoder, all seven reach **recall@5 1.000 "
        "and MRR 1.000**. The aggregate moved only 0.948 → 0.989 while the category that mattered moved "
        "0.738 → 1.000. **An average alone would have made the reranker look marginal.** Per-category "
        "reporting is the only reason that is visible.",
    )
    doc.p(
        "The one remaining retrieval gap is a single adversarial question (recall@5 0.5 — the 'ignore "
        "your instructions' injection). Its labelled sections are arguably debatable since the question "
        "is an attack rather than a genuine information need; what matters is that the system refused "
        "correctly and cited nothing fabricated."
    )

    doc.h2("5.3 The chunking fix, isolated")
    doc.p("Same dataset, same embedder, same k — only the chunker changed.")
    doc.table(
        ["Metric", "v1 chunking (size-only split)", "Structure-aware split", "Change"],
        [
            ["recall@5", "0.782", "0.948", "**+21.3%**"],
            ["recall@1", "0.674", "0.774", "+14.8%"],
            ["MRR", "0.635", "0.776", "**+22.2%**"],
            ["section accuracy", "0.782", "0.948", "**+21.3%**"],
        ],
        widths=[1.4, 2.0, 1.6, 1.0],
    )
    doc.p(
        "Before the fix, a question like 'Which sanctions lists does the platform screen against?' "
        "scored **recall@5 = 0.00** while retrieving the correct text — under the label '§2 Definitions' "
        "instead of '§2.1 Sanctions'. The harness found this within minutes of first running; it was "
        "invisible to v1's keyword-based checks."
    )

    doc.h2("5.4 Reranking cost — and the configuration it produced")
    doc.table(
        ["`RERANK_TOP_N`", "recall@1", "recall@5", "MRR", "nDCG@5", "rerank p50", "rerank p95"],
        [
            ["off", "0.774", "0.948", "0.776", "0.781", "0 ms", "0 ms"],
            ["30", "0.870", "0.989", "0.863", "0.845", "2,216 ms", "2,376 ms"],
            ["15", "0.870", "0.989", "0.863", "0.845", "760 ms", "923 ms"],
            [
                "**10 (shipped)**",
                "**0.870**",
                "**0.989**",
                "**0.863**",
                "**0.845**",
                "**566 ms**",
                "**703 ms**",
            ],
        ],
        widths=[1.1, 0.85, 0.85, 0.8, 0.85, 1.0, 0.95],
    )
    doc.p(
        "Phase 0 had estimated this stage at 100–250 ms. It is roughly four times that even at "
        "`top_n=10`, and would have been ten times at the planned pool size. Measuring it is what "
        "turned a wrong estimate into a correct configuration."
    )

    doc.h2("5.5 Top-k sweep")
    doc.table(
        ["k", "recall@5", "MRR", "section accuracy"],
        [
            ["3", "0.922", "0.770", "0.922"],
            ["**5 (default)**", "0.948", "0.776", "0.948"],
            ["8", "0.948", "0.779", "0.978"],
            ["10", "0.948", "0.779", "0.989"],
        ],
        widths=[1.3, 1.3, 1.2, 1.6],
    )
    doc.p(
        "Measured RRF-only, so the figures are the baseline. k=5 is the default as a latency/recall balance; `k` is exposed per request."
    )

    doc.h2("5.6 Generation metrics")
    doc.h3("Deterministic — exact, no judge involved")
    doc.table(
        ["Metric", "Value", "Note"],
        [
            [
                "**Refusal accuracy**",
                "**1.000**",
                "7 correct refusals, **0 over-refusals, 0 missed refusals**",
            ],
            [
                "Numeric accuracy",
                "0.889",
                "Exact figures — the worst failure mode is a right-sounding wrong number",
            ],
            ["Keyword compliance", "0.878", "Required substance present"],
            ["Citation recall", "0.844", "Labelled sections the answer actually cited"],
            ["Citation precision", "0.789", "Cited sections that are genuinely relevant"],
            ["Forbidden-content clean", "0.978", "The single flag is a label artifact — see Part 7"],
        ],
        widths=[1.6, 0.8, 4.3],
    )
    doc.p(
        "**Refusal accuracy of 1.000 with zero missed refusals is the headline result for a compliance "
        "tool.** Across five out-of-scope questions and three adversarial ones, the system never "
        "fabricated a procedure, never adopted a false premise, and never refused a question it could "
        "answer."
    )
    doc.h3("LLM-judged — indicative, not ground truth")
    doc.table(
        ["Metric", "Value", "Method"],
        [
            [
                "Faithfulness",
                "**0.860**",
                "Claim decomposition: 86% of extracted claims supported by context; 36 of 45 answers fully faithful",
            ],
            ["Answer relevance", "**0.928**", "1–5 rubric against the expert reference answer, normalised"],
        ],
        widths=[1.4, 0.8, 4.5],
    )
    doc.p(
        "Temperature 0, versioned prompts, per-claim reasoning persisted so any score can be inspected "
        "rather than trusted. Deterministic metrics remain the headline."
    )

    doc.h2("5.7 Performance")
    doc.table(
        ["Stage", "p50", "p95"],
        [
            ["Retrieval (query embed + FAISS + BM25 + RRF)", "**64–85 ms**", "101 ms"],
            ["Cross-encoder rerank (top-10)", "**566–733 ms**", "923 ms"],
            ["Retrieval pipeline total", "**~0.7 s**", "~1.0 s"],
        ],
        widths=[3.4, 1.6, 1.6],
    )
    doc.table(
        ["Generation path", "TTFT", "LLM total", "End to end"],
        [
            [
                "**Streaming** (representative question, 932 completion tokens)",
                "**~2.0 s**",
                "~2.9 s",
                "**~3.8 s**",
            ],
            ["**Non-streaming JSON** (eval harness, 45 questions)", "n/a", "**14.1 s p50**", "14.9 s p50"],
        ],
        widths=[2.8, 1.0, 1.4, 1.3],
    )
    doc.callout(
        "That 4x gap is a real finding, not a measurement error",
        "Two causes. `gpt-oss-120b` is a reasoning model, so JSON mode spends tokens reasoning before "
        "emitting the object. And the evaluation questions deliberately demand long, complete answers "
        "(full EDD requirement lists, multi-document syntheses) where a chat question usually does not. "
        "It has a design consequence: **streaming is the primary UX for a reason** — the user sees the "
        "first token in about 2 seconds regardless of how long the complete answer takes.",
    )
    doc.table(
        ["Operation", "Measured"],
        [
            ["Corpus ingest (5 documents → 51 chunks, including model load)", "~6.2 s"],
            [
                "Reranker cold load",
                "~10.8 s, once per process — **warmed at startup** so no user request pays it",
            ],
            ["Backend test suite (110 tests, no network)", "**8.5 s**"],
            ["Retrieval-only evaluation (45 questions, offline)", "~25 s"],
            ["Full evaluation with LLM judge (~135 model calls)", "~21 min"],
            ["Frontend production build", "~2.2 s"],
        ],
        widths=[4.0, 2.7],
    )
    doc.p(
        "**The headline improvement over v1:** v1 reloaded the embedding model on every CLI "
        "invocation, which dominated its ~22 second query. Models are now process-lifetime singletons "
        "warmed at startup, so retrieval settles at ~70 ms and the only material latency left is the "
        "model round-trip."
    )


# ---------------------------------------------------------------------------
# Part 6 — decisions
# ---------------------------------------------------------------------------


def part_decisions(doc: Any) -> None:
    doc.h1("Part 6 — Decision records")
    doc.p(
        "Thirteen decisions, each with the choice, the reasoning and the accepted trade-off. DR-1 to "
        "DR-4 are inherited from v1 and kept; DR-5 onward were made in the rebuild, and several were "
        "decided by measurement rather than opinion."
    )

    decisions = [
        (
            "DR-1",
            "Hybrid retrieval (dense + BM25) fused with RRF, not dense alone",
            "Compliance text is terminology-dense. Dense-only smooths rare tokens into neighbouring "
            "concepts; BM25-only misses paraphrase. RRF fuses ranks so no score calibration is needed.",
            "Two retrieval paths to maintain and a fusion constant to justify. Measured leg overlap of "
            "17–27 of 30 confirms both legs do real work.",
        ),
        (
            "DR-2",
            "Chunk on document structure, not fixed windows",
            "Policies are numbered rules and practitioners cite them that way ('Policy 02, Section "
            "3.1'). Cutting mid-rule forces reassembly and produces citations that do not match how "
            "the document reads.",
            "Chunk sizes are uneven. Phase 2 extended this one level deeper — split on H3 whenever H3s "
            "exist, not only when a section is oversized — which produced the +21% recall@5.",
        ),
        (
            "DR-3",
            "Groq as default, Ollama as offline fallback, model behind one environment variable",
            "Free tier, fast, strong instruction-following and reliable refusal behaviour. Ollama means "
            "a reviewer with no API key can still run the system.",
            "Dependence on a hosted free tier. **Immediately vindicated:** Groq decommissioned "
            "`llama-3.3-70b-versatile` between v1 and the rebuild, and the fix was one line because the "
            "model never leaks into the pipeline.",
        ),
        (
            "DR-4",
            "Citations assembled by code from chunk ids, never from LLM free text",
            "Free-form model-authored citations are the single biggest hallucination risk in a "
            "compliance product. Making the model hand over integer references makes fabrication "
            "structurally impossible.",
            "The model must be instructed in a specific protocol, and the protocol must be robust. This "
            "is the project's centrepiece and it survived the addition of streaming.",
        ),
        (
            "DR-5",
            "Keep BAAI/bge-small-en-v1.5 rather than upgrading the embedding model",
            "384 dimensions, ~33M parameters, CPU-fast, free, already cached. With structure-aware "
            "chunking and reranking it reaches recall@5 0.989, so there is no measured case for a "
            "larger model at this corpus size. API embeddings were rejected as default because they add "
            "cost, a network dependency, and third-party transmission of compliance text.",
            "English-only and a 512-token ceiling (which the 300-word chunk target respects). The "
            "embedder is swappable by one environment variable and the index refuses a model mismatch, "
            "so bge-base or e5-base remain a config change plus an eval run.",
        ),
        (
            "DR-6",
            "Retire LangChain; keep orchestration explicit",
            "The pipeline is explicit, readable Python. A framework would hide exactly the engineering "
            "this project exists to demonstrate, add a large fast-moving dependency surface, and make "
            "per-stage instrumentation harder.",
            "More code maintained by hand and no free connectors — accepted, because every stage here is "
            "deliberately custom and individually tested.",
        ),
        (
            "DR-7",
            "Cross-encoder reranking, gated on evaluation",
            "The commitment was to ship it only on a measured win and publish the numbers either way. "
            "It won — recall@1 +12.4%, MRR +11.2% — so it ships enabled. Measuring its cost then "
            "changed the configuration to `top_n=10`.",
            "+566 ms p50 and a 90 MB model. Hidden behind streaming time-to-first-token, and removable "
            "by one flag which reproduces the baseline exactly.",
        ),
        (
            "DR-8",
            "SQLite with no ORM for metadata; FAISS for vectors",
            "Filtered document lists, conversation transcripts and evaluation history need real queries "
            "and transactions; JSON files would mean hand-rolling a database badly. PostgreSQL would add "
            "a service, a pool and migrations for a single-writer workload of a few thousand rows.",
            "Single-writer, local disk, no horizontal scale. The named trigger for revisiting is "
            "multi-replica deployment, concurrent writers, or more than ~10^6 chunks.",
        ),
        (
            "DR-9",
            "Build the evaluation harness rather than adopt RAGAS or DeepEval",
            "Retrieval metrics are about 150 lines of exact arithmetic; the judge is a prompt plus a "
            "Pydantic model. Writing them keeps the dependency tree small, makes every metric "
            "inspectable, and lets them run offline in CI.",
            "No community-standard metric names out of the box — mitigated by using standard definitions "
            "and documenting the formulas. It also forced the nDCG ideal-count decision to be explicit "
            "rather than hidden.",
        ),
        (
            "DR-10",
            "Citation-marker protocol to reconcile streaming with citation integrity",
            "Streaming prose is incompatible with a single trailing JSON object, but token-by-token "
            "output is the expected UX. The model streams `[[cid:n]]` markers; the server resolves, "
            "drops unknowns, and renumbers.",
            "Marker parsing must be robust to arbitrary token boundaries. A real bug here was caught by "
            "an integration test and is now pinned across every split position.",
        ),
        (
            "DR-11",
            "Evidence bands from retrieval signals; no LLM confidence score",
            "Self-reported model confidence is uncalibrated, and a well-formatted meaningless number is "
            "actively harmful in compliance because it invites reliance.",
            "Less satisfying than '92% confident', and the thresholds need golden-set calibration. Both "
            "are acceptable prices for honesty.",
        ),
        (
            "DR-12",
            "LLM-as-judge used, labelled, and never treated as ground truth",
            "Faithfulness has no cheap deterministic proxy. The judge runs at temperature 0 with a "
            "versioned prompt and claim-by-claim decomposition, with reasoning persisted.",
            "Judge noise and cost; mitigated by also reporting exact citation, keyword, numeric and "
            "refusal metrics that need no judge, and by excluding the judge from CI.",
        ),
        (
            "DR-13",
            "Evaluation before frontend",
            "Phase 4 preceded Phase 6 so retrieval changes were validated by measurement rather than by "
            "how convincing a demo felt.",
            "The visible payoff arrived later. It paid for itself immediately: the harness found the "
            "chunking defect within minutes of first running.",
        ),
    ]
    for ref, title, why, trade in decisions:
        doc.h3(f"{ref} — {title}")
        doc.p(why, bold_prefix="Reasoning. ")
        doc.p(trade, bold_prefix="Trade-off accepted. ")

    doc.h2("6.1 Technologies deliberately rejected")
    doc.table(
        ["Rejected", "Reason"],
        [
            [
                "LangChain / LlamaIndex",
                "Would hide the engineering the project exists to demonstrate; large fast-moving dependency surface; harder per-stage instrumentation",
            ],
            [
                "RAGAS / DeepEval",
                "Heavy transitive trees, provider assumptions, and they obscure how metrics are computed",
            ],
            [
                "PostgreSQL + pgvector",
                "No multi-writer, no concurrency, no cross-node requirement at this scale",
            ],
            [
                "Redis / Celery",
                "Nothing to cache across processes; indexing takes seconds, so BackgroundTasks plus a status column gives the same UX without a broker",
            ],
            [
                "HNSW / IVF indexes",
                "Approximate search trades recall for speed, and recall is the metric being judged. Brute force is exact and fast enough",
            ],
            [
                "Next.js",
                "No SSR or SEO need for an authenticated internal tool; a Vite SPA is simpler to containerise",
            ],
            [
                "shadcn/ui + Radix",
                "The needed component set is small and native `<dialog>` solves the one hard primitive",
            ],
            [
                "Zustand / Redux",
                "TanStack Query owns server state; remaining client state is small enough for hooks",
            ],
            [
                "Semantic (embedding) chunking",
                "This corpus has explicit numbered structure mapping 1:1 onto how practitioners cite it. Inferring boundaries statistically would discard ground truth already in the document",
            ],
            [
                "LLM-as-reranker",
                "Doubles cost and latency per query and adds a second hallucination surface to the retrieval path",
            ],
        ],
        widths=[1.7, 5.0],
    )


# ---------------------------------------------------------------------------
# Part 7 — lessons
# ---------------------------------------------------------------------------


def part_lessons(doc: Any) -> None:
    doc.h1("Part 7 — What went wrong, and what it taught")
    doc.p(
        "Interviewers probe here hardest, because it is where judgement shows. Each item below is a "
        "real event from building this system, with what it changed."
    )

    items = [
        (
            "The default model had been decommissioned",
            "`llama-3.3-70b-versatile` returned `404 model_not_found` from Groq. The provider had "
            "retired it between v1 and the rebuild.",
            "Listing available models showed Llama was gone entirely; `openai/gpt-oss-120b` was the "
            "strongest remaining option. The fix was **one line** in `config.py` because the provider "
            "abstraction keeps the model id out of the pipeline.",
            "This is the model-deprecation risk from the Phase 0 risk register actually occurring, and "
            "it is the concrete justification for DR-3's abstraction. An interviewer asking 'why bother "
            "with a provider interface?' gets a real answer rather than a hypothetical.",
        ),
        (
            "My own latency estimate was four times wrong",
            "Phase 0 estimated cross-encoder reranking at 100–250 ms. Measured: **2,216 ms p50** over a "
            "30-candidate pool.",
            "Rather than accept the cost or drop the feature, I measured smaller rerank windows and "
            "found `top_n=10` scored **identically** at 566 ms — because RRF's recall@10 is already "
            "0.948, so the relevant passage is almost always in the top 10.",
            "A wrong estimate became a correct configuration because it was measured rather than "
            "trusted. The README's estimate was corrected in public rather than quietly deleted.",
        ),
        (
            "A streaming bug that only appeared at one token boundary",
            "The partial-marker guard held back `[[cid:1` but not `[[cid:10]` — a prefix that had "
            "already reached the first closing bracket. When a token boundary fell between the two "
            "closing brackets, a raw marker leaked into the visible answer.",
            "An integration test caught it. The regex was widened to cover every proper prefix, and a "
            "parametrised regression test now pins six split positions including character-by-character.",
            "It is the kind of bug that passes every unit test and ships. It is also the strongest "
            "argument for having written integration tests that read the real SSE stream.",
        ),
        (
            "Three of my own evaluation labels were wrong",
            "Three 'forbidden content' violations appeared. In every case the system had refused "
            "**correctly** and the substring check fired on the answer quoting the premise in order to "
            "deny it — for example 'I cannot state that EDD is never required for PEPs' tripped a ban "
            "on 'never required'.",
            "All three labels were corrected to target the *asserted claim* rather than the quoted "
            "premise, with the reasoning recorded in each record's `notes` field. One was also "
            "mislabelled `should_refuse: false` when declining to confirm a non-existent policy **is** "
            "the correct refusal.",
            "The methodological lesson: **a forbidden-substring check must match what the answer "
            "asserts, not words it echoes from the question.** Naive negative labels penalise exactly "
            "the careful refusal behaviour you are trying to reward. The refusal *detector* was widened "
            "in the same pass, because it had missed 'is not one of the five recognised categories'.",
        ),
        (
            "Writing the typed frontend found two weak API contracts",
            "`/api/stats` returned a bare `dict[str, Any]`, which generates `Record<string, unknown>` in "
            "TypeScript and pushes every field access back to runtime. Upload failures were "
            "`list[dict[str, str]]`.",
            "Both were fixed on the **backend** with real Pydantic response models (`StatsResponse` "
            "with five nested models, and `UploadFailure`) rather than cast away in the UI.",
            "This is the entire argument for generating types from the schema, and it paid off within "
            "an hour of starting the frontend. The weak contracts were invisible while only Python "
            "consumed them.",
        ),
        (
            "A free-tier quota exhausted mid-evaluation",
            "A 135-call `--mode full --judge` run hit Groq's 200,000 tokens-per-day limit: 64 retries, "
            "**17 of 45 answers failed**, generation metrics invalidated.",
            "The failure was *visible* — errors are counted per question rather than silently averaged "
            "in — so the degraded run was identified and discarded rather than published. The reported "
            "figures come from the last fully successful run (45/45, zero errors).",
            "Two things to say about this: the uniform error contract meant 17 failures produced 17 "
            "structured error results rather than a crashed run; and `retrieval_only` mode needs no LLM "
            "at all, which is why that is what CI gates on.",
        ),
        (
            "Windows console encoding destroyed a correct answer",
            "A perfectly good answer failed at the `print` statement: cp1252 cannot encode the "
            "non-breaking hyphen (U+2011) that appears in policy text.",
            "stdout and stderr are reconfigured to UTF-8 at CLI start-up.",
            "A reminder that the last six inches of a pipeline can break it. It also happened twice more "
            "in my own test scripts before I set `PYTHONIOENCODING` consistently.",
        ),
        (
            "The chunking defect the evaluation harness found",
            "Questions like 'Which sanctions lists does the platform screen against?' scored **recall@5 "
            "= 0.00** while retrieving exactly the right text — labelled '§2 Definitions' instead of "
            "'§2.1 Sanctions', because v1 only sub-split sections that exceeded 300 words.",
            "Split on structure rather than size, with a 35-word floor so tiny fragments merge into a "
            "sibling.",
            "**+21.3% recall@5 and +22.2% MRR from one logic change.** The harness found it within "
            "minutes of first running, and v1's keyword-based checks could never have seen it — the "
            "keyword was present in the retrieved text. This is the single best argument for DR-13 "
            "(evaluation before frontend).",
        ),
    ]
    for title, what, fix, lesson in items:
        doc.h3(title)
        doc.p(what, bold_prefix="What happened. ")
        doc.p(fix, bold_prefix="What I did. ")
        doc.p(lesson, bold_prefix="Why it matters. ")

    doc.h2("7.1 Known limitations — state these before being asked")
    doc.table(
        ["Limitation", "Honest framing"],
        [
            [
                "**The golden set is only 45 questions**",
                "This is now the main constraint. Every category except `multi` and `adversarial` scores "
                "1.000, which means the dataset is close to saturated and no longer discriminates well. "
                "200+ questions with harder cases and multiple annotators is the honest next step.",
            ],
            [
                "**Docker and deployment are not built**",
                "Phases 10 and 11. The compose design and the deployment options are documented with "
                "costs, and the honest constraint is recorded: FAISS plus SQLite on a local volume make "
                "this a stateful single-replica service, which rules out pure serverless.",
            ],
            [
                "**No screenshots, and the UI was never visually verified**",
                "Browser automation was unavailable in the build environment. Frontend verification was "
                "programmatic: 21 schema conformance checks, SSE incrementality (247 tokens over a "
                "0.62 s spread, proving the proxy does not buffer), citation resolution. Layout, spacing "
                "and dark mode are unverified.",
            ],
            [
                "**Coverage is not measured**",
                "110 backend and 15 frontend tests pass, and the areas covered are enumerated, but there "
                "is no coverage percentage or gate yet. Phase 9.",
            ],
            [
                "**Import boundaries are not machine-enforced**",
                "The layering rule is real and the tests depend on it, but no automated import linter "
                "checks it. One ruff configuration away.",
            ],
            [
                "**Single-tenant in practice**",
                "`tenant_id` plumbing is real and the retrieval filter applies unconditionally, but only "
                "one demo tenant is ever issued and there is no identity provider.",
            ],
            [
                "**Conflict detection has no natural fixture**",
                "The supplied corpus contains no conflicting versions, so it is demonstrated with a "
                "purpose-built, clearly-labelled fixture kept outside `policies/` so no evaluation run "
                "is skewed. Structural detection is exact; semantic detection is best-effort and "
                "labelled as such in the UI.",
            ],
        ],
        widths=[1.9, 4.8],
    )


# ---------------------------------------------------------------------------
# Part 8 — Q&A
# ---------------------------------------------------------------------------


def part_qa(doc: Any) -> None:
    doc.h1("Part 8 — Anticipated questions and answers")
    doc.p(
        "Grouped by theme. Answers are written the way you would say them aloud — a direct claim "
        "first, then the supporting detail."
    )

    doc.h2("8.1 Opening and framing")
    doc.qa(
        "Tell me about this project.",
        "It is a retrieval-augmented generation system for AML/KYC compliance documents. A compliance "
        "officer uploads policy documents and asks natural-language questions, and gets an answer where "
        "every claim is backed by a citation they can click and read. Three things make it more than a "
        "PDF chatbot: fabricated citations are **structurally impossible** because the server resolves "
        "every reference against the passages actually retrieved; the system refuses rather than "
        "guesses, enforced in code before the model is even called; and retrieval quality is "
        "**measured** against a 45-question labelled set rather than assumed — recall@5 0.989, MRR "
        "0.863, refusal accuracy 1.000.",
    )
    doc.qa(
        "What are you most proud of?",
        "That measurement drove the design rather than decorating it. The evaluation harness found a "
        "chunking defect within minutes of first running — questions were scoring zero recall while "
        "retrieving exactly the right text, because the chunk was labelled with its parent section "
        "instead of its subsection. Fixing it lifted recall@5 by 21%. That defect was completely "
        "invisible to the previous keyword-based checks, because the keyword *was* in the retrieved "
        "text.",
    )
    doc.qa(
        "What would you do differently?",
        "Two things. I would write the golden set before the retrieval code, not after — I built "
        "retrieval, then measured it, and the measurement immediately told me the chunker was wrong. "
        "Doing it the other way round would have caught that on day one. And I would have measured the "
        "reranker's latency before designing around an estimate; mine was four times off, and the "
        "estimate had already influenced the planned candidate-pool size.",
    )

    doc.h2("8.2 RAG fundamentals")
    doc.qa(
        "What is RAG and why use it instead of fine-tuning?",
        "Retrieval-augmented generation means retrieving relevant passages from a corpus and giving them "
        "to the model as context, rather than relying on what the model learned in training. For this "
        "problem it is clearly correct for four reasons:",
        [
            "**Attribution.** Compliance requires citing the source. A fine-tune blends knowledge into "
            "weights with no way to point at a passage.",
            "**Freshness.** Policies are versioned and updated. Re-indexing a document takes seconds; "
            "re-fine-tuning does not.",
            "**Correctability.** A wrong answer is usually a retrieval problem you can diagnose and fix. "
            "A wrong fine-tune requires retraining.",
            "**Scale of data.** Five documents and 51 chunks is far too little to fine-tune on, and "
            "nothing about the task needs new capability — just the right text in context.",
        ],
    )
    doc.qa(
        "Why hybrid retrieval? Why not just embeddings?",
        "Because the two methods fail in opposite directions and compliance text needs both. Dense "
        "embeddings handle paraphrase — 'how often must we screen?' matching 'frequency of periodic "
        "screening' — but they smooth rare tokens toward nearby concepts, which is wrong when the user "
        "asked specifically about `MLRO` or `§4.2`. BM25 is literal, so it nails the rare token but "
        "cannot match a paraphrase. Measured evidence that both legs matter: the leg overlap on my "
        "golden set is 17–27 of 30 candidates, so they disagree on 10–43% of the pool.",
    )
    doc.qa(
        "How does Reciprocal Rank Fusion work, and why not just add the scores?",
        "RRF scores each document as the sum over each ranked list of `weight / (60 + rank)`. So a "
        "document ranked first in both legs gets `1/60 + 1/60 ≈ 0.0333`, which is the maximum. "
        "Agreement between legs beats a strong showing in one leg. The reason not to blend raw scores is "
        "that cosine similarities sit around 0.5–0.9 while BM25 scores on this corpus run from 6 to 34 — "
        "different scales, both corpus-dependent. Normalising them against each other needs per-corpus "
        "calibration that breaks whenever documents are added. Ranks are scale-free, which is what makes "
        "RRF robust.",
    )
    doc.qa(
        "What does the reranker add that retrieval does not?",
        "A bi-encoder has to compress a passage into one vector **before it knows the query**, so it "
        "cannot weigh which part of the passage matters for this question. A cross-encoder reads the "
        "query and passage together in one forward pass. It is much more accurate but costs one model "
        "call per candidate, so it reranks a shortlist rather than the corpus. Measured: recall@1 went "
        "0.774 → 0.870 and MRR 0.776 → 0.863. The most interesting part is that per-category, "
        "multi-document questions went from recall@5 0.738 to 1.000 — the aggregate barely moved, so an "
        "average alone would have made the reranker look marginal.",
    )
    doc.qa(
        "How did you choose your chunking strategy?",
        "I split on document structure — H2 sections, then H3 subsections, then paragraphs with a "
        "60-word overlap, capped at 300 words. The reason is that these policies are numbered rules and "
        "practitioners cite them that way: 'Policy 02, Section 3.1'. If you cut mid-rule, the model has "
        "to reassemble it and the citation does not match how the document reads. The 300-word cap is "
        "set by the embedding model: BGE-small truncates at 512 tokens, and 300 words is about 390 "
        "tokens, leaving headroom for the provenance header on every chunk.",
    )
    doc.qa(
        "Why not semantic chunking?",
        "Because this corpus already contains the ground truth that semantic chunking would try to "
        "infer. The documents have explicit numbered headings that map one-to-one onto how compliance "
        "officers cite them. Inferring boundaries from embedding similarity would discard that and make "
        "citations *less* faithful to how the document actually reads. I would revisit it for "
        "unstructured material — scanned memos, email threads — where there is no heading structure to "
        "respect.",
    )
    doc.qa(
        "Why 60 words of overlap?",
        "So that a rule straddling a paragraph boundary is retrievable from either side. Sixty words is "
        "roughly enough to keep a complete sentence plus its lead-in intact. The cost is some duplicated "
        "text in the index, which is why there is a deduplication stage before context assembly — "
        "otherwise two overlapping chunks would consume the context window saying the same thing twice "
        "and bias the model by repetition.",
    )

    doc.h2("8.3 The citation guarantee")
    doc.qa(
        "You say fabricated citations are impossible. Explain exactly how.",
        "The model is never allowed to write citation text. In JSON mode it returns "
        "`used_chunk_ids: [int]`; in streaming mode it emits inline `[[cid:17]]` markers. Either way the "
        "server builds a resolver **from the retrieved set**, looks up each id, and discards anything it "
        "does not recognise — in marker mode it removes the marker from the text entirely, so a "
        "fabricated reference leaves no trace. The citation object's text is then read from the indexed "
        "chunk, not from anything the model wrote. So the worst a model can do is cite nothing, or cite "
        "a real passage that does not support its claim — and the second case is what the faithfulness "
        "metric and the visible passage are for.",
    )
    doc.qa(
        "How did you keep that guarantee when you added streaming?",
        "That was the hardest design problem in the project. The v1 guarantee came from a single "
        "trailing JSON object, which cannot be streamed. I kept the invariant by changing the protocol "
        "rather than weakening it: the model streams prose with `[[cid:n]]` markers, and the server "
        "parses them incrementally, resolves them against the retrieved set, drops unknowns, and "
        "renumbers survivors to `[1]`, `[2]` in order of first appearance. The non-streaming path keeps "
        "the original JSON mode, and both converge on the same validator. There is a parametrised test "
        "proving an unresolvable marker leaves no trace even when split character by character.",
    )
    doc.qa(
        "What if the model cites a real passage that does not actually support its claim?",
        "That is the residual risk and I would not claim otherwise. Three things address it. The "
        "citation is rendered next to the claim and the passage is one click away, so a human can check "
        "in seconds — which is the actual workflow for a compliance officer. The faithfulness metric "
        "measures it by claim decomposition: 86% of extracted claims were judged supported, with 36 of "
        "45 answers fully faithful. And citation precision, which is exact rather than judged, is 0.789 "
        "against labelled sections. None of those is 1.000, and the UI never implies that it is.",
    )

    doc.h2("8.4 Evaluation")
    doc.qa(
        "How do you know the system works?",
        "A 45-question labelled set over the five-document corpus, authored by reading the policies and "
        "recording which document and section answers each question. Ground truth is section numbers, "
        "so rewording a heading does not invalidate the dataset. Retrieval metrics are exact arithmetic "
        "with no LLM involved: recall@5 0.989, MRR 0.863, nDCG@5 0.845, section accuracy 0.989. Running "
        "it takes 25 seconds offline with no API key, which is why CI gates on it.",
    )
    doc.qa(
        "Walk me through your metrics. Why those?",
        "Four groups.",
        [
            "**Recall@k** is the ceiling on answer quality — the model cannot use what was never "
            "retrieved. This is the primary metric.",
            "**Precision@k** measures context pollution, which costs tokens and distracts the model. "
            "Mine is 0.36 and that is bounded by the labelling scheme, not retrieval: most questions "
            "have one or two relevant sections, so at k=3 the ceiling is about 0.33–0.67 even with "
            "perfect ranking.",
            "**MRR and nDCG@5** are order-sensitive, which matters because the first passage gets the "
            "most attention from the model.",
            "**Section accuracy** is right-document-and-right-section. It is the metric the chunking fix "
            "unlocked, and it is the one closest to 'would the citation be useful to an auditor'.",
        ],
    )
    doc.qa(
        "Your MRR is 0.863 but you also quote 0.971. Which is it?",
        "Both, and the difference is worth explaining. Five of the 45 questions are out-of-scope cases "
        "with no labelled sections by design, so reciprocal rank returns 0 for them **by construction** "
        "— not because ranking failed. Across all 45 the MRR is 0.863; across the 40 answerable "
        "questions it is 0.971. I report the all-45 figure in the headline tables because excluding "
        "inconvenient questions is how benchmarks become meaningless, and I report both because quoting "
        "only the higher one would be misleading.",
    )
    doc.qa(
        "How do you measure whether the answer is faithful, not just whether retrieval worked?",
        "Deterministically where I can and with a judge where I cannot, and I label which is which. "
        "Exact: citation precision and recall against labelled sections, keyword compliance, numeric "
        "accuracy (because the worst compliance failure is a right-sounding wrong number), and refusal "
        "accuracy split into correct refusals and over-refusals. Judged: faithfulness via claim "
        "decomposition — the judge extracts individual claims and marks each supported or not — and "
        "answer relevance against a reference answer on a 1–5 rubric. Temperature 0, versioned prompt, "
        "per-claim reasoning persisted so any score is inspectable.",
    )
    doc.qa(
        "Isn't using an LLM to judge an LLM circular?",
        "It is a real weakness and I treat it as one. Three mitigations. The judge is asked a much "
        "easier question than the generator — 'is this specific claim supported by this context?' is far "
        "more reliable than 'rate this answer' — and it answers claim by claim, so each verdict is "
        "auditable. The deterministic metrics are the headline and the judged ones are explicitly "
        "labelled indicative. And the judge never runs in CI, so no automated decision depends on it. "
        "The honest next step is a human-agreement study on a sample.",
    )
    doc.qa(
        "What is your weakest evaluation result?",
        "Citation precision at 0.789 — about a fifth of cited sections are not in my labelled relevant "
        "set. Some of that is genuine over-citation, and some is label strictness, since a passage can "
        "be legitimately supporting without being one I labelled. The other honest weakness is the "
        "dataset size: at 45 questions, every category except multi-document and adversarial now scores "
        "1.000, which means the set is close to saturated and no longer discriminates. Growing it is the "
        "highest-value next piece of work.",
    )
    doc.qa(
        "Did you find any bugs in your own evaluation?",
        "Yes, three label bugs and one metric bug, and I would rather volunteer them. The metric bug: my "
        "nDCG exceeded 1.0 in one category because I used the number of expectations as the ideal count, "
        "while ground truth is section-level and retrieval is chunk-level — two chunks can satisfy one "
        "expectation. The label bugs were all the same mistake: forbidden-substring checks that fired on "
        "correct refusals quoting the premise to deny it, like 'I cannot state that EDD is never "
        "required' tripping a ban on 'never required'. The lesson is that a negative check must match "
        "what the answer *asserts*, not words it echoes from the question.",
    )

    doc.h2("8.5 Architecture and engineering")
    doc.qa(
        "Why no LangChain?",
        "Because the pipeline is the thing I wanted to demonstrate, and a framework would hide it. "
        "Everything in my retrieval path — the asymmetric query prefix, the metadata pre-filter, the "
        "weighted fusion, the eval-gated reranker, the citation resolver, the evidence gate — is custom. "
        "Wrapping that in abstractions designed for a different shape would add a large, fast-moving "
        "dependency surface and make per-stage instrumentation harder, which matters because I report "
        "per-stage latency. For a team shipping a standard pipeline quickly, LangChain is a reasonable "
        "choice; for this, it was the wrong trade.",
    )
    doc.qa(
        "Why SQLite and not PostgreSQL?",
        "Because the workload is single-writer with a few thousand rows, and Postgres would add a "
        "service, a connection pool, migrations and a compose dependency to serve that. SQLite in WAL "
        "mode gives ACID transactions, real SQL and concurrent readers in one file with zero operations. "
        "I also named the trigger for changing: multi-replica deployment, concurrent writers, or more "
        "than about a million chunks. The repository layer is the only place that knows SQL, so the swap "
        "is contained.",
    )
    doc.qa(
        "Why no ORM?",
        "Eight tables with hand-written SQL in one module is less code than configuring SQLAlchemy, and "
        "it keeps the schema legible in the README. The repositories give me the abstraction an ORM "
        "would — services talk in domain objects and never see a `sqlite3.Row`. The cost is writing "
        "migrations by hand, which at eight tables is a numbered SQL script and a version table.",
    )
    doc.qa(
        "Why is the RAG core forbidden from importing FastAPI?",
        "So that the evaluation harness measures production code. If retrieval depended on the web "
        "framework, the harness would either need to spin up an HTTP server or re-implement the "
        "pipeline — and a re-implementation is how benchmarks stop reflecting reality. Keeping `rag/` "
        "framework-free means the CLI, the API and the eval harness are three callers of the same "
        "`RagPipeline.answer()`. It also makes retrieval unit-testable in milliseconds with fake models.",
    )
    doc.qa(
        "How would you scale this to a million chunks?",
        "Four changes, in order of when they bind. First, swap `IndexFlatIP` for an approximate index — "
        "HNSW or IVF-PQ — and measure the recall loss against the golden set, because that trade has to "
        "be quantified rather than assumed. Second, move the registry to Postgres so multiple replicas "
        "can write. Third, move vectors to Qdrant or pgvector so filtering is pushed into the index "
        "rather than intersected in Python. Fourth, make ingestion a queue-backed worker rather than a "
        "background task. The interfaces for the first three already exist, which is the point — but I "
        "would not pre-build any of it for 51 chunks.",
    )
    doc.qa(
        "What happens if the LLM provider goes down?",
        "The request returns the uniform error envelope with code `llm_unavailable`, a request id, and "
        "HTTP 502 — and critically, the **audit entry is still written** with the full retrieved "
        "context, so a failed query is as reconstructable as a successful one. Retrieval itself does not "
        "depend on the provider, so the nearest-passages response still works. There is also an Ollama "
        "fallback switchable by one environment variable for fully offline operation. This is not "
        "theoretical: I hit a quota exhaustion mid-evaluation and 17 of 45 questions returned structured "
        "errors rather than crashing the run.",
    )
    doc.qa(
        "How do you keep the index and the database consistent?",
        "The registry is the source of truth and the indices are derived. Ingestion writes vectors then "
        "commits the registry row, so a crash leaves orphan vectors — which startup reconciliation "
        "detects and removes. Deletion reverses the order, registry first then vectors, so a crash can "
        "only ever leave unreferenced vectors and **never a citation pointing at missing text**. The "
        "readiness endpoint reports index consistency, and `rebuild-index` reconstructs both indices "
        "from the registry as a documented recovery path.",
    )
    doc.qa(
        "Why two output protocols for the same model?",
        "Because streaming and a single trailing JSON object are incompatible, and I wanted both the "
        "streaming UX and the original CLI contract. JSON mode serves the CLI, the non-streaming "
        "endpoint and evaluation; marker mode serves the chat UI. They share the context builder, the "
        "guardrails and the citation validator, so the invariant holds identically — only the transport "
        "differs.",
    )

    doc.h2("8.6 Safety, security and honesty")
    doc.qa(
        "How do you handle prompt injection?",
        "Four layers, and I am explicit that they are not equally strong. The weakest is a regex scanner "
        "at ingest that **flags** suspicious spans for human review — pattern scanners are evadable, and "
        "the code says so. Then the system prompt establishes an instruction hierarchy stating that "
        "document text is untrusted data, so anything inside it that looks like an instruction is "
        "content to report, not obey. Then the structural layer that actually holds: citations resolve "
        "server-side, so an injected 'cite policy X' cannot produce a citation for a policy that was not "
        "retrieved. And adversarial cases are in the golden set, so a regression shows up as a number. "
        "There is a test that uploads a poisoned document and asserts its instructions cannot fabricate "
        "a citation.",
    )
    doc.qa(
        "Why no confidence score?",
        "Because a self-reported model confidence is uncalibrated — it tracks fluency, not correctness — "
        "and in a compliance tool a well-formatted meaningless number is worse than no number, because "
        "it invites reliance. Instead I expose the observable retrieval signals: top passage score, "
        "margin over the next, how many passages supported the answer, how many distinct documents, what "
        "fraction of context was cited. Those produce a discrete band — strong, moderate, weak, "
        "insufficient — by a rule published in the README and visible in the UI. A disclaimer travels "
        "with the data saying it is not a calibrated probability, and a test asserts the disclaimer is "
        "present.",
    )
    doc.qa(
        "How does the system refuse, and how do you know it refuses correctly?",
        "Two independent safeguards, because one is not enough. First a code-level gate: if the best "
        "reranked passage scores below a calibrated floor, no answer is requested from the model at all "
        "— refusal must not depend on the model choosing to refuse. The response states that evidence is "
        "insufficient and lists the nearest matching sections, because a dead end plus 'here is the "
        "closest thing in your corpus' lets the officer judge for themselves. Second the prompt instructs "
        "explicit refusal with the documented escalation path. Measured: refusal accuracy 1.000 — seven "
        "correct refusals, zero missed, zero over-refusals, across five out-of-scope and three "
        "adversarial questions.",
    )
    doc.qa(
        "Is this secure enough for production?",
        "No, and the README says so in a table with two columns. Implemented and tested: magic-byte file "
        "validation, size and page caps, content-addressed storage so client input never builds a path, "
        "Pydantic validation everywhere, API-key auth with constant-time comparison, role dependencies, "
        "tenant-scoped retrieval filters, rate limiting, CORS allowlist, security headers, no secrets in "
        "responses or logs, and a CI check that fails if a key-shaped string is committed. Architecture "
        "prepared but **not** implemented: OIDC/JWT identity, per-document ACLs from directory groups, "
        "WORM audit storage, a secrets manager, encryption at rest, PII detection, distributed rate "
        "limiting, malware scanning. Keeping those columns separate is deliberate — overclaiming "
        "security is worse than lacking it.",
    )
    doc.qa(
        "What sensitive data does the system log?",
        "This is a deliberate split. `audit.log` contains the full question text and the full retrieved "
        "context — that is its regulatory purpose, it is local, append-only, and documented. Application "
        "logs and the analytics table contain a question **hash** and length, never the body, so "
        "shipping logs to a third-party aggregator does not export compliance content. A structlog "
        "processor scrubs anything secret-shaped before any sink sees it, and there is a test asserting "
        "no secret appears in any response.",
    )
    doc.qa(
        "What happens when two policy versions disagree?",
        "The system surfaces both rather than picking one. There are two mechanisms. Structural detection "
        "is exact: retrieved chunks are grouped by document family — the normalised title — and any "
        "family with differing version or effective date raises a conflict carrying both documents, their "
        "versions and dates, and which is newer. Version ordering is numeric, so v2.10 correctly beats "
        "v1.9 where string comparison would not. Semantic detection is prompt-level and labelled "
        "best-effort: the model is told not to choose but to state both and attribute each. I demonstrate "
        "it with a clearly-labelled fixture kept outside the corpus so no evaluation run is skewed.",
    )

    doc.h2("8.7 Frontend")
    doc.qa(
        "Why generate TypeScript types from OpenAPI instead of writing them?",
        "So that a backend field rename is a compile error instead of a runtime `undefined` three screens "
        "deep. It paid off within an hour: building the dashboard exposed that `/api/stats` returned a "
        "bare `dict[str, Any]`, which generates `Record<string, unknown>` and pushes every field access "
        "back to runtime. The honest fix was on the **backend** — a real `StatsResponse` model with five "
        "nested models — not a cast in the UI. The same thing happened again with upload failures. "
        "Writing the typed client is what found two weak API contracts that were invisible while only "
        "Python consumed them.",
    )
    doc.qa(
        "Why not EventSource for streaming?",
        "Because `EventSource` can only issue a GET and cannot set headers, and the chat endpoint is a "
        "POST with a JSON body and an auth header. So the client reads the response `ReadableStream` with "
        "`fetch` and parses SSE frames by hand — about 30 lines — which also gives cancellation through "
        "`AbortController` for free, so the Stop button actually aborts the request rather than just "
        "hiding the output. That parser has the most tests in the frontend because a frame-reassembly bug "
        "would be invisible in development and destructive in production.",
    )
    doc.qa(
        "How did you verify the frontend without a browser?",
        "Programmatically, and I would not claim it substitutes for a visual pass. I validated that every "
        "payload the UI consumes conforms to the OpenAPI schema its types were generated from — 21 shape "
        "checks across all six pages. I streamed a real answer through the Vite proxy and measured "
        "arrival times: 247 token events over a 0.62 second spread, which proves the proxy is not "
        "buffering SSE. A buffered proxy would have delivered everything at once and silently reduced "
        "streaming to a single late dump while every unit test still passed. I also confirmed 4 citations "
        "resolved with full provenance and no raw marker reached the client. What remains unverified is "
        "layout, spacing and dark mode.",
    )
    doc.qa(
        "Why no component library?",
        "The component set this app needs is small — button, card, badge, pill, skeleton, dialog, tabs — "
        "and the one genuinely hard primitive is a modal with focus trapping, Escape handling and an "
        "inert background. The native `<dialog>` element provides all three from the platform, so I got "
        "correct behaviour without 40 KB of JavaScript. That let me skip Radix and shadcn entirely while "
        "keeping accessibility standards-based: real buttons, real ARIA, platform focus management. It is "
        "a deliberate deviation from my own Phase 0 plan, which had named shadcn/ui.",
    )

    doc.h2("8.8 Process and judgement")
    doc.qa(
        "How did you decide what to build first?",
        "I analysed the existing code before changing any of it and catalogued 18 concrete defects, each "
        "traceable to a file and line. Then I ordered the work so that measurement came before anything "
        "that depended on it — the evaluation harness is Phase 4, before the frontend at Phase 6. That "
        "ordering is a decision record in its own right, and it paid for itself: the harness found the "
        "chunking defect immediately, and fixing that was worth more than any UI work.",
    )
    doc.qa(
        "How do you prevent regressions?",
        "Three layers. 110 backend tests running in 8.5 seconds with no network and no API key, which is "
        "what makes them usable as a per-commit gate. A retrieval regression gate in CI that fails the "
        "build if recall@5 drops below the recorded baseline — that is the point of a deterministic "
        "evaluation mode. And the fact that `RERANK_ENABLED=false` reproduces the RRF-only baseline "
        "exactly, so any configuration change can be A/B'd against it.",
    )
    doc.qa(
        "What was the hardest technical problem?",
        "Keeping the citation guarantee while adding streaming. The v1 design got its safety from a "
        "single trailing JSON object, which is fundamentally incompatible with token-by-token output. The "
        "resolution was to change the protocol rather than weaken the guarantee — inline markers resolved "
        "server-side — and the subtlety is that a marker can be split across arbitrary token boundaries. "
        "My first parser held back `[[cid:1` but not `[[cid:10]`, so a boundary between the two closing "
        "brackets leaked a raw marker into the answer. An integration test caught it, and it is now pinned "
        "across six split positions.",
    )
    doc.qa(
        "If you had two more weeks, what would you do?",
        "In order: finish Docker and get a live URL, because a project a recruiter cannot click is worth "
        "less than one they can. Then grow the golden set to 200+ questions with harder cases, because at "
        "45 it is nearly saturated and no longer discriminates between configurations. Then query "
        "decomposition for multi-document questions — splitting 'a foreign PEP scoring 72' into "
        "sub-queries and merging the results — which is the architectural fix for the category reranking "
        "currently papers over. Then coverage measurement and Playwright flows.",
    )
    doc.qa(
        "What would you tell someone starting a RAG project tomorrow?",
        "Write the labelled evaluation set before the retrieval code. I did it the other way round and "
        "the harness immediately told me my chunker was wrong in a way no amount of manual testing had "
        "revealed — the answers *looked* right, because the right text was being retrieved under the "
        "wrong label. Without the measurement I would have shipped a system with 21% less recall than it "
        "could have had, and I would have had no idea.",
    )


# ---------------------------------------------------------------------------
# Part 9 — glossary
# ---------------------------------------------------------------------------


def part_glossary(doc: Any) -> None:
    doc.h1("Part 9 — Glossary")
    doc.p("Every term used in this document or the codebase, defined so you can say it aloud confidently.")

    doc.h2("9.1 RAG and retrieval")
    doc.table(
        ["Term", "Definition"],
        [
            [
                "**RAG**",
                "Retrieval-Augmented Generation. Retrieve relevant passages from a corpus, then give them to a language model as context so the answer is grounded in them rather than in training data.",
            ],
            [
                "**Chunk**",
                "One retrievable unit of a document. Here: a section or subsection, up to 300 words, carrying its full heading path as metadata.",
            ],
            [
                "**Embedding**",
                "A dense vector representation of text where semantic similarity corresponds to geometric closeness. 384 dimensions in this project.",
            ],
            [
                "**Bi-encoder**",
                "Encodes query and passage independently, so passage vectors can be precomputed and indexed. Fast; cannot weigh query-specific relevance.",
            ],
            [
                "**Cross-encoder**",
                "Encodes query and passage together in one forward pass to produce a relevance score. Accurate; costs one model call per candidate.",
            ],
            [
                "**Dense retrieval**",
                "Nearest-neighbour search over embeddings. Handles paraphrase; blurs rare tokens.",
            ],
            [
                "**Sparse retrieval**",
                "Term-matching search such as BM25. Handles rare literal tokens; misses paraphrase.",
            ],
            [
                "**BM25**",
                "A ranking function scoring documents by term frequency, inverse document frequency and length normalisation. The standard keyword baseline.",
            ],
            ["**Hybrid retrieval**", "Running dense and sparse retrieval and combining the results."],
            [
                "**RRF**",
                "Reciprocal Rank Fusion. Combines ranked lists as `sum(weight / (k + rank))`, using only ranks so incomparable score scales do not need calibration.",
            ],
            [
                "**Reranking**",
                "A second, more expensive scoring pass over a retrieved shortlist to improve the ordering at the top.",
            ],
            ["**Top-k**", "How many passages are passed to the model as context. Default 5 here."],
            ["**Candidate pool**", "How many passages each retrieval leg returns before fusion. 30 here."],
            [
                "**Cosine similarity**",
                "Similarity as the cosine of the angle between two vectors — magnitude-independent. Equals the inner product when vectors are L2-normalised.",
            ],
            [
                "**L2 normalisation**",
                "Scaling a vector to unit length, which is what makes inner-product search equivalent to cosine search.",
            ],
            [
                "**FAISS**",
                "Facebook AI Similarity Search — a vector indexing library. `IndexFlatIP` is exact brute-force inner-product search.",
            ],
            [
                "**ANN**",
                "Approximate Nearest Neighbour. Faster than exact search but with some recall loss — deliberately not used here.",
            ],
            [
                "**Query expansion**",
                "Adding terms to a query to improve matching. Here: a deterministic acronym dictionary applied to the sparse leg only.",
            ],
            [
                "**Query rewriting**",
                "Turning a follow-up question into a standalone one using conversation history.",
            ],
            ["**Context window**", "The maximum tokens a model can attend to in one request."],
            ["**Grounding**", "Constraining a model to answer only from supplied context."],
            ["**Hallucination**", "A model asserting something not supported by its context or by fact."],
        ],
        widths=[1.4, 5.3],
    )

    doc.h2("9.2 Metrics")
    doc.table(
        ["Term", "Definition"],
        [
            [
                "**Recall@k**",
                "Fraction of labelled relevant items appearing in the top k. The ceiling on answer quality.",
            ],
            ["**Precision@k**", "Fraction of the top k that are relevant. Measures context pollution."],
            [
                "**MRR**",
                "Mean Reciprocal Rank — the mean of `1/rank` of the first relevant result. Rewards putting the right passage first.",
            ],
            [
                "**nDCG@k**",
                "Normalised Discounted Cumulative Gain. Rank-discounted relevance divided by the ideal ordering's value; order-sensitive.",
            ],
            [
                "**Hit rate@k**",
                "Whether at least one relevant item appears in the top k. Blunt but reportable.",
            ],
            [
                "**Faithfulness**",
                "Whether the answer's claims are supported by the supplied context. Measured here by claim decomposition with an LLM judge.",
            ],
            [
                "**Answer relevance**",
                "Whether the answer addresses the question, scored against a reference answer.",
            ],
            [
                "**Citation precision / recall**",
                "Of the citations given, how many are relevant; of the relevant sections, how many were cited.",
            ],
            [
                "**Refusal accuracy**",
                "Whether the system refused exactly when it should have. Split into correct refusals, over-refusals and missed refusals.",
            ],
            [
                "**Golden set**",
                "A labelled question set with recorded ground truth, used to measure retrieval and generation quality.",
            ],
            [
                "**LLM-as-judge**",
                "Using a language model to score outputs against a rubric. Indicative, not ground truth.",
            ],
            [
                "**p50 / p95**",
                "Median and 95th-percentile latency. p95 matters because it is what slow users experience.",
            ],
            [
                "**TTFT**",
                "Time To First Token — what a streaming interface actually feels like, as distinct from total generation time.",
            ],
        ],
        widths=[1.6, 5.1],
    )

    doc.h2("9.3 Compliance domain")
    doc.table(
        ["Term", "Definition"],
        [
            [
                "**AML**",
                "Anti-Money Laundering — controls preventing the financial system being used to launder criminal proceeds.",
            ],
            [
                "**KYC**",
                "Know Your Customer — verifying who a client is before and during a business relationship.",
            ],
            ["**CDD**", "Customer Due Diligence. Three tiers here: Simplified, Standard and Enhanced."],
            ["**SDD**", "Simplified Due Diligence — reduced checks for demonstrably low-risk clients."],
            [
                "**EDD**",
                "Enhanced Due Diligence — heightened checks: two independent Source of Wealth sources, senior management approval, documented rationale, elevated monitoring, six-monthly review.",
            ],
            [
                "**PEP**",
                "Politically Exposed Person — holds or recently held a prominent public function. Domestic, Foreign and International Organisation tiers. Always triggers EDD.",
            ],
            [
                "**SoW / SoF**",
                "Source of Wealth (how total assets were accumulated) versus Source of Funds (where the money in a specific transaction came from).",
            ],
            [
                "**MLRO**",
                "Money Laundering Reporting Officer — the accountable individual to whom cases are escalated.",
            ],
            [
                "**UBO**",
                "Ultimate Beneficial Owner — the real person who ultimately owns or controls an entity. 25% threshold in this corpus.",
            ],
            [
                "**SAR**",
                "Suspicious Activity Report — filed with the authorities (the National Crime Agency in this corpus).",
            ],
            [
                "**Sanctions screening**",
                "Checking clients against government and international prohibition lists: HM Treasury, OFAC, EU, UN.",
            ],
            [
                "**FATF**",
                "Financial Action Task Force — sets international AML standards and maintains grey and black lists of jurisdictions.",
            ],
            [
                "**Risk band**",
                "Low 0–30, Medium 31–60, High 61–100 in this corpus, determining CDD tier and review frequency.",
            ],
            [
                "**Effective date**",
                "When a policy version came into force. Decisive when two versions conflict.",
            ],
        ],
        widths=[1.4, 5.3],
    )

    doc.h2("9.4 Engineering")
    doc.table(
        ["Term", "Definition"],
        [
            [
                "**SSE**",
                "Server-Sent Events — a one-way streaming protocol over HTTP using `text/event-stream`.",
            ],
            [
                "**WAL**",
                "Write-Ahead Logging — a SQLite journal mode allowing readers to proceed during a write.",
            ],
            [
                "**Content-addressed storage**",
                "Storing a file under a hash of its content, which gives deduplication for free and makes path traversal impossible.",
            ],
            [
                "**Idempotent**",
                "Producing the same result when repeated. Re-indexing a document is idempotent here because chunk ids are content-derived.",
            ],
            ["**Composition root**", "The single place that builds the object graph. `container.py` here."],
            [
                "**Dependency injection**",
                "Passing collaborators in rather than constructing them internally — what makes fake models possible in tests.",
            ],
            [
                "**Append-only**",
                "Written by adding to the end, never modified in place. The property that makes the audit log an audit log.",
            ],
            [
                "**Constant-time comparison**",
                "Comparing secrets without early exit, so response timing does not reveal how much of a guess was correct.",
            ],
            [
                "**Magic bytes**",
                "A file's leading signature (`%PDF-`, `PK\\x03\\x04`), used to verify its real type rather than trusting the extension.",
            ],
            [
                "**Prompt injection**",
                "Malicious instructions embedded in data that the model treats as commands.",
            ],
            [
                "**Instruction hierarchy**",
                "Telling the model explicitly that the system message outranks anything appearing in the data.",
            ],
            [
                "**Uniform error envelope**",
                "Every non-2xx response sharing one shape: code, message, details, request id, timestamp.",
            ],
            [
                "**Request id**",
                "A per-request identifier returned in every response and present on every log line, so one report maps to one grep.",
            ],
            [
                "**Readiness versus liveness**",
                "Liveness: is the process up. Readiness: can it actually serve. Separate because restarting on a dependency outage fixes nothing.",
            ],
        ],
        widths=[1.7, 5.0],
    )


# ---------------------------------------------------------------------------
# Part 10 — quick reference
# ---------------------------------------------------------------------------


def part_quickref(doc: Any) -> None:
    doc.h1("Part 10 — Quick reference")

    doc.h2("10.1 Numbers worth memorising")
    doc.table(
        ["Category", "Figure"],
        [
            ["Corpus", "5 documents · **51 chunks** · 384-dimensional vectors"],
            ["Golden set", "**45 questions** across 7 categories · 5 must-refuse · 3 adversarial"],
            [
                "Retrieval (shipped)",
                "recall@5 **0.989** · recall@1 **0.870** · MRR **0.863** · nDCG@5 **0.845** · section accuracy **0.989** · document accuracy **1.000**",
            ],
            ["Retrieval (answerable only)", "MRR **0.971** · nDCG@5 **0.951**"],
            ["Baseline (RRF only)", "recall@5 0.948 · recall@1 0.774 · MRR 0.776 · nDCG@5 0.781"],
            ["Reranking gain", "recall@1 **+12.4%** · MRR **+11.2%** · nDCG@5 +8.2%"],
            ["Multi-document category", "recall@5 **0.738 → 1.000** with reranking"],
            ["Chunking fix", "recall@5 **+21.3%** · MRR **+22.2%**"],
            [
                "Generation",
                "refusal accuracy **1.000** (7 correct, 0 missed, 0 over) · numeric 0.889 · keyword 0.878 · citation recall 0.844 · citation precision 0.789",
            ],
            ["LLM-judged", "faithfulness **0.860** (36/45 fully faithful) · relevance **0.928**"],
            [
                "Latency",
                "retrieval **64–85 ms** · rerank **566 ms** · TTFT **~2.0 s** · streaming end-to-end **~3.8 s** · non-streaming eval p50 **14.1 s**",
            ],
            [
                "Reranker config",
                "`top_n=10` — identical quality to 30 at **4× less latency** (566 ms vs 2,216 ms)",
            ],
            ["Tests", "**110 backend** in 8.5 s offline · **15 frontend** · 23 endpoints · 38 schemas"],
            ["Code", "~8,400 lines backend (65 modules) · ~4,300 lines frontend (22 modules)"],
            ["Ingest", "5 documents → 51 chunks in **~6.2 s**"],
        ],
        widths=[1.7, 5.0],
    )

    doc.h2("10.2 Commands")
    doc.code(
        """
# --- backend (from the project root) -------------------------------------
.\\.venv\\Scripts\\Activate.ps1          # Windows PowerShell
python main.py ingest --docs ./policies   # index the corpus (~6 s)
python main.py serve                      # API :8000, docs at /docs
python main.py query --question "When is EDD required?" --k 5
python main.py documents                  # list indexed documents
python main.py reindex --id doc_xxx       # re-run the pipeline for one document
python main.py rebuild-index              # rebuild FAISS + BM25 from the registry

# --- evaluation ----------------------------------------------------------
python -m eval.run --mode retrieval_only            # ~25 s, offline, no API key
python -m eval.run --mode full --judge              # + generation metrics (~21 min)
python -m eval.run --mode retrieval_only --rerank false   # reproduce the baseline
python -m eval.run --mode retrieval_only --top-k 8
python -m eval.run --mode retrieval_only --min-recall-at-5 0.95   # the CI gate

# --- tests and quality ---------------------------------------------------
pytest tests -q                           # 110 tests, no network
ruff check backend eval tests main.py
ruff format backend eval tests main.py

# --- frontend ------------------------------------------------------------
cd frontend
npm install
npm run dev                               # http://localhost:3000
npm run verify                            # typecheck + lint + tests + build
npm run gen:api                           # regenerate types from openapi.json

# --- conflict detection demo --------------------------------------------
python main.py ingest --docs ./fixtures   # adds the superseded CDD Policy v1.9
python main.py query --question "How often must a high-risk client be reviewed?" --k 6

# --- regenerate this document -------------------------------------------
python scripts/generate_project_doc.py
""",
        caption="Everything you might be asked to demonstrate",
    )

    doc.h2("10.3 Troubleshooting")
    doc.table(
        ["Symptom", "Cause and fix"],
        [
            [
                "`error: The model did not return a usable response`",
                "Usually the Groq free-tier daily token cap (200,000/day). It rolls over. `--mode retrieval_only` needs no LLM at all.",
            ],
            [
                "`[Errno 10048] error while attempting to bind`",
                "Port 8000 already held, often by an orphaned server. `netstat -ano | findstr :8000` then `taskkill /PID <pid> /F`.",
            ],
            [
                "`404 model_not_found`",
                "The configured model has been retired by the provider. List available models and change `GROQ_MODEL` — one line.",
            ],
            [
                "`Index at ... was built with model=...`",
                "The embedding model changed since the index was built. Deliberate refusal rather than silent nonsense: re-run ingest or `rebuild-index`.",
            ],
            ["`503 index_not_ready`", "Nothing is indexed. Run `python main.py ingest --docs ./policies`."],
            [
                "`UnicodeEncodeError: 'charmap'`",
                "A Windows console in cp1252. Set `PYTHONIOENCODING=utf-8`; the CLI already reconfigures its own streams.",
            ],
            [
                "Frontend cannot reach the API",
                "Use `localhost:3000` rather than `127.0.0.1:3000` — Vite prefers IPv6. Confirm the backend is up at `/api/health`.",
            ],
            [
                "`Cannot find native binding`",
                "An npm optional-dependency bug after install/uninstall cycles. Install the platform binding explicitly, or remove `node_modules` and `package-lock.json` and reinstall.",
            ],
        ],
        widths=[2.3, 4.4],
    )

    doc.h2("10.4 The one-minute narrative")
    doc.p(
        "If you have sixty seconds and one chance, this is the order that works: **problem → guarantee "
        "→ measurement → honesty.**"
    )
    doc.callout(
        "Say it like this",
        "“Compliance officers need answers from their own policy documents that they can verify, because "
        "a confidently wrong answer with a fabricated citation is worse than no answer. I built a RAG "
        "system where fabricated citations are structurally impossible — the model emits references and "
        "the server resolves them against the passages actually retrieved, dropping anything else. Then "
        "I measured it: 45 labelled questions, recall@5 0.989, refusal accuracy 1.000 with zero missed "
        "refusals. The measurement is what made it good — it found a chunking defect costing 21% recall "
        "that was invisible to keyword testing. And it is honest about its limits: no fake confidence "
        "score, no invented page numbers, and security split explicitly into what is implemented versus "
        "what is only designed.”",
    )
