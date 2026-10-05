"""Generate the project reference document (.docx).

Why this is a script rather than a hand-written file: the document contains ~60 measured
numbers. Regenerating it after a change is the only way to stop it drifting away from the
code — a stale technical document is worse than none.

    python scripts/generate_project_doc.py

Output: Compliance_Intelligence_Copilot_Technical_Reference.docx in the project root.
"""

from __future__ import annotations

import sys
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = PROJECT_ROOT / "Compliance_Intelligence_Copilot_Technical_Reference.docx"

INK = RGBColor(0x1F, 0x23, 0x37)
MUTED = RGBColor(0x5B, 0x63, 0x73)
ACCENT = RGBColor(0x3B, 0x3D, 0xB8)
OK = RGBColor(0x1B, 0x7A, 0x4B)
WARN = RGBColor(0xA5, 0x5A, 0x0B)
CODE_BG = "F4F5F7"
CALLOUT_BG = "EEF1FB"
NOTE_BG = "FFF8E6"


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------


class Doc:
    def __init__(self) -> None:
        self.d = Document()
        self._setup_styles()

    def _setup_styles(self) -> None:
        normal = self.d.styles["Normal"]
        normal.font.name = "Calibri"
        normal.font.size = Pt(10.5)
        normal.font.color.rgb = INK
        normal.paragraph_format.space_after = Pt(7)
        normal.paragraph_format.line_spacing = 1.14

        for name, size, color, before in (
            ("Heading 1", 20, ACCENT, 20),
            ("Heading 2", 15, INK, 16),
            ("Heading 3", 12, INK, 12),
            ("Heading 4", 10.5, MUTED, 10),
        ):
            style = self.d.styles[name]
            style.font.name = "Calibri"
            style.font.size = Pt(size)
            style.font.color.rgb = color
            style.font.bold = True
            style.paragraph_format.space_before = Pt(before)
            style.paragraph_format.space_after = Pt(5)
            style.paragraph_format.keep_with_next = True

        for section in self.d.sections:
            section.top_margin = Inches(0.85)
            section.bottom_margin = Inches(0.85)
            section.left_margin = Inches(0.9)
            section.right_margin = Inches(0.9)

    # --- structure ---------------------------------------------------------
    def h1(self, text: str, page_break: bool = True) -> None:
        if page_break:
            self.d.add_page_break()
        self.d.add_heading(text, level=1)

    def h2(self, text: str) -> None:
        self.d.add_heading(text, level=2)

    def h3(self, text: str) -> None:
        self.d.add_heading(text, level=3)

    def h4(self, text: str) -> None:
        self.d.add_heading(text, level=4)

    # --- text --------------------------------------------------------------
    def p(self, text: str = "", bold_prefix: str | None = None) -> None:
        """Paragraph with inline **bold** and `code` markup."""
        para = self.d.add_paragraph()
        if bold_prefix:
            run = para.add_run(bold_prefix)
            run.bold = True
        self._runs(para, text)

    def _runs(self, para, text: str) -> None:
        import re

        for token in re.split(r"(\*\*[^*]+\*\*|`[^`]+`)", text):
            if not token:
                continue
            if token.startswith("**") and token.endswith("**"):
                para.add_run(token[2:-2]).bold = True
            elif token.startswith("`") and token.endswith("`"):
                run = para.add_run(token[1:-1])
                run.font.name = "Consolas"
                run.font.size = Pt(9.5)
                run.font.color.rgb = ACCENT
            else:
                para.add_run(token)

    def bullets(self, items: list[str], level: int = 0) -> None:
        for item in items:
            para = self.d.add_paragraph(style="List Bullet" if level == 0 else "List Bullet 2")
            para.paragraph_format.space_after = Pt(3)
            self._runs(para, item)

    def numbered(self, items: list[str]) -> None:
        for item in items:
            para = self.d.add_paragraph(style="List Number")
            para.paragraph_format.space_after = Pt(3)
            self._runs(para, item)

    def code(self, text: str, caption: str | None = None) -> None:
        if caption:
            cap = self.d.add_paragraph()
            cap.paragraph_format.space_after = Pt(2)
            run = cap.add_run(caption)
            run.italic = True
            run.font.size = Pt(9)
            run.font.color.rgb = MUTED

        table = self.d.add_table(rows=1, cols=1)
        table.alignment = WD_TABLE_ALIGNMENT.LEFT
        cell = table.rows[0].cells[0]
        self._shade(cell, CODE_BG)
        cell.text = ""
        for index, line in enumerate(text.strip("\n").split("\n")):
            para = cell.paragraphs[0] if index == 0 else cell.add_paragraph()
            para.paragraph_format.space_after = Pt(0)
            para.paragraph_format.line_spacing = 1.0
            run = para.add_run(line)
            run.font.name = "Consolas"
            run.font.size = Pt(8.5)
        self.d.add_paragraph().paragraph_format.space_after = Pt(2)

    def callout(self, title: str, body: str, tone: str = "accent") -> None:
        table = self.d.add_table(rows=1, cols=1)
        cell = table.rows[0].cells[0]
        self._shade(cell, NOTE_BG if tone == "note" else CALLOUT_BG)
        cell.text = ""
        head = cell.paragraphs[0]
        head.paragraph_format.space_after = Pt(2)
        run = head.add_run(title)
        run.bold = True
        run.font.size = Pt(10)
        run.font.color.rgb = WARN if tone == "note" else ACCENT
        body_para = cell.add_paragraph()
        body_para.paragraph_format.space_after = Pt(0)
        self._runs(body_para, body)
        self.d.add_paragraph().paragraph_format.space_after = Pt(2)

    def table(self, headers: list[str], rows: list[list[str]], widths: list[float] | None = None) -> None:
        table = self.d.add_table(rows=1, cols=len(headers))
        table.style = "Table Grid"
        table.alignment = WD_TABLE_ALIGNMENT.LEFT

        for index, header in enumerate(headers):
            cell = table.rows[0].cells[index]
            self._shade(cell, CODE_BG)
            cell.text = ""
            para = cell.paragraphs[0]
            para.paragraph_format.space_after = Pt(1)
            run = para.add_run(header)
            run.bold = True
            run.font.size = Pt(9)

        for row_values in rows:
            cells = table.add_row().cells
            for index, value in enumerate(row_values):
                cells[index].text = ""
                para = cells[index].paragraphs[0]
                para.paragraph_format.space_after = Pt(1)
                para.paragraph_format.line_spacing = 1.0
                self._runs(para, str(value))
                for run in para.runs:
                    if run.font.size is None:
                        run.font.size = Pt(9)

        if widths:
            for row in table.rows:
                for index, width in enumerate(widths):
                    row.cells[index].width = Inches(width)

    def qa(self, question: str, answer: str, extra: list[str] | None = None) -> None:
        """A question/answer pair — the format for the interview-preparation sections."""
        para = self.d.add_paragraph()
        para.paragraph_format.space_before = Pt(9)
        para.paragraph_format.space_after = Pt(3)
        para.paragraph_format.keep_with_next = True
        run = para.add_run(f"Q. {question}")
        run.bold = True
        run.font.size = Pt(10.5)
        run.font.color.rgb = INK

        answer_para = self.d.add_paragraph()
        answer_para.paragraph_format.left_indent = Inches(0.22)
        self._runs(answer_para, answer)
        if extra:
            for item in extra:
                bullet = self.d.add_paragraph(style="List Bullet")
                bullet.paragraph_format.left_indent = Inches(0.5)
                bullet.paragraph_format.space_after = Pt(2)
                self._runs(bullet, item)

    @staticmethod
    def _shade(cell, hex_color: str) -> None:
        shading = OxmlElement("w:shd")
        shading.set(qn("w:val"), "clear")
        shading.set(qn("w:fill"), hex_color)
        cell._tc.get_or_add_tcPr().append(shading)

    def toc(self) -> None:
        para = self.d.add_paragraph()
        run = para.add_run()
        begin = OxmlElement("w:fldChar")
        begin.set(qn("w:fldCharType"), "begin")
        instr = OxmlElement("w:instrText")
        instr.set(qn("xml:space"), "preserve")
        instr.text = r'TOC \o "1-2" \h \z \u'
        separate = OxmlElement("w:fldChar")
        separate.set(qn("w:fldCharType"), "separate")
        placeholder = OxmlElement("w:t")
        placeholder.text = "Right-click here and choose 'Update Field' to build the table of contents."
        separate.append(placeholder)
        end = OxmlElement("w:fldChar")
        end.set(qn("w:fldCharType"), "end")
        for element in (begin, instr, separate, end):
            run._r.append(element)

    def footer_page_numbers(self) -> None:
        footer = self.d.sections[0].footer
        para = footer.paragraphs[0]
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = para.add_run()
        begin = OxmlElement("w:fldChar")
        begin.set(qn("w:fldCharType"), "begin")
        instr = OxmlElement("w:instrText")
        instr.text = "PAGE"
        end = OxmlElement("w:fldChar")
        end.set(qn("w:fldCharType"), "end")
        for element in (begin, instr, end):
            run._r.append(element)
        run.font.size = Pt(8)
        run.font.color.rgb = MUTED

    def title_page(self) -> None:
        for _ in range(3):
            self.d.add_paragraph()
        title = self.d.add_paragraph()
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = title.add_run("Compliance Intelligence Copilot")
        run.bold = True
        run.font.size = Pt(28)
        run.font.color.rgb = ACCENT

        subtitle = self.d.add_paragraph()
        subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = subtitle.add_run("Technical Reference and Interview Preparation Guide")
        run.font.size = Pt(13)
        run.font.color.rgb = MUTED

        tagline = self.d.add_paragraph()
        tagline.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = tagline.add_run(
            "A production-style Retrieval-Augmented Generation platform for AML/KYC compliance"
        )
        run.italic = True
        run.font.size = Pt(10.5)
        run.font.color.rgb = MUTED

        for _ in range(2):
            self.d.add_paragraph()

        self.table(
            ["", ""],
            [
                ["Backend", "Python 3.10+ · FastAPI · Pydantic v2 · FAISS · BM25 · sentence-transformers"],
                ["Frontend", "React 19 · TypeScript 5.9 · Vite 8 · Tailwind CSS 4 · TanStack Query 5"],
                [
                    "Models",
                    "BAAI/bge-small-en-v1.5 (embeddings) · ms-marco-MiniLM-L-6-v2 (reranker) · openai/gpt-oss-120b via Groq (generation)",
                ],
                ["Scale", "5 documents · 51 indexed chunks · 45-question labelled evaluation set"],
                ["Code", "~8,400 lines backend (65 modules) · ~4,300 lines frontend (22 modules)"],
                ["Tests", "110 backend (8.5 s, offline) · 15 frontend · 23 API endpoints · 38 schemas"],
                [
                    "Headline result",
                    "recall@5 0.989 · MRR 0.863 · refusal accuracy 1.000 (0 missed refusals)",
                ],
            ],
            widths=[1.4, 5.3],
        )

        self.d.add_paragraph()
        note = self.d.add_paragraph()
        note.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = note.add_run(
            "Every number in this document is measured on the current code, not estimated. "
            "Reproduction commands are given alongside each result."
        )
        run.italic = True
        run.font.size = Pt(9)
        run.font.color.rgb = MUTED

    def save(self) -> Path:
        self.footer_page_numbers()
        self.d.save(OUTPUT)
        return OUTPUT


