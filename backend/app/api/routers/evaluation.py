"""Evaluation endpoints.

`retrieval_only` runs synchronously when small (it is deterministic and fast); anything larger
or in `full` mode is dispatched to a background task and polled, because a 45-question run
with an LLM in the loop takes minutes and must not hold an HTTP connection open.
"""

from __future__ import annotations

from typing import Any

from app.api.deps import ContainerDep, RequireRead, RequireWrite
from app.api.schemas import (
    ErrorResponse,
    EvaluationRunDetail,
    EvaluationRunRequest,
    EvaluationRunSummary,
    EvaluationStartedResponse,
)
from app.core.logging import get_logger
from fastapi import APIRouter, BackgroundTasks, Query
from starlette.concurrency import run_in_threadpool

router = APIRouter(prefix="/evaluation", tags=["evaluation"])
log = get_logger("api.evaluation")

# Above this many questions, run in the background rather than holding the connection.
SYNC_LIMIT = 60


@router.get("/datasets", summary="Available golden datasets")
async def list_datasets(container: ContainerDep, caller: RequireRead) -> list[dict[str, Any]]:
    return container.evaluation_service.available_datasets()


@router.post(
    "/runs",
    response_model=EvaluationRunSummary | EvaluationStartedResponse,
    summary="Start an evaluation run",
    description=(
        "`retrieval_only` computes Recall@k, Precision@k, MRR, nDCG@5 and section accuracy by "
        "exact arithmetic with no LLM involved — deterministic and CI-safe. `full` adds "
        "generation metrics (citation precision/recall, keyword and numeric compliance, "
        "refusal accuracy) and, with `judge=true`, LLM-judged faithfulness and relevance "
        "which are reported as indicative rather than ground truth."
    ),
    responses={422: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def start_run(
    body: EvaluationRunRequest,
    background: BackgroundTasks,
    container: ContainerDep,
    caller: RequireWrite,
):
    service = container.evaluation_service
    datasets = {d["name"]: d for d in service.available_datasets()}
    dataset = datasets.get(body.dataset)
    if dataset is None:
        from app.core.errors import NotFoundError

        raise NotFoundError(f"Dataset '{body.dataset}' does not exist.", available=list(datasets))

    n_questions = body.limit or dataset.get("n_questions", 0)
    run_synchronously = body.mode == "retrieval_only" and n_questions <= SYNC_LIMIT

    kwargs = {
        "dataset": body.dataset,
        "mode": body.mode,
        "top_k": body.top_k,
        "rerank": body.rerank,
        "judge": body.judge,
        "limit": body.limit,
        "categories": body.categories,
    }

    if run_synchronously:
        outcome = await run_in_threadpool(lambda: service.run(**kwargs))
        run = service.get_run(outcome["run_id"])
        return _to_summary(run)

    def task() -> None:
        try:
            service.run(**kwargs)
        except Exception as exc:
            log.error("evaluation.background_failed", error=str(exc), exc_info=True)

    background.add_task(task)
    return EvaluationStartedResponse(
        message=(
            f"Evaluation of {n_questions} questions started in {body.mode} mode. "
            "Poll the runs endpoint for results."
        ),
        poll="/api/evaluation/runs",
    )


@router.get("/runs", response_model=list[EvaluationRunSummary], summary="Run history")
async def list_runs(
    container: ContainerDep, caller: RequireRead, limit: int = Query(25, ge=1, le=100)
) -> list[EvaluationRunSummary]:
    return [_to_summary(run) for run in container.evaluation_service.list_runs(limit=limit)]


@router.get(
    "/runs/{run_id}",
    response_model=EvaluationRunDetail,
    summary="Metrics plus per-question results",
    responses={404: {"model": ErrorResponse}},
)
async def get_run(run_id: str, container: ContainerDep, caller: RequireRead) -> EvaluationRunDetail:
    run = container.evaluation_service.get_run(run_id)
    return EvaluationRunDetail(**_to_summary(run).model_dump(), results=run.get("results", []))


def _to_summary(run: dict[str, Any]) -> EvaluationRunSummary:
    return EvaluationRunSummary(
        id=run["id"],
        dataset=run["dataset"],
        mode=run["mode"],
        status=run["status"],
        started_at=run["started_at"],
        finished_at=run.get("finished_at"),
        n_questions=run.get("n_questions", 0),
        metrics=run.get("metrics", {}),
        config=run.get("config", {}),
        error=run.get("error"),
    )
