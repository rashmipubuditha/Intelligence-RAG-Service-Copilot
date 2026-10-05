"""Evaluation runner.

    python -m eval.run --mode retrieval_only    # seconds, no LLM, CI gate
    python -m eval.run --mode full              # + generation + LLM judge
    python -m eval.run --rerank true --top-k 8  # parameter sweep inputs

`retrieval_only` is the mode that matters for iteration speed: it exercises the real
retrieval stack (same code the API uses) with no LLM in the loop, so it is deterministic,
free, offline, and fast enough to gate every commit.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.container import AppContainer  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.logging import configure_logging  # noqa: E402
from app.rag.pipeline import AskOptions  # noqa: E402

from eval.metrics import (  # noqa: E402
    RetrievedRef,
    aggregate,
    citation_metrics,
    expand_expected,
    forbidden_content,
    keyword_compliance,
    numeric_accuracy,
    refusal_correctness,
    retrieval_metrics,
)

DATASETS_DIR = Path(__file__).parent / "datasets"
REPORTS_DIR = Path(__file__).parent / "reports"


def load_dataset(name: str) -> list[dict[str, Any]]:
    path = DATASETS_DIR / (name if name.endswith(".jsonl") else f"{name}.jsonl")
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {path}")
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path.name} line {line_number} is not valid JSON: {exc}") from exc
    return rows


def _refs_from_chunks(chunks: list[Any]) -> list[RetrievedRef]:
    return [
        RetrievedRef(
            document_name=rc.chunk.metadata.document_name,
            section=rc.chunk.metadata.section,
            subsection=rc.chunk.metadata.subsection,
        )
        for rc in chunks
    ]


def _refs_from_citations(citations: list[Any]) -> list[RetrievedRef]:
    return [
        RetrievedRef(document_name=c.document, section=c.section, subsection=c.subsection) for c in citations
    ]


def evaluate_question(
    *,
    container: AppContainer,
    record: dict[str, Any],
    mode: str,
    top_k: int,
    judge_provider: Any | None = None,
) -> dict[str, Any]:
    question = record["question"]
    history = [(role, content) for role, content in record.get("history", [])]
    expected = expand_expected(record.get("relevant_documents", []), record.get("relevant_sections", []))
    should_refuse = bool(record.get("should_refuse", False))

    metrics_out: dict[str, Any] = {}
    detail: dict[str, Any] = {}
    started = time.perf_counter()

    if mode == "retrieval_only":
        # Rewriting needs an LLM, so for follow-ups in retrieval-only mode the history is
        # folded into the search text instead. Stated here because it means follow-up
        # retrieval numbers in this mode are an approximation of the live path.
        search_text = question
        if history:
            previous_user = [content for role, content in history if role == "user"]
            if previous_user:
                search_text = f"{previous_user[-1]} {question}"
        outcome = container.retriever.retrieve(search_text, k=top_k)
        retrieved_refs = _refs_from_chunks(outcome.chunks)
        metrics_out.update(retrieval_metrics(retrieved_refs, expected))
        metrics_out["retrieval_ms"] = outcome.retrieval_ms
        metrics_out["rerank_ms"] = outcome.rerank_ms
        detail["retrieved"] = [
            {
                "document": ref.document_name,
                "section": ref.section,
                "subsection": ref.subsection,
                "score": round(rc.normalised_score, 4),
            }
            for ref, rc in zip(retrieved_refs, outcome.chunks, strict=True)
        ]
        detail["search_text"] = search_text
    else:
        result = container.rag.answer(
            question, AskOptions(k=top_k, history=history, rewrite_followups=bool(history))
        )
        retrieved_refs = _refs_from_chunks(result.retrieved)
        cited_refs = _refs_from_citations(result.citations)

        metrics_out.update(retrieval_metrics(retrieved_refs, expected))
        metrics_out.update(citation_metrics(cited_refs, expected))
        metrics_out.update(keyword_compliance(result.answer, record.get("must_include", [])))
        metrics_out.update(forbidden_content(result.answer, record.get("must_not_include", [])))
        metrics_out.update(numeric_accuracy(result.answer, record.get("expected_numbers", [])))
        metrics_out.update(refusal_correctness(result.refused, should_refuse))
        metrics_out["retrieval_ms"] = result.timings.retrieval_ms
        metrics_out["rerank_ms"] = result.timings.rerank_ms
        metrics_out["llm_ms"] = result.timings.llm_ms
        metrics_out["total_ms"] = result.timings.total_ms
        metrics_out["evidence_band_is_insufficient"] = result.evidence.band == "insufficient"

        detail.update(
            {
                "answer": result.answer,
                "rewritten_question": result.rewritten_question,
                "evidence_band": result.evidence.band,
                "model": result.model,
                "error": result.error,
                "citations": [
                    {"label": c.label, "document": c.document, "section": c.subsection or c.section}
                    for c in result.citations
                ],
                "retrieved": [
                    {"document": r.document_name, "section": r.subsection or r.section}
                    for r in retrieved_refs
                ],
            }
        )

        if judge_provider is not None and result.answer and not result.error:
            from eval.judges import judge_faithfulness, judge_relevance

            context = "\n\n---\n\n".join(rc.chunk.text for rc in result.retrieved)
            try:
                verdict = judge_faithfulness(judge_provider, answer=result.answer, context=context)
                metrics_out["faithfulness_llm_judged"] = verdict.score
                detail["faithfulness_claims"] = [c.model_dump() for c in verdict.claims]
            except Exception as exc:
                detail["faithfulness_error"] = str(exc)
            try:
                relevance = judge_relevance(
                    judge_provider,
                    question=question,
                    reference=record.get("expected_answer", ""),
                    candidate=result.answer,
                )
                metrics_out["answer_relevance_llm_judged"] = relevance.normalised
                detail["relevance_reason"] = relevance.reason
            except Exception as exc:
                detail["relevance_error"] = str(exc)

    return {
        "question_id": record["id"],
        "question": question,
        "category": record.get("category", "uncategorised"),
        "should_refuse": should_refuse,
        "expected_documents": record.get("relevant_documents", []),
        "expected_sections": record.get("relevant_sections", []),
        "metrics": metrics_out,
        "detail": detail,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }


def run_evaluation(
    *,
    dataset: str = "aml_kyc_golden_v1",
    mode: str = "retrieval_only",
    top_k: int | None = None,
    rerank: bool | None = None,
    judge: bool = False,
    limit: int | None = None,
    categories: list[str] | None = None,
    container: AppContainer | None = None,
    persist: bool = True,
    progress: bool = False,
) -> dict[str, Any]:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    container = container or AppContainer(settings)

    if rerank is not None:
        container.overrides.rerank_enabled = rerank
    effective_k = top_k or container.effective_settings.retrieval_top_k

    records = load_dataset(dataset)
    if categories:
        records = [r for r in records if r.get("category") in categories]
    if limit:
        records = records[:limit]
    if not records:
        raise ValueError("The dataset selection produced no questions.")

    if container.chunks.count() == 0:
        raise RuntimeError(
            "Nothing is indexed. Run `python main.py ingest --docs ./policies` before evaluating."
        )

    judge_provider = None
    if judge and mode == "full":
        judge_provider = container.provider_factory()

    config = {
        "dataset": dataset,
        "mode": mode,
        "top_k": effective_k,
        "candidate_pool": container.effective_settings.retrieval_candidate_pool,
        "rrf_k": container.settings.rrf_k,
        "rerank_enabled": container.effective_settings.rerank_enabled,
        "rerank_model": container.settings.rerank_model
        if container.effective_settings.rerank_enabled
        else None,
        "embedding_model": container.settings.embedding_model,
        "llm_model": container.effective_settings.active_model_name if mode == "full" else None,
        "judge_enabled": judge_provider is not None,
        "chunks_indexed": container.chunks.count(),
    }

    run_id = container.evals.create_run(dataset, mode, config, len(records)) if persist else "dry-run"
    started = time.perf_counter()
    results: list[dict[str, Any]] = []

    try:
        for position, record in enumerate(records, start=1):
            result = evaluate_question(
                container=container,
                record=record,
                mode=mode,
                top_k=effective_k,
                judge_provider=judge_provider,
            )
            results.append(result)
            if persist:
                container.evals.add_result(run_id, record["id"], result)
            if progress:
                recall = result["metrics"].get("recall@5", 0.0)
                print(
                    f"  [{position:>3}/{len(records)}] {record['id']} {record['category']:<12} "
                    f"recall@5={recall:.2f} ({result['elapsed_ms']} ms)",
                    file=sys.stderr,
                )

        summary = aggregate(results)
        summary["config"] = config
        summary["elapsed_s"] = round(time.perf_counter() - started, 2)
        if persist:
            container.evals.finish_run(run_id, summary)
    except Exception as exc:
        if persist:
            container.evals.finish_run(run_id, {}, status="failed", error=str(exc))
        raise

    return {"run_id": run_id, "config": config, "metrics": summary, "results": results}


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def render_markdown(report: dict[str, Any]) -> str:
    metrics = report["metrics"]
    config = report["config"]
    lines = [
        "# Evaluation report",
        "",
        f"- **Run id:** `{report['run_id']}`",
        f"- **Dataset:** {config['dataset']} ({metrics.get('n_questions', 0)} questions)",
        f"- **Mode:** {config['mode']}",
        f"- **Embedding model:** `{config['embedding_model']}`",
        f"- **Reranking:** {'on — ' + str(config['rerank_model']) if config['rerank_enabled'] else 'off'}",
        f"- **top_k:** {config['top_k']} · **candidate pool:** {config['candidate_pool']} · "
        f"**rrf_k:** {config['rrf_k']}",
        f"- **Elapsed:** {metrics.get('elapsed_s', 0)} s",
        "",
        "## Retrieval (deterministic)",
        "",
        "| Metric | Value |",
        "| --- | --- |",
    ]
    for key in (
        "recall@1",
        "recall@3",
        "recall@5",
        "recall@10",
        "precision@3",
        "precision@5",
        "mrr",
        "ndcg@5",
        "hit_rate@5",
        "document_accuracy",
        "section_accuracy",
    ):
        if key in metrics:
            lines.append(f"| {key} | {metrics[key]:.4f} |")

    generation_keys = [
        ("citation_precision", "Citation precision"),
        ("citation_recall", "Citation recall"),
        ("keyword_score", "Keyword compliance"),
        ("numeric_score", "Numeric accuracy"),
        ("refusal_correct_rate", "Refusal accuracy"),
        ("correct_refusal_count", "Correct refusals"),
        ("over_refusal_count", "Over-refusals"),
        ("missed_refusal_count", "Missed refusals"),
        ("forbidden_clean_rate", "Forbidden-content clean rate"),
    ]
    if any(key in metrics for key, _ in generation_keys):
        lines += ["", "## Generation (deterministic)", "", "| Metric | Value |", "| --- | --- |"]
        for key, label in generation_keys:
            if key in metrics:
                value = metrics[key]
                rendered = f"{value:.4f}" if isinstance(value, float) else str(value)
                lines.append(f"| {label} | {rendered} |")

    judged = [(k, v) for k, v in metrics.items() if k.endswith("_llm_judged")]
    if judged:
        lines += [
            "",
            "## Generation (LLM-judged — indicative, not ground truth)",
            "",
            "| Metric | Value |",
            "| --- | --- |",
        ]
        for key, value in judged:
            lines.append(f"| {key.replace('_llm_judged', '')} | {value:.4f} |")

    if "by_category" in metrics:
        lines += [
            "",
            "## By category",
            "",
            "| Category | n | recall@5 | precision@3 | MRR | nDCG@5 | section acc. | refusal acc. |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for category, row in metrics["by_category"].items():
            lines.append(
                f"| {category} | {row['n']} | {_fmt(row.get('recall@5'))} | "
                f"{_fmt(row.get('precision@3'))} | {_fmt(row.get('mrr'))} | "
                f"{_fmt(row.get('ndcg@5'))} | {_fmt(row.get('section_accuracy'))} | "
                f"{_fmt(row.get('refusal_correct_rate'))} |"
            )

    failures = [r for r in report["results"] if (r["metrics"].get("recall@5", 1.0) or 0) < 1.0]
    if failures:
        lines += ["", f"## Incomplete retrieval ({len(failures)} questions)", ""]
        for row in failures[:15]:
            lines.append(
                f"- **{row['question_id']}** ({row['category']}, recall@5="
                f"{row['metrics'].get('recall@5', 0):.2f}): {row['question'][:110]}"
            )
            lines.append(f"  - expected: {row['expected_documents']} {row['expected_sections']}")
            retrieved = row["detail"].get("retrieved", [])[:3]
            lines.append(f"  - retrieved: {retrieved}")

    return "\n".join(lines) + "\n"


def _fmt(value: Any) -> str:
    return f"{value:.3f}" if isinstance(value, (int, float)) else "–"


def write_reports(report: dict[str, Any]) -> tuple[Path, Path]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"{report['config']['mode']}_{report['run_id']}"
    json_path = REPORTS_DIR / f"{stem}.json"
    md_path = REPORTS_DIR / f"{stem}.md"
    json_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the RAG evaluation harness.")
    parser.add_argument("--dataset", default="aml_kyc_golden_v1")
    parser.add_argument("--mode", choices=["retrieval_only", "full"], default="retrieval_only")
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument("--rerank", choices=["true", "false"], default=None, help="Override RERANK_ENABLED.")
    parser.add_argument("--judge", action="store_true", help="Add LLM-judged metrics (full mode).")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--categories", default=None, help="Comma-separated category filter.")
    parser.add_argument("--min-recall-at-5", type=float, default=None, help="CI gate threshold.")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    report = run_evaluation(
        dataset=args.dataset,
        mode=args.mode,
        top_k=args.top_k,
        rerank=None if args.rerank is None else args.rerank == "true",
        judge=args.judge,
        limit=args.limit,
        categories=args.categories.split(",") if args.categories else None,
        progress=not args.quiet,
    )

    json_path, md_path = write_reports(report)
    metrics = report["metrics"]

    print(render_markdown(report))
    print(f"Reports written to:\n  {json_path}\n  {md_path}", file=sys.stderr)

    if args.min_recall_at_5 is not None:
        actual = metrics.get("recall@5", 0.0)
        if actual < args.min_recall_at_5:
            print(
                f"FAIL: recall@5 {actual:.4f} is below the gate {args.min_recall_at_5:.4f}",
                file=sys.stderr,
            )
            return 1
        print(f"PASS: recall@5 {actual:.4f} >= {args.min_recall_at_5:.4f}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