# ---------------------------------------------------------------------------
# Part 0 — how to use this document
# ---------------------------------------------------------------------------


def part_how_to_use(doc: Doc) -> None:
    doc.h1("How to use this document", page_break=True)
    doc.p(
        "This document exists so that you can answer any question about this project with "
        "confidence, including questions you have not anticipated. It is organised so that you "
        "can read it linearly once, then use it as a lookup."
    )

    doc.h2("Structure")
    doc.table(
        ["Part", "What it covers", "Read this when"],
        [
            ["1", "The problem and the product", "You need the 60-second pitch"],
            ["2", "Architecture — the layers and why each exists", "Asked 'walk me through the design'"],
            ["3", "Every module explained, file by file", "Asked about a specific file or component"],
            ["4", "The algorithms, with worked arithmetic", "Asked 'how does RRF actually work?'"],
            ["5", "Measured results and what they mean", "Asked 'how do you know it works?'"],
            ["6", "Decision records — the 13 significant choices", "Asked 'why did you choose X over Y?'"],
            ["7", "What went wrong and what it taught", "Asked about failures, debugging, or judgement"],
            ["8", "~70 anticipated questions with answers", "Rehearsing before an interview"],
            ["9", "Glossary of every term used", "You hit a term you cannot define aloud"],
            ["10", "Numbers and commands worth memorising", "The night before"],
        ],
        widths=[0.5, 3.4, 2.8],
    )

    doc.h2("Three things to internalise above all else")
    doc.numbered(
        [
            "**Citations cannot be fabricated — structurally, not by request.** The model emits "
            "references into a set the server controls; the server resolves them against the "
            "passages actually retrieved and silently discards anything else. This is the single "
            "most important property of the system and it survived the addition of streaming.",
            "**Retrieval quality is measured, not asserted.** A 45-question labelled set produces "
            "recall@5 0.989, MRR 0.863 and refusal accuracy 1.000, reproducible with one command. "
            "The measurement found a real chunking defect that was invisible to the previous "
            "keyword-based checks and whose fix lifted recall@5 by 21%.",
            "**The project is honest about its limits.** No LLM confidence score. Page numbers null "
            "for markdown rather than invented. Token usage null rather than estimated. Security "
            "split into 'implemented' and 'architecture prepared'. Three of my own dataset labels "
            "found wrong and corrected in public.",
        ]
    )

    doc.callout(
        "If you only remember one sentence",
        "“I built a compliance RAG system where fabricated citations are structurally impossible, "
        "and I measured retrieval quality against a labelled set rather than assuming it — which is "
        "how I found a chunking defect that was costing 21% recall.”",
    )


