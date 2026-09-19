"""
FastAPI backend (Phase 2, spec section 32).

Every endpoint either reads persisted results of a real engine run, or (for
POST /experiments) triggers one. There are no mocked responses anywhere in
this file - if the engine can't run something, the endpoint returns an
error, not a fabricated result (spec section 40, Rule 8: "do not let the
frontend invent values" - the corollary here is that the backend must
never hand it invented values to begin with).

Run with (from the repo root; the modules here use flat imports, so the
backend directory and the built `executor` module must be on the path):
    PYTHONPATH=build:backend uvicorn main:app --app-dir backend --reload --port 8000
"""

from __future__ import annotations

import datetime as dt
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import db
from experiment_service import (
    STRATEGIES,
    ExperimentError,
    compute_config_hash,
    compute_dataset_checksum,
    resolve_dataset_path,
    run_experiment,
)
from logging_utils import log_event
from schemas import (
    CostBreakdownOut,
    ErrorOut,
    ExecutionMetricsOut,
    ExperimentDetailOut,
    ExperimentRequest,
    ExperimentSummaryOut,
    FillOut,
    ImpactEstimateOut,
    StrategyInfo,
)

app = FastAPI(
    title="Quant Execution Engine API",
    description=(
        "Read-only + experiment-triggering API over the C++ execution engine. "
        "Every result originates from an actual ExecutionSession run - see "
        "backend/experiment_service.py."
    ),
    version="0.2.0",
)

# Permissive CORS for local dev (the React dashboard runs on a different
# port). Tighten this before deploying anywhere that isn't localhost.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# error_type -> HTTP status. Anything not listed is an ordinary 400. engine_error
# is a server-side failure (not the client's fault), so it is a 500.
_ERROR_STATUS = {"dataset_path_unsafe": 403, "engine_error": 500}


def _mark_failed(conn, experiment_id: int, message: str) -> None:
    """Move a row out of 'running' so it can't be stranded there forever
    (a stranded row is invisible to the duplicate check and never retried)."""
    conn.rollback()
    db.update_experiment_status(conn, experiment_id, "failed", message)
    conn.commit()


@app.exception_handler(ExperimentError)
def handle_experiment_error(request, exc: ExperimentError):
    """Step 6: 'return structured validation errors'. Every ExperimentError
    becomes {"error_type": ..., "detail": ...} instead of FastAPI's default
    bare-string `detail`, so a client can branch on `error_type` without
    parsing English prose. dataset_path_unsafe is the one case treated as
    a stricter client error (403) since it's a boundary violation attempt,
    not an ordinary mistake; everything else is 400."""
    status_code = _ERROR_STATUS.get(exc.error_type, 400)
    return JSONResponse(
        status_code=status_code,
        content=ErrorOut(error_type=exc.error_type, detail=str(exc)).model_dump(),
    )


@app.get("/strategies", response_model=list[StrategyInfo])
def list_strategies():
    """Static description of what each strategy actually needs - reflects
    the real ExperimentRequest validation, not aspirational docs."""
    return STRATEGIES


@app.post("/experiments", response_model=ExperimentDetailOut, status_code=201)
def create_experiment(req: ExperimentRequest, allow_duplicate: bool = False):
    """Run one experiment through the real engine.

    Step 6 duplicate-submission policy: if an experiment with an
    identical request body AND an identical dataset checksum already
    completed successfully, that result is returned as-is (with
    `duplicate_of` set) instead of re-running the engine - the same
    inputs are guaranteed to produce the same outputs (see BASELINE.md
    §3.4), so re-running would only burn time for an identical answer.
    Pass `?allow_duplicate=true` to force a fresh run anyway (e.g. to
    verify determinism, or after fixing something the config_hash can't see
    like the engine binary itself).
    """
    conn = db.get_connection()
    created_at = dt.datetime.now(dt.timezone.utc).isoformat()

    # Resolve + checksum the dataset up front. A bad dataset path is
    # exactly the kind of "invalid configuration" Step 6 wants surfaced
    # clearly and early, via the structured-error handler above, before
    # any row is even written.
    dataset_path = resolve_dataset_path(req.dataset)
    dataset_checksum = compute_dataset_checksum(dataset_path)
    config_hash = compute_config_hash(req, dataset_checksum)

    if not allow_duplicate:
        existing = db.find_completed_experiment_by_config_hash(conn, config_hash)
        if existing is not None:
            log_event("experiment_duplicate_reused", experiment_id=existing["id"], config_hash=config_hash)
            detail = _load_experiment_detail(existing["id"])
            detail.duplicate_of = existing["id"]
            return detail

    experiment_id = db.insert_experiment(
        conn,
        created_at=created_at,
        symbol=req.symbol,
        dataset=req.dataset,
        side=req.side,
        quantity=req.quantity,
        strategy=req.strategy,
        config=req.model_dump(),
        status="queued",
        dataset_checksum=dataset_checksum,
        config_hash=config_hash,
    )
    conn.commit()

    db.update_experiment_status(conn, experiment_id, "running")
    conn.commit()

    try:
        run = run_experiment(req)
        with db.transaction() as tx_conn:
            db.insert_execution_run(tx_conn, experiment_id, run.result)
            db.insert_fills(tx_conn, experiment_id, run.fills)
            db.insert_strategy_result(tx_conn, experiment_id, run.costs, run.impact)
            db.update_experiment_status(tx_conn, experiment_id, "completed")
    except ExperimentError as exc:
        _mark_failed(conn, experiment_id, str(exc))
        log_event("experiment_failed", experiment_id=experiment_id, error_type=exc.error_type, error=str(exc))
        raise
    except Exception as exc:  # noqa: BLE001 - engine/DB failure: never leave the row 'running'
        _mark_failed(conn, experiment_id, f"{type(exc).__name__}: {exc}")
        log_event("experiment_failed", experiment_id=experiment_id, error_type="engine_error", error=str(exc))
        raise ExperimentError(f"Experiment failed unexpectedly: {exc}", error_type="engine_error") from exc

    return _load_experiment_detail(experiment_id)


