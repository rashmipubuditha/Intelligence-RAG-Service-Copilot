"""Retrieval and generation metrics — exact arithmetic, no LLM, no dependencies.

README DR-9 explains why these are written rather than imported from RAGAS/DeepEval: the
formulas are ~150 lines, writing them keeps every metric inspectable, they run offline in CI,
and being able to explain exactly how a number was computed is the point of the exercise.

Ground truth is expressed as *section numbers* ("3.1", "4") rather than full heading text, so
a reworded heading does not silently invalidate the dataset. A retrieved chunk counts as
relevant when its document matches AND its section (or subsection) number matches.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

_SECTION_NUMBER = re.compile(r"^\s*(\d+(?:\.\d+)*)")


def section_number(label: str | None) -> str | None:
    """'3.1 Employment / Salary' → '3.1'. Returns None when a heading is unnumbered."""
    if not label:
        return None
    match = _SECTION_NUMBER.match(label)
    return match.group(1) if match else None


def normalise_document(name: str) -> str:
    return (name or "").strip().lower()


@dataclass
class RetrievedRef:
    """What a retrieval returned, reduced to the fields metrics care about."""

    document_name: str
    section: str | None = None
    subsection: str | None = None

    @property
    def numbers(self) -> set[str]:
        """Section numbers this chunk can satisfy.

        A chunk from subsection 3.1 also satisfies an expectation of section 3 — the rule the
        question asks about genuinely lives there.
        """
        out: set[str] = set()
        for label in (self.subsection, self.section):
            number = section_number(label)
            if not number:
                continue
            out.add(number)
            parts = number.split(".")
            for i in range(1, len(parts)):
                out.add(".".join(parts[:i]))
        return out


@dataclass
class ExpectedRef:
    document_name: str
    sections: list[str] = field(default_factory=list)

    def matches(self, retrieved: RetrievedRef) -> bool:
        if normalise_document(retrieved.document_name) != normalise_document(self.document_name):
            return False
        if not self.sections:
            return True  # document-level ground truth
        return bool(self.numbers & retrieved.numbers)

    @property
    def numbers(self) -> set[str]:
        return {s.strip() for s in self.sections if s.strip()}


def expand_expected(
    relevant_documents: Sequence[str], relevant_sections: Sequence[str] | None
) -> list[ExpectedRef]:
    """Build expectations from a dataset record.

    `relevant_sections` entries may be plain ("3.1", applies to every listed document) or
    qualified ("02:3.1", applies to one document) — qualification matters for multi-document
    questions where each document contributes a different section.
    """
    sections = list(relevant_sections or [])
    qualified: dict[str, list[str]] = {}
    unqualified: list[str] = []

    for entry in sections:
        if ":" in entry:
            prefix, number = entry.split(":", 1)
            qualified.setdefault(prefix.strip(), []).append(number.strip())
        else:
            unqualified.append(entry.strip())

    expected: list[ExpectedRef] = []
    for document in relevant_documents:
        doc_sections = list(unqualified)
        for prefix, numbers in qualified.items():
            if document.startswith(prefix) or prefix in document:
                doc_sections.extend(numbers)
        expected.append(ExpectedRef(document_name=document, sections=doc_sections))
    return expected


# ---------------------------------------------------------------------------
# Retrieval metrics
# ---------------------------------------------------------------------------


def relevance_vector(retrieved: Sequence[RetrievedRef], expected: Sequence[ExpectedRef]) -> list[int]:
    """1 where the retrieved chunk at that rank satisfies any expectation."""
    return [1 if any(exp.matches(ref) for exp in expected) else 0 for ref in retrieved]


def recall_at_k(retrieved: Sequence[RetrievedRef], expected: Sequence[ExpectedRef], k: int) -> float:
    """Fraction of *expectations* covered by the top k. This is the ceiling on answer
    quality — the model cannot use what was never retrieved."""
    if not expected:
        return 1.0
    window = retrieved[:k]
    covered = sum(1 for exp in expected if any(exp.matches(ref) for ref in window))
    return covered / len(expected)


def precision_at_k(retrieved: Sequence[RetrievedRef], expected: Sequence[ExpectedRef], k: int) -> float:
    """Fraction of the top k that are relevant — measures context pollution."""
    window = retrieved[:k]
    if not window:
        return 0.0
    return sum(relevance_vector(window, expected)) / len(window)


def reciprocal_rank(retrieved: Sequence[RetrievedRef], expected: Sequence[ExpectedRef]) -> float:
    """1/rank of the first relevant chunk; 0 if none. Rewards putting the right passage first."""
    for index, ref in enumerate(retrieved, start=1):
        if any(exp.matches(ref) for exp in expected):
            return 1.0 / index
    return 0.0


def hit_rate(retrieved: Sequence[RetrievedRef], expected: Sequence[ExpectedRef], k: int) -> float:
    return 1.0 if any(relevance_vector(retrieved[:k], expected)) else 0.0


def ndcg_at_k(retrieved: Sequence[RetrievedRef], expected: Sequence[ExpectedRef], k: int) -> float:
    """Binary-gain nDCG: rank-discounted, so ordering is rewarded.

    The ideal ranking places all relevant chunks first. The ideal count is the greater of
    "how many expectations exist" and "how many relevant chunks were actually found", capped
    at k — because ground truth here is section-level while retrieval is chunk-level, so two
    chunks can legitimately satisfy one expectation. Taking only `len(expected)` as the ideal
    would let nDCG exceed 1.0 in exactly that case.
    """
    gains = relevance_vector(retrieved[:k], expected)
    dcg = sum(gain / math.log2(rank + 1) for rank, gain in enumerate(gains, start=1))
    ideal_hits = min(k, max(len(expected), sum(gains)))
    idcg = sum(1 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / idcg if idcg else 0.0


def document_accuracy(retrieved: Sequence[RetrievedRef], expected: Sequence[ExpectedRef]) -> float:
    """Did we retrieve the right document(s), ignoring section precision?"""
    if not expected:
        return 1.0
    expected_docs = {normalise_document(e.document_name) for e in expected}
    retrieved_docs = {normalise_document(r.document_name) for r in retrieved}
    return len(expected_docs & retrieved_docs) / len(expected_docs)


def section_accuracy(retrieved: Sequence[RetrievedRef], expected: Sequence[ExpectedRef]) -> float:
    """Right document *and* right section — the metric the subsection-provenance fix
    (README D1) makes measurable at all."""
    sectioned = [e for e in expected if e.numbers]
    if not sectioned:
        return 1.0
    hits = sum(1 for exp in sectioned if any(exp.matches(ref) for ref in retrieved))
    return hits / len(sectioned)


def retrieval_metrics(
    retrieved: Sequence[RetrievedRef],
    expected: Sequence[ExpectedRef],
    ks: Iterable[int] = (1, 3, 5, 10),
) -> dict[str, float]:
    out: dict[str, float] = {}
    for k in ks:
        out[f"recall@{k}"] = round(recall_at_k(retrieved, expected, k), 4)
        out[f"precision@{k}"] = round(precision_at_k(retrieved, expected, k), 4)
        out[f"hit_rate@{k}"] = round(hit_rate(retrieved, expected, k), 4)
    out["mrr"] = round(reciprocal_rank(retrieved, expected), 4)
    out["ndcg@5"] = round(ndcg_at_k(retrieved, expected, 5), 4)
    out["document_accuracy"] = round(document_accuracy(retrieved, expected), 4)
    out["section_accuracy"] = round(section_accuracy(retrieved, expected), 4)
    return out


# ---------------------------------------------------------------------------
# Generation metrics (deterministic)
# ---------------------------------------------------------------------------


def citation_metrics(cited: Sequence[RetrievedRef], expected: Sequence[ExpectedRef]) -> dict[str, float]:
    """Precision/recall of the citations the answer actually carried.

    This is stricter than retrieval recall: a passage can be retrieved and still not cited.
    """
    if not cited:
        return {"citation_precision": 0.0, "citation_recall": 0.0, "citation_count": 0}
    relevant = relevance_vector(cited, expected)
    precision = sum(relevant) / len(cited)
    recall = (
        sum(1 for exp in expected if any(exp.matches(ref) for ref in cited)) / len(expected)
        if expected
        else 1.0
    )
    return {
        "citation_precision": round(precision, 4),
        "citation_recall": round(recall, 4),
        "citation_count": len(cited),
    }


def keyword_compliance(answer: str, must_include: Sequence[str]) -> dict[str, Any]:
    """Coarse but exact: did the answer state the things the ground truth requires?"""
    if not must_include:
        return {"keyword_score": 1.0, "missing_keywords": []}
    lowered = answer.lower()
    missing = [kw for kw in must_include if kw.lower() not in lowered]
    return {
        "keyword_score": round((len(must_include) - len(missing)) / len(must_include), 4),
        "missing_keywords": missing,
    }


def forbidden_content(answer: str, must_not_include: Sequence[str]) -> dict[str, Any]:
    """Catches the adversarial cases: content that must never appear in an answer."""
    if not must_not_include:
        return {"forbidden_violations": [], "forbidden_clean": True}
    lowered = answer.lower()
    violations = [kw for kw in must_not_include if kw.lower() in lowered]
    return {"forbidden_violations": violations, "forbidden_clean": not violations}


_NUMBER = re.compile(r"\b\d+(?:[.,]\d+)?\s*(?:%|months?|years?|days?|hours?|points?)?\b", re.I)


def numeric_accuracy(answer: str, expected_numbers: Sequence[str]) -> dict[str, Any]:
    """The worst compliance failure mode is a right-sounding wrong number, so figures are
    checked explicitly rather than hoping a keyword check catches them."""
    if not expected_numbers:
        return {"numeric_score": 1.0, "missing_numbers": []}
    lowered = answer.lower()
    missing = [n for n in expected_numbers if n.lower() not in lowered]
    return {
        "numeric_score": round((len(expected_numbers) - len(missing)) / len(expected_numbers), 4),
        "missing_numbers": missing,
    }


def refusal_correctness(refused: bool, should_refuse: bool) -> dict[str, Any]:
    """Split, not merged: a system that refuses everything would score well on a single
    'refusal accuracy' number, so correct refusals and over-refusals are reported apart."""
    return {
        "refusal_correct": refused == should_refuse,
        "correct_refusal": refused and should_refuse,
        "over_refusal": refused and not should_refuse,
        "missed_refusal": (not refused) and should_refuse,
    }


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def aggregate(per_question: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Mean every numeric metric; count every boolean. Also breaks results down by category,
    because an aggregate that hides a failing category is misleading."""
    if not per_question:
        return {}

    numeric_keys: set[str] = set()
    boolean_keys: set[str] = set()
    for row in per_question:
        for key, value in row.get("metrics", {}).items():
            if isinstance(value, bool):
                boolean_keys.add(key)
            elif isinstance(value, (int, float)):
                numeric_keys.add(key)

    def mean(key: str, rows: Sequence[dict[str, Any]]) -> float | None:
        values = [
            row["metrics"][key]
            for row in rows
            if key in row.get("metrics", {})
            and isinstance(row["metrics"][key], (int, float))
            and not isinstance(row["metrics"][key], bool)
        ]
        return round(sum(values) / len(values), 4) if values else None

    summary: dict[str, Any] = {"n_questions": len(per_question)}
    for key in sorted(numeric_keys):
        value = mean(key, per_question)
        if value is not None:
            summary[key] = value
    for key in sorted(boolean_keys):
        trues = sum(1 for row in per_question if row.get("metrics", {}).get(key) is True)
        summary[f"{key}_count"] = trues
        summary[f"{key}_rate"] = round(trues / len(per_question), 4)

    by_category: dict[str, Any] = {}
    categories = {row.get("category", "uncategorised") for row in per_question}
    for category in sorted(categories):
        rows = [r for r in per_question if r.get("category", "uncategorised") == category]
        entry: dict[str, Any] = {"n": len(rows)}
        for key in ("recall@5", "precision@3", "mrr", "ndcg@5", "section_accuracy", "citation_precision"):
            value = mean(key, rows)
            if value is not None:
                entry[key] = value
        entry["refusal_correct_rate"] = round(
            sum(1 for r in rows if r.get("metrics", {}).get("refusal_correct") is True) / len(rows), 4
        )
        by_category[category] = entry
    summary["by_category"] = by_category

    return summary