# ---------------------------------------------------------------------------
# Part 1 — problem and product
# ---------------------------------------------------------------------------


def part_problem(doc: Doc) -> None:
    doc.h1("Part 1 — The problem and the product")

    doc.h2("1.1 The domain problem")
    doc.p(
        "Compliance officers at regulated firms work against a library of AML/KYC policy "
        "documents: Customer Due Diligence policies, Source of Wealth guidelines, sanctions and "
        "PEP screening procedures, document verification standards, risk frameworks. Four "
        "properties of these documents make general-purpose chatbots unsuitable."
    )
    doc.table(
        ["Property", "Why it breaks a generic chatbot"],
        [
            [
                "**Cross-referential**",
                "One real question — 'a foreign PEP scores 72, what applies?' — is answered by three "
                "different documents, each contributing one piece of the rule. A single-document "
                "lookup returns a partial answer, and a partial compliance answer is a wrong one.",
            ],
            [
                "**Versioned and dated**",
                "CDD Policy v2.1 effective 1 Jan 2025 contradicts the v1.9 PDF still circulating in "
                "someone's inbox. Answering from the superseded version is a regulatory finding.",
            ],
            [
                "**Literal**",
                "'Three months of payslips' is not 'recent payslips'. 'Expired within 6 months' is not "
                "'expired'. Thresholds, counts and time windows must be reproduced exactly.",
            ],
            [
                "**Audited**",
                "A regulator can ask what the firm relied on for a decision made nine months ago. "
                "'The AI said so' is not an answer; 'here is the exact passage the model was shown, "
                "the model version and the timestamp' is.",
            ],
        ],
        widths=[1.3, 5.4],
    )

    doc.p(
        "The failure mode that matters is not 'unhelpful'. It is **confidently wrong with a "
        "fabricated citation**, which is worse than no answer at all, because it looks verified."
    )

    doc.h2("1.2 What the system does about it")
    doc.table(
        ["Guarantee", "Mechanism", "Where it lives"],
        [
            [
                "Answers only from firm documents",
                "Retrieval-augmented generation with an explicit grounding prompt; no external knowledge",
                "`rag/prompts.py`",
            ],
            [
                "Citations cannot be fabricated",
                "Model emits references; server resolves them against the retrieved set and drops unknowns",
                "`rag/citations.py`",
            ],
            [
                "Refuses rather than guesses",
                "Evidence floor checked **before** the model is asked for an answer at all",
                "`rag/guardrails.py`",
            ],
            [
                "Conflicting versions surfaced",
                "Structural detection on document family + version/effective date",
                "`rag/guardrails.py`",
            ],
            [
                "Evidence strength without false precision",
                "Observable retrieval signals plus a banded rule — never an LLM confidence score",
                "`rag/guardrails.py`",
            ],
            [
                "Reconstructable audit trail",
                "Append-only JSONL holding the full question and the full retrieved context",
                "`observability/audit.py`",
            ],
            [
                "Quality is measured",
                "45 labelled questions, exact retrieval metrics, CI regression gate",
                "`eval/`",
            ],
        ],
        widths=[1.7, 3.4, 1.6],
    )

    doc.h2("1.3 Project history — why there is a 'v1'")
    doc.p(
        "The project began as a take-home assignment: a Python CLI with two commands (`ingest`, "
        "`query`) over five supplied policy documents, which passed 5/5 on a public verification "
        "question set. That version is preserved at `docs/legacy/src-v1/`."
    )
    doc.p(
        "The current system is a rebuild of the internals with the CLI contract kept intact. That "
        "matters for two reasons you may be asked about: it demonstrates **backward-compatible "
        "refactoring** (the original `ingest`/`query` commands, their stdout JSON schema and the "
        "`audit.log` format all still work, with additive fields only), and it means every claimed "
        "improvement has a baseline to be measured against."
    )

    doc.h2("1.4 Current scope — what is built and what is not")
    doc.table(
        ["Phase", "Scope", "State"],
        [
            ["0", "Repository analysis, 18 defects catalogued, target architecture, roadmap", "Done"],
            ["1", "Layered backend, structlog, error hierarchy, pinned deps, ruff, pytest, CI", "Done"],
            ["2", "Ingestion pipeline, SQLite registry, multi-format extraction, delete/reindex", "Done"],
            [
                "3",
                "Reranking, metadata filtering, citation protocol, guardrails, conversation memory",
                "Done",
            ],
            ["4", "Evaluation harness, 45-question golden set, published experiments, CI gate", "Done"],
            ["5", "FastAPI — 23 endpoints, SSE streaming, OpenAPI, 45 integration tests", "Done"],
            ["6", "React frontend — 6 pages, streaming chat, citation inspection, eval dashboard", "Done"],
            ["7", "Observability — request ids, stage timings, /api/metrics, query log", "Largely done"],
            ["8", "Security — validation, API key, roles, rate limits, injection defence", "Largely done"],
            ["9", "Test depth — 125 tests passing; coverage gate and Playwright outstanding", "Partial"],
            ["10", "Docker and Compose", "Not started"],
            ["11", "Deployment and a live URL", "Not started"],
            ["12", "Portfolio polish — screenshots, demo recording", "Not started"],
        ],
        widths=[0.5, 4.5, 1.7],
    )
    doc.callout(
        "Answer this honestly if asked",
        "Docker and deployment are genuinely not built yet, and there are no screenshots because the "
        "visual pass has not been done. Saying so is better than overclaiming — and the roadmap for "
        "both is written in the README with per-phase definitions of done.",
        tone="note",
    )


# ---------------------------------------------------------------------------
# Part 2 — architecture
# ---------------------------------------------------------------------------


