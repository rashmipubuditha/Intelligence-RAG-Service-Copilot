"""Evaluation service — the API's view of the harness in eval/.

The harness is the implementation; this is a thin wrapper that runs it in a background task
and exposes run history. Deliberately thin: the same code must be runnable from the CLI with
no server involved, because that is how it gets used in CI.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.core.errors import NotFoundError, ValidationError
from app.core.logging import get_logger

if TYPE_CHECKING:
    from app.container import AppContainer

log = get_logger("evaluation")

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _ensure_eval_importable() -> None:
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))


class EvaluationService:
    def __init__(self, *, container: AppContainer) -> None:
        self.c = container

    def available_datasets(self) -> list[dict[str, Any]]:
        _ensure_eval_importable()
        from eval.run import DATASETS_DIR, load_dataset

        datasets: list[dict[str, Any]] = []
        for path in sorted(DATASETS_DIR.glob("*.jsonl")):
            try:
                records = load_dataset(path.name)
            except Exception as exc:
                datasets.append({"name": path.stem, "error": str(exc)})
                continue
            categories: dict[str, int] = {}
            for record in records:
                category = record.get("category", "uncategorised")
                categories[category] = categories.get(category, 0) + 1
            datasets.append(
                {
                    "name": path.stem,
                    "n_questions": len(records),
                    "categories": categories,
                    "refusal_cases": sum(1 for r in records if r.get("should_refuse")),
                }
            )
        return datasets

    def run(
        self,
        *,
        dataset: str = "aml_kyc_golden_v1",
        mode: str = "retrieval_only",
        top_k: int | None = None,
        rerank: bool | None = None,
        judge: bool = False,
        limit: int | None = None,
        categories: list[str] | None = None,
    ) -> dict[str, Any]:
        """Run synchronously and return the summary. Callers that must not block (the API)
        schedule this on a background task and poll the run record."""
        _ensure_eval_importable()
        from eval.run import run_evaluation, write_reports

        if mode not in ("retrieval_only", "full"):
            raise ValidationError("mode must be 'retrieval_only' or 'full'.", received=mode)
        if self.c.chunks.count() == 0:
            from app.core.errors import IndexNotReadyError

            raise IndexNotReadyError("Index a document before running an evaluation.")

        log.info("evaluation.started", dataset=dataset, mode=mode, top_k=top_k, rerank=rerank)
        report = run_evaluation(
            dataset=dataset,
            mode=mode,
            top_k=top_k,
            rerank=rerank,
            judge=judge,
            limit=limit,
            categories=categories,
            container=self.c,
            progress=False,
        )
        try:
            write_reports(report)
        except Exception as exc:  # a report-writing failure must not lose the run
            log.warning("evaluation.report_write_failed", error=str(exc))

        log.info(
            "evaluation.finished",
            run_id=report["run_id"],
            n=report["metrics"].get("n_questions"),
            recall_at_5=report["metrics"].get("recall@5"),
            mrr=report["metrics"].get("mrr"),
        )
        return {"run_id": report["run_id"], "metrics": report["metrics"], "config": report["config"]}

    def list_runs(self, limit: int = 25) -> list[dict[str, Any]]:
        return self.c.evals.list_runs(limit=limit)

    def get_run(self, run_id: str) -> dict[str, Any]:
        run = self.c.evals.get_run(run_id)
        if run is None:
            raise NotFoundError(f"Evaluation run {run_id} does not exist.")
        return run