@app.delete("/experiments/{experiment_id}", response_model=ExperimentDetailOut)
def cancel_experiment(experiment_id: int):
    """Step 6 'cancelled' state.

    Honest limitation: experiment execution in this backend is synchronous
    (the engine runs to completion inside the POST /experiments request
    handler before it returns), so there is no in-flight run for this
    endpoint to interrupt under normal operation - by the time a client
    could call DELETE, POST has already returned 'completed' or 'failed'.
    This endpoint exists for the one case a status can legitimately still
    be 'running': the server process crashed or was killed mid-request,
    leaving a row stuck in 'running' with no execution behind it. Marking
    that row 'cancelled' is what unblocks a duplicate-submission retry of
    the same config (see the config_hash lookup above, which only matches
    'completed' rows). A future async/queued execution mode is what would
    make this endpoint able to interrupt a genuinely in-flight run.
    """
    conn = db.get_connection()
    exp = db.get_experiment(conn, experiment_id)
    if exp is None:
        raise HTTPException(status_code=404, detail=f"Experiment {experiment_id} not found")
    if exp["status"] != "running":
        raise HTTPException(
            status_code=409,
            detail=f"Experiment {experiment_id} is '{exp['status']}', not 'running' - nothing to cancel",
        )
    db.update_experiment_status(conn, experiment_id, "cancelled", "Cancelled via DELETE /experiments/{id}")
    conn.commit()
    return _load_experiment_detail(experiment_id)


@app.get("/experiments", response_model=list[ExperimentSummaryOut])
def list_experiments(limit: int = Query(100, ge=1, le=1000)):
    conn = db.get_connection()
    rows = db.list_experiments(conn, limit=limit)
    return [
        ExperimentSummaryOut(
            id=r["id"],
            created_at=r["created_at"],
            symbol=r["symbol"],
            dataset=r["dataset"],
            side=r["side"],
            quantity=r["quantity"],
            strategy=r["strategy"],
            status=r["status"],
            dataset_checksum=r["dataset_checksum"],
            filled_quantity=r["filled_quantity"],
            requested_quantity=r["requested_quantity"],
            fill_rate=r["fill_rate"],
            average_execution_price=r["average_execution_price"],
            slippage=r["slippage"],
            total_cost=r["total_cost"],
            total_cost_bps=r["total_cost_bps"],
        )
        for r in rows
    ]


def _load_experiment_detail(experiment_id: int) -> ExperimentDetailOut:
    conn = db.get_connection()
    exp = db.get_experiment(conn, experiment_id)
    if exp is None:
        raise HTTPException(status_code=404, detail=f"Experiment {experiment_id} not found")

    import json

    run = db.get_execution_run(conn, experiment_id)
    strat = db.get_strategy_result(conn, experiment_id)

    metrics: Optional[ExecutionMetricsOut] = None
    if run is not None:
        metrics = ExecutionMetricsOut(**{k: run[k] for k in ExecutionMetricsOut.model_fields})

    costs: Optional[CostBreakdownOut] = None
    impact: Optional[ImpactEstimateOut] = None
    if strat is not None:
        costs = CostBreakdownOut(**{k: strat[k] for k in CostBreakdownOut.model_fields})
        if strat["impact_bps"] is not None:
            impact = ImpactEstimateOut(
                participation_rate=strat["impact_participation_rate"],
                impact_bps=strat["impact_bps"],
                impact_cost=strat["impact_cost"],
            )

    return ExperimentDetailOut(
        id=exp["id"],
        created_at=exp["created_at"],
        symbol=exp["symbol"],
        dataset=exp["dataset"],
        side=exp["side"],
        quantity=exp["quantity"],
        strategy=exp["strategy"],
        status=exp["status"],
        error=exp["error"],
        config=json.loads(exp["config_json"]),
        dataset_checksum=exp["dataset_checksum"],
        config_hash=exp["config_hash"],
        metrics=metrics,
        costs=costs,
        impact=impact,
    )


@app.get("/experiments/{experiment_id}", response_model=ExperimentDetailOut)
def get_experiment(experiment_id: int):
    return _load_experiment_detail(experiment_id)


@app.get("/experiments/{experiment_id}/fills", response_model=list[FillOut])
def get_experiment_fills(experiment_id: int):
    conn = db.get_connection()
    if db.get_experiment(conn, experiment_id) is None:
        raise HTTPException(status_code=404, detail=f"Experiment {experiment_id} not found")
    rows = db.get_fills(conn, experiment_id)
    return [FillOut(**{k: r[k] for k in FillOut.model_fields}) for r in rows]


@app.get("/experiments/{experiment_id}/metrics")
def get_experiment_metrics(experiment_id: int):
    detail = _load_experiment_detail(experiment_id)
    if detail.metrics is None:
        raise HTTPException(status_code=404, detail="No metrics recorded for this experiment")
    return {
        "metrics": detail.metrics,
        "costs": detail.costs,
        "impact": detail.impact,
    }


@app.get("/health")
def health():
    return {"status": "ok"}