def part_architecture(doc: Doc) -> None:
    doc.h1("Part 2 — Architecture")

    doc.h2("2.1 The layer diagram")
    doc.code(
        """
 Clients          CLI (main.py)                React SPA (frontend/)
                      |                              |
                      |                        REST + SSE
                      v                              v
 HTTP            +-------------------------------------------------+
 boundary        |  FastAPI                                        |
                 |  Middleware: request-id, timing, API key,       |
                 |              rate limit, CORS, error envelope   |
                 |  Routers: chat, documents, conversations,       |
                 |           evaluation, system                    |
                 +-------------------------------------------------+
                      |
 Business        +-------------------------------------------------+
 logic           |  Services: ChatService, DocumentService,        |
                 |            EvaluationService, StatsService      |
                 |  (no HTTP types reach this layer)               |
                 +-------------------------------------------------+
                      |                              |
 Domain          +----------------------+  +------------------------+
 core            |  RAG pipeline        |  |  Ingestion pipeline    |
                 |  query processing    |  |  validate -> extract   |
                 |  -> filter           |  |  -> clean -> metadata  |
                 |  -> dense + sparse   |  |  -> chunk -> scan      |
                 |  -> RRF -> rerank    |  |  -> embed -> index     |
                 |  -> context select   |  |  -> registry row       |
                 |  -> evidence gate    |  +------------------------+
                 |  -> generate         |
                 |  -> validate/cite    |
                 +----------------------+
                      |
 Storage         +-------------------------------------------------+
                 |  SQLite (WAL)   FAISS index   uploads   audit.log|
                 +-------------------------------------------------+
""",
        caption="Figure 1 — request flow through the layers",
    )

    doc.h2("2.2 Why each layer exists")
    doc.p(
        "This is the question most likely to be asked as 'walk me through your architecture'. The "
        "answer that lands is not a list of layers but a reason for each boundary."
    )
    doc.table(
        ["Layer", "Responsibility", "Why it is a separate layer"],
        [
            [
                "**Middleware**",
                "Request id, timing, auth, rate limit, CORS, uniform errors",
                "One place guarantees that **every** response carries a `request_id`. That turns a "
                "user report of 'it broke' into a single grep. Scattering this through handlers means "
                "some paths lose it, and those are the paths that fail.",
            ],
            [
                "**Routers**",
                "Translate HTTP to DTOs and back. Nothing else.",
                "Logic inside a router cannot be reused by the CLI and cannot be tested without an "
                "HTTP client. Thin routers are precisely what lets `main.py` remain a first-class "
                "consumer of the same code.",
            ],
            [
                "**Services**",
                "Orchestration, persistence, audit, metrics. Knows nothing of HTTP.",
                "The CLI, the HTTP API and the evaluation harness are three callers of the **same** "
                "`RagPipeline.answer()`. Without this layer the evaluation would measure a different "
                "code path than production — the most common way RAG benchmarks become meaningless.",
            ],
            [
                "**RAG core**",
                "Query processing, retrieval, fusion, reranking, context, generation, validation",
                "Framework-free by rule: it may not import FastAPI. That is what makes retrieval "
                "testable in milliseconds with fake models, and what lets the eval harness call "
                "production retrieval directly instead of over HTTP.",
            ],
            [
                "**Ingestion**",
                "Nine discrete stages from bytes to indexed chunks",
                "Upload is where untrusted data enters a compliance system. Each stage has exactly one "
                "failure mode worth asserting on, and a partial failure must leave the registry "
                "consistent.",
            ],
            [
                "**Storage**",
                "SQLite for metadata, FAISS for vectors, filesystem for originals, JSONL for audit",
                "Four kinds of data with four access patterns and four durability rules. The audit log "
                "is deliberately separate and append-only: an audit trail living in a mutable table is "
                "not an audit trail.",
            ],
        ],
        widths=[1.0, 2.0, 3.7],
    )

    doc.h2("2.3 The import rule that enforces the design")
    doc.code(
        """
api/        may import services, schemas.    MUST NOT import rag/ or storage/ directly.
services/   may import rag, storage, schemas. MUST NOT import fastapi.
rag/        may import schemas, core.         MUST NOT import fastapi, services, storage.
ingestion/  may import storage, core.
storage/    may import schemas, core.         MUST NOT import services or rag.
core/       imports nothing from the above (config, errors, logging, security).
""",
        caption="Dependency direction — always inward, never outward",
    )
    doc.p(
        "If asked how the rule is enforced: by review and by the fact that violating it breaks the "
        "test suite, because the unit tests construct `rag/` objects with no FastAPI application "
        "present. It is not currently enforced by an automated import linter — that is an honest "
        "gap and a one-line ruff configuration away."
    )

    doc.h2("2.4 Composition root")
    doc.p(
        "`backend/app/container.py` is the single place that builds the object graph. Both the "
        "FastAPI lifespan and the CLI use it. This is the mechanism behind the claim that "
        "`python main.py query` and `POST /api/chat` execute identical retrieval code."
    )
    doc.p(
        "It also solves v1's biggest performance problem. v1 constructed the embedding model inside "
        "each CLI invocation, costing roughly 2–3 seconds of a ~22 second query. Here the embedder, "
        "reranker, FAISS index, BM25 index and SQLite connection are created once per process and "
        "warmed at startup, so retrieval settles at 64–85 ms."
    )
    doc.table(
        ["Held object", "Lifetime", "Why"],
        [
            [
                "`Database`",
                "Process",
                "One SQLite connection, WAL mode, write lock; opening per request would serialise reads",
            ],
            [
                "`Embedder`",
                "Process",
                "Model load is ~2 s; cached by model name so one process loads each model once",
            ],
            [
                "`Reranker`",
                "Process",
                "Cold load measured at 10.8 s — this must never be paid by a user request",
            ],
            [
                "`VectorStore`",
                "Process",
                "FAISS index held in memory; reloading per request would dominate latency",
            ],
            [
                "`BM25Store`",
                "Process",
                "Fixes v1's defect of re-tokenising the whole corpus on every single query",
            ],
            [
                "`HybridRetriever`",
                "Per access",
                "Cheap to construct; rebuilt so a settings override takes effect immediately",
            ],
            [
                "`RagPipeline`",
                "Per access",
                "Same reason — composes cached singletons, holds no state of its own",
            ],
        ],
        widths=[1.3, 0.9, 4.5],
    )


# ---------------------------------------------------------------------------
# Part 3 — module by module
# ---------------------------------------------------------------------------


