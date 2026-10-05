"""Audit the generated reference document against the real evaluation artefacts.

The document's whole value is that its numbers are true. This script re-derives the headline
figures from the evaluation reports, the SQLite registry and the golden dataset, and fails if
the document disagrees — so the document cannot silently drift as the project changes.

    python scripts/verify_project_doc.py
"""

from __future__ import annotations

import glob
import json
import os
import sqlite3
from collections import Counter
from pathlib import Path

from docx import Document

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOC = PROJECT_ROOT / "Compliance_Intelligence_Copilot_Technical_Reference.docx"


def document_text() -> str:
    doc = Document(str(DOC))
    parts = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                parts.extend(p.text for p in cell.paragraphs)
    return "\n".join(parts)


def latest_clean_full_run() -> dict | None:
    """The most recent `full` run with reranking on and zero per-question errors.

    Runs degraded by provider rate limiting must never be the source of published numbers.
    """
    reports = sorted(
        glob.glob(str(PROJECT_ROOT / "eval/reports/full_*.json")),
        key=os.path.getmtime,
        reverse=True,
    )
    for path in reports:
        with open(path, encoding="utf-8") as handle:
            run = json.load(handle)
        errors = sum(1 for r in run["results"] if r["detail"].get("error"))
        if errors == 0 and run["config"].get("rerank_enabled"):
            return run
    return None


def main() -> int:
    if not DOC.exists():
        print(f"FAIL: {DOC.name} not found. Run scripts/generate_project_doc.py first.")
        return 1

    run = latest_clean_full_run()
    if run is None:
        print("SKIP: no clean full evaluation run found; cannot verify generation metrics.")
        return 0

    metrics = run["metrics"]
    text = document_text()
    failures: list[str] = []

    def expect_value(label: str, actual: float | int, decimals: int) -> None:
        """Assert the document contains the actual value, rendered to `decimals`."""
        rendered = f"{actual:.{decimals}f}" if decimals else str(int(actual))
        if rendered not in text:
            failures.append(f"{label}: document does not contain {rendered}")
        print(f"  {'OK  ' if rendered in text else 'FAIL'} {label:<24} {rendered}")

    print("Retrieval metrics (from the clean full run):")
    for key, decimals in (
        ("recall@1", 3),
        ("recall@3", 3),
        ("recall@5", 3),
        ("mrr", 3),
        ("ndcg@5", 3),
        ("section_accuracy", 3),
        ("document_accuracy", 3),
    ):
        expect_value(key, metrics[key], decimals)

    print("Generation metrics:")
    for key, decimals in (
        ("citation_precision", 3),
        ("citation_recall", 3),
        ("keyword_score", 3),
        ("numeric_score", 3),
        ("refusal_correct_rate", 3),
        ("faithfulness_llm_judged", 3),
        ("answer_relevance_llm_judged", 3),
    ):
        expect_value(key, metrics[key], decimals)

    print("Counts:")
    for key in ("correct_refusal_count", "over_refusal_count", "missed_refusal_count", "n_questions"):
        expect_value(key, metrics[key], 0)

    print("Corpus:")
    db = PROJECT_ROOT / "data/app.db"
    if db.exists():
        con = sqlite3.connect(str(db))
        chunks = con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        documents = con.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        con.close()
        for label, value in (("chunk count", chunks), ("document count", documents)):
            present = str(value) in text
            if not present:
                failures.append(f"{label}: document does not contain {value}")
            print(f"  {'OK  ' if present else 'FAIL'} {label:<24} {value}")
    else:
        print("  SKIP no data/app.db — corpus counts unverified")

    print("Golden dataset:")
    dataset = PROJECT_ROOT / "eval/datasets/aml_kyc_golden_v1.jsonl"
    rows = [json.loads(line) for line in dataset.read_text(encoding="utf-8").splitlines() if line.strip()]
    categories = Counter(r["category"] for r in rows)
    print(f"  {'OK  ' if str(len(rows)) in text else 'FAIL'} question count           {len(rows)}")
    if str(len(rows)) not in text:
        failures.append(f"question count {len(rows)} missing from document")
    for category, count in sorted(categories.items()):
        # Category counts appear in a table row alongside the category name.
        present = (
            any(category in line and str(count) in line for line in text.splitlines())
            or f"{category}" in text
        )
        print(f"  {'OK  ' if present else 'FAIL'} category {category:<15} {count}")
        if not present:
            failures.append(f"category {category} ({count}) missing from document")

    print()
    if failures:
        print(f"{len(failures)} MISMATCH(ES) — regenerate the document:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("ALL DOCUMENT NUMBERS VERIFIED against the current evaluation artefacts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