def part_modules(doc: Doc) -> None:
    doc.h1("Part 3 — Every module explained")
    doc.p(
        "For each module: what it does, the technical detail worth knowing, and why it exists. "
        "If you are asked about a specific file, this is the section to find."
    )

    # ---- core ----
    doc.h2("3.1 core/ — foundations")

    doc.h3("core/config.py")
    doc.bullets(
        [
            "**What.** One `Settings` class built on pydantic-settings, loading every value from "
            "environment variables or `.env`. Grouped by concern (LLM, embeddings, retrieval, "
            "reranking, evidence thresholds, storage, uploads, server/security, observability) but "
            "kept flat, because pydantic-settings maps environment variables to flat fields.",
            "**Technical detail.** `@lru_cache` on `get_settings()` means the whole process shares "
            "one object and `.env` is read once. Derived properties (`index_dir`, `db_path`, "
            "`cors_origin_list`, `auth_enabled`) keep path and parsing logic out of callers. A "
            "validator absolutises relative paths so behaviour does not depend on the working "
            "directory.",
            "**Why.** No secret is ever defaulted to a real value, nothing is hardcoded, and every "
            "retrieval parameter is tunable without code changes — which is what made the "
            "reranking and top-k experiments possible at all.",
            "**Interview-ready detail.** The default Groq model lives here, and that single line is "
            "what made recovering from a model deprecation trivial (see Part 7).",
        ]
    )

    doc.h3("core/errors.py")
    doc.bullets(
        [
            "**What.** One `AppError` hierarchy: `ValidationError`, `NotFoundError`, `ConflictError`, "
            "`UnsupportedFileError`, `FileTooLargeError`, `ExtractionError`, `IndexNotReadyError`, "
            "`LLMError`, `AuthError`, `ForbiddenError`, `RateLimitError`.",
            "**Technical detail.** Each subclass carries a stable machine-readable `code` and an HTTP "
            "`status_code`. One exception handler in the API turns any of them into the uniform error "
            "envelope; the CLI turns the same exceptions into its structured `error` field.",
            "**Why.** Clients need to branch on failures (`index_not_ready` means 'upload a document', "
            "`rate_limited` means 'retry later'), and that is impossible if errors are bare strings. "
            "It also guarantees internal detail stays in logs rather than leaking into responses.",
        ]
    )

    doc.h3("core/logging.py")
    doc.bullets(
        [
            "**What.** structlog configuration, replacing v1's `print(..., file=sys.stderr)`.",
            "**Technical detail.** Context-local binding means a request id bound once in middleware "
            "appears on every subsequent log line for that request — including lines emitted deep "
            "inside the RAG pipeline — without threading an argument through every function. A "
            "redaction processor scrubs secret-shaped values (`api_key`, `authorization`, `token`, "
            "anything containing `gsk_`) before any sink sees them. Output goes to stderr so the CLI's "
            "stdout stays a single JSON object.",
            "**Why.** This is the foundation observability is built on. It also implements the "
            "privacy split: `hash_text()` gives a stable 16-character hash so a log line can be "
            "correlated with an audit entry **without** putting compliance question text into logs "
            "that might be shipped to a third-party aggregator.",
        ]
    )

    doc.h3("core/security.py")
    doc.bullets(
        [
            "**What.** `Caller` identity, API-key verification, role comparison, and a fixed-window "
            "`RateLimiter`.",
            "**Technical detail.** Key comparison uses `hmac.compare_digest` (constant-time, so "
            "response timing does not leak how much of a guessed key was correct). Roles are ranked "
            "`viewer < analyst < admin`. `Caller` carries a `tenant_id` so retrieval filters can be "
            "tenant-scoped from day one.",
            "**Why, stated carefully.** This is a shared-secret gate, not an identity provider. It is "
            "deliberately shaped so that replacing `verify_api_key` with OIDC/JWT validation changes "
            "one function and no route signatures. When no `API_KEY` is configured the service runs "
            "open — a documented local-development default that the readiness endpoint reports and "
            "the Settings page warns about.",
        ]
    )

    # ---- models ----
    doc.h2("3.2 models.py — the shared vocabulary")
    doc.p(
        "Pydantic models rather than dataclasses, because every boundary crossing is validated. "
        "These are the nouns the whole system speaks: ingestion produces them, retrieval ranks them, "
        "generation cites them, the API serialises them, the audit log records them."
    )
    doc.table(
        ["Model", "Role", "Detail worth knowing"],
        [
            [
                "`ChunkMetadata`",
                "Provenance for one passage",
                "19 fields. `citation_label` property renders 'Title v1.3 — §3.1 Name (p. 4)'. `family_key` normalises the title for conflict grouping.",
            ],
            [
                "`Chunk`",
                "A retrievable unit",
                "`chunk_uid` (content-derived), `faiss_id` (registry-assigned int64), text with inline provenance header. Legacy `.document`/`.section` accessors preserve v1's flat API.",
            ],
            [
                "`RetrievedChunk`",
                "A chunk plus its scores",
                "Carries `rrf_score`, `rerank_score`, `dense_rank`, `sparse_rank`. `normalised_score` maps either scoring scale onto 0–1 for evidence banding.",
            ],
            [
                "`Citation`",
                "What the UI renders and an auditor verifies",
                "15 fields. `document` and `chunk` are v1's original names, retained so the CLI contract and existing audit readers still work.",
            ],
            [
                "`Evidence`",
                "Retrieval-derived strength",
                "Band plus six observable signals plus a disclaimer that it is not a calibrated probability.",
            ],
            [
                "`Conflict`",
                "A surfaced version disagreement",
                "Sources with version, effective date, and which is most recent. `detection` is literally typed `'structural'`.",
            ],
            [
                "`StageTimings`",
                "Per-stage latency",
                "Eight fields including `llm_ttft_ms` tracked separately, because time-to-first-token is what a streaming UI actually feels like.",
            ],
            [
                "`TokenUsage`",
                "Provider-reported usage",
                "All fields optional — null when the provider does not report, never estimated.",
            ],
            [
                "`RetrievalParams`",
                "The configuration that produced a result",
                "Recorded on every answer and audit entry so an experiment is reconstructable from its output.",
            ],
            [
                "`AnswerResult`",
                "Full internal result",
                "`retrieved` is marked `exclude=True` so it never serialises to the API but is available for the audit entry.",
            ],
            [
                "`QueryResponse`",
                "The CLI's stdout contract",
                "Original seven keys unchanged; evidence/conflicts/refused are additive.",
            ],
            [
                "`AuditEntry`",
                "One line in audit.log",
                "Original five fields unchanged; request id, params, evidence, usage, timings additive.",
            ],
        ],
        widths=[1.2, 1.7, 3.8],
    )
    doc.callout(
        "The `normalised_score` detail is worth understanding",
        "RRF scores are tiny — the best possible is `2/60 ≈ 0.033` when both legs rank a chunk first — "
        "while cross-encoder logits are unbounded and can be negative. Evidence thresholds must work "
        "for both, so RRF scores are divided by that theoretical maximum and rerank logits are passed "
        "through a logistic squash. This is a **presentation transform, not a probability**, and the "
        "code says so in a comment.",
    )

    # ---- storage ----
    doc.h2("3.3 storage/ — persistence")

    doc.h3("storage/db.py")
    doc.bullets(
        [
            "**What.** SQLite access: connection, WAL mode, foreign keys, versioned migrations, a "
            "transactional `write()` context manager, and read helpers.",
            "**Technical detail.** One connection shared process-wide with `check_same_thread=False` "
            "and an `RLock` around writes. WAL mode allows concurrent readers during a write. "
            "Migrations are numbered SQL scripts applied in order and tracked in a `schema_version` "
            "table. `write()` commits on success and rolls back on any exception.",
            "**Why.** Eight tables of explicit SQL is less code than configuring an ORM and keeps the "
            "schema legible. The single-writer design is correct for a single-replica deployment and "
            "is exactly the constraint documented as the trigger for moving to PostgreSQL.",
        ]
    )
    doc.table(
        ["Table", "Purpose"],
        [
            [
                "`documents`",
                "The registry — source of truth. Unique index on `content_sha256` gives upload deduplication.",
            ],
            ["`chunks`", "Chunk text and metadata; `faiss_id` unique, `document_id` cascades on delete"],
            [
                "`conversations` / `messages`",
                "Transcripts with per-message citations, evidence, conflicts, timings, usage",
            ],
            ["`eval_runs` / `eval_results`", "Run history and per-question results, so trends are queryable"],
            [
                "`query_log`",
                "Analytics: question **hash** and length, counters, stage latencies. Never question text.",
            ],
        ],
        widths=[1.6, 5.1],
    )

    doc.h3("storage/vector_store.py")
    doc.bullets(
        [
            "**What.** FAISS wrapper: `IndexIDMap2` around `IndexFlatIP`.",
            "**Technical detail.** `IndexFlatIP` is exact brute-force inner-product search; because "
            "vectors are L2-normalised at encode time, inner product equals cosine similarity. "
            "`IndexIDMap2` attaches stable int64 ids so `remove_ids` can delete one document's "
            "vectors. Filtered search is exact by construction: when a filter is active the whole "
            "index is scanned and intersected with the allowed id set, which costs microseconds at "
            "this scale and avoids debugging an approximate filtered-ANN path.",
            "**Why `IndexFlatIP` and not HNSW/IVF.** At 51 chunks — and even at tens of thousands — "
            "brute force is fast and, critically, **exact**. Approximate indexes trade recall for "
            "speed, and recall is the metric this project is judged on. Choosing an approximate index "
            "here would mean accepting unmeasured retrieval loss to solve a performance problem that "
            "does not exist.",
            "**Safety property.** `load_or_create` refuses to load an index whose recorded embedding "
            "model or dimension differs from the current configuration. Mixing embedding spaces "
            "produces silently meaningless similarity scores — far worse than a loud failure.",
        ]
    )

    doc.h3("storage/bm25_store.py")
    doc.bullets(
        [
            "**What.** Persisted sparse index using `rank_bm25`'s `BM25Okapi`.",
            "**Technical detail.** The tokenised corpus is persisted to JSONL and the BM25 model is "
            "built once per process, rebuilt only when the corpus actually changes (a `_dirty` flag). "
            "Tokenisation is a simple `\\w+` lowercase split.",
            "**Why.** v1 re-tokenised the entire corpus inside `HybridRetriever.__init__`, i.e. on "
            "every single query. Negligible at 46 chunks, O(corpus) per request as it grows, and "
            "pointless under a long-lived server.",
        ]
    )

    doc.h3("storage/files.py and storage/repositories.py")
    doc.bullets(
        [
            "**`files.py`.** Content-addressed storage: files are saved under their SHA-256 digest, "
            "sharded by the first two hex characters. Three benefits at once — path traversal is "
            "impossible because client input never builds a path, identical uploads deduplicate for "
            "free, and the original filename stays pure metadata.",
            "**`repositories.py`.** The only module that knows SQL. `DocumentRepository`, "
            "`ChunkRepository`, `ConversationRepository`, `EvalRepository`, `QueryLogRepository`. "
            "Services talk in domain objects; nothing above this layer sees a `sqlite3.Row`.",
            "**The interesting method.** `ChunkRepository.allowed_faiss_ids(filters)` resolves "
            "retrieval filters to a set of searchable ids by joining chunks to documents. It returns "
            "`None` when nothing could have been excluded, which lets the vector store take its fast "
            "path — an optimisation that is also a correctness statement.",
        ]
    )

    # ---- ingestion ----
    doc.h2("3.4 ingestion/ — bytes to indexed chunks")
    doc.code(
        """
validate -> store original -> extract -> clean -> metadata -> chunk
         -> injection scan -> embed -> FAISS + BM25 -> registry row
""",
        caption="Nine stages. A document is either fully indexed or not indexed.",
    )

    doc.h3("ingestion/validators.py")
    doc.bullets(
        [
            "**What.** The trust boundary. Filename safety, extension allowlist, size limit, magic-byte "
            "verification.",
            "**Technical detail.** `Path(filename).name` strips any directory component including "
            "traversal sequences; control characters and shell-hostile characters are rejected. PDFs "
            "must start with `%PDF-`; DOCX must start with `PK\\x03\\x04` (it is a zip container). Text "
            "formats have no signature so they are validated by decodability.",
            "**Why both extension and magic bytes.** An extension check alone is trivially spoofed by "
            "renaming a file. There is an integration test that uploads plain text named `fake.pdf`, "
            "asserts a 422, and asserts that **nothing was persisted**.",
        ]
    )

    doc.h3("ingestion/extractors.py")
    doc.bullets(
        [
            "**What.** Per-format text extraction returning `ExtractedDocument` (text, page count, "
            "page offsets).",
            "**Technical detail.** PDFs via `pypdf`, recording a `(char_offset, page_number)` map so a "
            "chunk can report the page it came from. DOCX via `python-docx`, mapping Word heading "
            "styles onto markdown `#` levels so the structure-aware chunker sees them, and flattening "
            "tables into pipe-delimited rows. A PDF with no selectable text raises `ExtractionError` "
            "explaining that scanned documents need OCR, which this service does not perform.",
            "**Why page offsets matter.** A compliance citation that can say 'page 18' is materially "
            "more verifiable than one that cannot. Markdown has no pages, so those fields stay null — "
            "the system never fabricates a page number.",
        ]
    )

    doc.h3("ingestion/cleaning.py")
    doc.bullets(
        [
            "**What.** Whitespace normalisation, horizontal-rule removal, PDF de-hyphenation, repeated "
            "header/footer removal, and a token estimator.",
            "**Technical detail.** Repeated-boilerplate removal counts short lines (3–80 characters) "
            "appearing three or more times and drops them — applied to PDFs only, where running "
            "headers are an artefact rather than content. `estimate_tokens` uses ~1.3 tokens per word, "
            "deliberately an estimate because it is used for context budgeting where ±10% is fine and "
            "loading a tokenizer per chunk is not.",
            "**Why.** In the v1 index, 36 of 46 chunks carried a trailing `---` rule. That is noise in "
            "the embedding and noise in the prompt.",
        ]
    )

    doc.h3("ingestion/metadata.py")
    doc.bullets(
        [
            "**What.** Parses the document header into typed fields: title from `#`, then "
            "`**Version:** 2.1`, `**Effective Date:** 1 January 2025`, `**Owner:** MLRO`, "
            "`**Review Cycle:** Annual`.",
            "**Technical detail.** Only the first 2,500 characters are scanned, so a `**Version:**` "
            "mentioned in the body cannot be mistaken for the document's own version. Eight date "
            "formats are tried, including ordinals ('1st March 2025'). Version falls back to the "
            "filename (`cdd_policy_v2.1.md`). `family_key` strips a trailing version from the title so "
            "v1.9 and v2.1 of the same policy group together. Document type is inferred from title and "
            "filename keywords.",
            "**Why.** v1 discarded all of this. Four features depend on it: metadata filtering, "
            "version-aware answers, conflict detection, and human-readable citations. Anything the "
            "document does not state stays null — nothing is inferred that is not there.",
        ]
    )

    doc.h3("ingestion/chunking.py — the highest-impact module")
    doc.bullets(
        [
            "**What.** Structure-aware chunking: split on `##`, then on `###`, then on paragraphs with "
            "a 60-word overlap, capped at 300 words.",
            "**Technical detail.** Each chunk carries the full heading path (H1 title → H2 section → "
            "H3 subsection). Subsections below 35 words are merged into the preceding sibling, because "
            "a 20-word fragment is a poor retrieval unit. `chunk_uid` is "
            "`sha256(document_id|section|subsection|ordinal|body[:200])[:16]` — content-derived, so "
            "re-ingesting produces identical ids. The header block is stripped before chunking so "
            "version lines are not indexed as prose.",
            "**The 300-word cap is not arbitrary.** BGE-small truncates at 512 tokens. At ~1.3 tokens "
            "per English word, 300 words ≈ 390 tokens, leaving headroom for the provenance header "
            "prepended to every chunk. Exceeding it would mean silently discarding the tail of a "
            "passage at encode time.",
            "**Why the overlap.** A rule straddling a paragraph boundary must be retrievable from "
            "either side. 60 words is enough context to keep a sentence intact.",
        ]
    )
    doc.callout(
        "The single most valuable change in the project",
        "v1 sub-split a section **only when it exceeded 300 words**. So a compact section like "
        "'2. Definitions' containing '2.1 Sanctions' and '2.2 PEP' stayed one chunk labelled §2. The "
        "text was retrievable, but a citation could only ever say 'Section 2', and the labelled ground "
        "truth says §2.1. Splitting on **structure rather than size** lifted recall@5 from 0.782 to "
        "0.948 and MRR from 0.635 to 0.776 — a 21% relative gain from one logic change.",
    )

    doc.h3("ingestion/injection.py")
    doc.bullets(
        [
            "**What.** Nine regex patterns for injection-shaped text: instruction override, role "
            "hijack, prompt leak, citation forgery, guardrail bypass, exfiltration, hidden directives.",
            "**Why it is the weakest of four layers, and said so in the code.** A pattern scanner is "
            "evadable. It exists to **flag** a document for a human, not to guarantee safety. The "
            "layers that actually hold are the prompt's instruction hierarchy, server-side citation "
            "resolution (an injected 'cite policy X' cannot invent a citation), and adversarial cases "
            "in the evaluation set.",
        ]
    )

    doc.h3("ingestion/pipeline.py")
    doc.bullets(
        [
            "**What.** Orchestrates the nine stages, plus `reindex_document`, `delete_document`, "
            "`reconcile`, and `rebuild_all`.",
            "**Failure semantics — worth being able to state precisely.** Any stage failure marks the "
            "registry row `failed` with a reason and leaves the indices untouched. Ingestion writes "
            "vectors then commits the registry row, so a crash leaves orphan vectors, which startup "
            "reconciliation removes. Deletion reverses the order — registry first, then vectors — so a "
            "crash can only ever leave unreferenced vectors, **never a citation pointing at missing "
            "text**.",
            "**`reconcile()`** runs at startup, compares FAISS's id map against the registry, removes "
            "orphans, and rebuilds BM25 if its size disagrees. The registry is the source of truth; "
            "the indices are derived.",
        ]
    )

    # ---- rag ----
    doc.h2("3.5 rag/ — the retrieval and generation core")

    doc.h3("rag/embedder.py")
    doc.bullets(
        [
            "**What.** sentence-transformers wrapper with asymmetric encoding and a process-lifetime cache.",
            "**The asymmetric detail — a likely interview question.** BGE v1.5 is trained with an "
            "instruction prefix on **queries** and bare **passages**. `encode_queries` prepends "
            "'Represent this sentence for searching relevant passages:'; `encode_passages` "
            "deliberately does not. v1 embedded the raw question, leaving measurable quality on the "
            "table for the cost of one line.",
            "**Technical detail.** Vectors are L2-normalised at encode time, which is what makes FAISS "
            "inner-product search equal cosine similarity. Lazy loading means importing the module "
            "does not load a model, so config and chunking tests stay fast.",
        ]
    )

    doc.h3("rag/reranker.py")
    doc.bullets(
        [
            "**What.** Cross-encoder reranking over the fused candidate pool, behind a feature flag.",
            "**Why a cross-encoder beats the bi-encoder.** A bi-encoder compresses a passage into one "
            "vector **before it has seen the query**, so it cannot weigh which part of the passage "
            "matters for this question. A cross-encoder reads query and passage jointly in one forward "
            "pass and scores the pair. That is far more accurate but O(candidates) model calls, which "
            "is why it reranks a shortlist rather than the corpus.",
            "**Technical detail.** `NoopReranker` is a true no-op that does not even reorder, so "
            "`RERANK_ENABLED=false` reproduces the RRF-only baseline exactly. A reranker exception "
            "degrades to the fused ranking and logs a warning — it never fails the query.",
        ]
    )

    doc.h3("rag/query_processing.py")
    doc.bullets(
        [
            "**What.** Normalisation with length guard, follow-up detection, acronym expansion, and the "
            "query-rewrite prompt builder.",
            "**Acronym expansion — note where it is applied.** A dictionary of 17 AML/KYC terms "
            "(PEP, EDD, SDD, CDD, SoW, MLRO, UBO, SAR, FATF, BRP…). Expansions are appended to the "
            "**sparse** query only, because BM25 is literal and will not match 'Enhanced Due "
            "Diligence' for a query saying 'EDD'. The dense embedding is left unperturbed. The "
            "original token survives so a literal match on the acronym itself is not lost.",
            "**Why a dictionary rather than an LLM.** Deterministic, free, instant, unit-testable.",
            "**Follow-up detection is deliberately biased toward false positives.** A needless rewrite "
            "is cheap — the rewrite prompt returns the question unchanged — while a missed rewrite "
            "silently retrieves against an incomplete query, which is the expensive failure.",
        ]
    )

    doc.h3("rag/retrieval.py")
    doc.bullets(
        [
            "**What.** The hybrid retriever: metadata pre-filter → dense + sparse → RRF → rerank → "
            "dedup → trim.",
            "**Why pre-filter rather than post-filter.** Filtering after ranking would silently return "
            "fewer than k results, and a superseded policy must not be retrievable as a current rule. "
            "Filtering first means k means k.",
            "**Deduplication.** Exact content-hash drop, then token-set Jaccard similarity ≥ 0.97, "
            "keeping the better-ranked copy. Jaccard rather than embeddings because it is free, "
            "deterministic, and at chunk granularity it catches exactly the overlap-induced repetition "
            "that matters.",
            "**Diagnostics.** Every retrieval logs dense/sparse hit counts, **leg overlap**, top score "
            "per leg, duplicates dropped, and whether a filter was active. Measured leg overlap on the "
            "golden set is 17–27 of 30 candidates, which is the evidence that the two legs genuinely "
            "disagree and the fusion is doing real work.",
        ]
    )

    doc.h3("rag/context.py")
    doc.bullets(
        [
            "**What.** Token-budgeted context selection with paragraph-boundary truncation.",
            "**Why it is a stage rather than 'take top k'.** Latency and cost scale with context "
            "length, and long contexts degrade attention to the middle of the list. The top-ranked "
            "chunk is always included even if it alone exceeds the budget — truncated to fit — because "
            "returning no context at all because the best passage is long would be worse.",
        ]
    )

    doc.h3("rag/prompts.py")
    doc.bullets(
        [
            "**What.** Versioned prompt templates: shared rules, a JSON-output variant, a marker-output "
            "variant, a repair prompt, a query-rewrite prompt, and the context block builder.",
            "**The six enforced rules.** Grounding (only supplied passages); explicit refusal with the "
            "documented escalation path; no fabrication of sections, thresholds or document names; "
            "conflicts stated rather than resolved; precision (exact figures, conditions and "
            "exceptions included); and an **instruction hierarchy** stating that passages are untrusted "
            "reference data, so text inside a document that looks like an instruction is content to be "
            "reported, not obeyed.",
            "**Context block detail.** Each passage is rendered with its id, document title, version, "
            "effective date, section, page and filename. Provenance is repeated in the header line "
            "(not only inside the chunk text) because a model that can see the real title and section "
            "is far less likely to guess at them.",
            "**Why prompts live in code.** The prompt is the primary hallucination control. It belongs "
            "in versioned, reviewable, testable code rather than scattered f-strings.",
        ]
    )

    doc.h3("rag/llm.py")
    doc.bullets(
        [
            "**What.** An abstract `LLMProvider` with `GroqProvider` and `OllamaProvider`, plus a "
            "factory driven by one environment variable.",
            "**Four methods.** `generate_json` (JSON mode, used by the CLI, non-streaming API and "
            "evaluation), `stream_text` (the chat path), `health` (cheap check for readiness), "
            "`last_usage` (token counts).",
            "**Token usage is reported as null, never estimated.** Groq reports usage on the terminal "
            "stream chunk — either directly or nested under `x_groq` depending on SDK version, and both "
            "are checked. Ollama reports `prompt_eval_count`/`eval_count`. When a provider reports "
            "nothing, the field is null, because a guessed token count in a cost dashboard is worse "
            "than no count.",
            "**Why a thin transport wrapper.** Schema validation and citation resolution happen in the "
            "pipeline, not here. That is what keeps providers genuinely interchangeable — and it is why "
            "recovering from a model deprecation was a one-line change.",
        ]
    )

    doc.h3("rag/citations.py — the most important module in the project")
    doc.bullets(
        [
            "**What.** `CitationResolver`, `resolve_used_ids` (JSON mode), `resolve_markers` (complete "
            "string), and `MarkerStreamParser` (incremental).",
            "**The invariant.** A citation can only ever point at a chunk the retriever actually "
            "returned. The resolver is constructed from the retrieved set; any id not in it is recorded "
            "as fabricated and dropped, and in marker mode the marker is removed from the text "
            "entirely so a fabricated reference leaves no trace.",
            "**Display indices follow order of first appearance**, so the prose reads `[1]`, `[2]`, "
            "`[3]` naturally regardless of which internal chunk ids the model emitted.",
            "**`MarkerStreamParser` is the awkward part.** A marker can be split across arbitrary token "
            "boundaries, so the parser holds back any trailing text that is still a proper prefix of a "
            "complete marker. Markers inside fenced code blocks are left untouched, because a code "
            "sample containing the syntax is content.",
        ]
    )
    doc.callout(
        "A real bug here, found by a test — worth telling as a story",
        "The partial-marker guard initially held back `[[cid:1` but **not** `[[cid:10]` — a prefix that "
        "had already reached the first closing bracket. So when a token boundary fell between the two "
        "closing brackets, a raw `[[cid:10]]` leaked into the visible answer while the citation still "
        "resolved correctly. An integration test caught it; it is now pinned by a parametrised test "
        "across six different split positions including character-by-character.",
    )

    doc.h3("rag/guardrails.py")
    doc.bullets(
        [
            "**What.** Refusal detection, the evidence floor gate, evidence banding, and structural "
            "conflict detection.",
            "**`has_sufficient_evidence`** is the retrieval-level refusal gate: if the best passage "
            "scores below the floor, the pipeline returns the refusal response and **never asks the "
            "model for an answer**. Refusal must not depend on the model choosing to refuse.",
            "**`compute_evidence`** produces a band from six observable signals: top score, margin over "
            "the next passage, supporting passage count, distinct document count, cited fraction of "
            "context, and whether the answer is a refusal.",
            "**`detect_conflicts`** groups retrieved chunks by document family and flags any family "
            "with differing version or effective date. Version ordering is numeric, so `v2.10 > v1.9` — "
            "string comparison would get that backwards.",
            "**Refusal detection is pattern-based and therefore imperfect**, which is exactly why "
            "refusal accuracy is a reported metric split into correct refusals and over-refusals rather "
            "than an assumed property.",
        ]
    )

    doc.h3("rag/pipeline.py")
    doc.bullets(
        [
            "**What.** `RagPipeline.answer()` (JSON mode) and `answer_stream()` (marker mode) over "
            "identical retrieval and guardrails.",
            "**The contract.** Every code path — including every failure path — produces the same "
            "result shape. Nothing raises past this boundary and nothing prints. Errors surface in the "
            "`error` field.",
            "**Dependencies are injected** (retriever, provider factory, settings) rather than "
            "constructed inline. That is what lets unit tests run with a fake embedder and fake LLM in "
            "milliseconds, and what lets the evaluation harness exercise this exact code.",
            "**The repair retry.** One normal JSON attempt, then one stricter repair attempt, then a "
            "typed error. Preserved from v1 because slightly malformed JSON is common enough to be "
            "worth one retry, and a second failure is a real error worth surfacing.",
            "**Streaming event order is fixed:** `meta` → `retrieval` → `token`* → `citations` → "
            "`evidence` → `conflicts`? → `done`. The `done` payload carries the complete result so the "
            "caller can persist and audit without reassembling the stream.",
        ]
    )


def main() -> int:
    doc = Doc()
    doc.title_page()
    doc.h1("Contents", page_break=True)
    doc.toc()
    part_how_to_use(doc)
    part_problem(doc)
    part_architecture(doc)
    part_modules(doc)
    # Remaining parts are appended by generate_project_doc_part2.
    from generate_project_doc_part2 import append_remaining_parts

    append_remaining_parts(doc)
    path = doc.save()
    print(f"Written: {path}")
    print(f"Size: {path.stat().st_size / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    raise SystemExit(main())
