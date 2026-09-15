"""
FastAPI backend (Phase 2, spec section 32).

Every endpoint either reads persisted results of a real engine run, or (for
POST /experiments) triggers one. There are no mocked responses anywhere in
this file - if the engine can't run something, the endpoint returns an
error, not a fabricated result (spec section 40, Rule 8: "do not let the
frontend invent values" - the corollary here is that the backend must
never hand it invented values to begin with).

Run with:
    uvicorn backend.main:app --reload --port 8000
"""

from __future__ import annotations

import datetime as dt
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import db
from experiment_service import STRATEGIES, ExperimentError, run_experiment
from logging_utils import log_event
from schemas import (
    CostBreakdownOut,
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


@app.get("/strategies", response_model=list[StrategyInfo])
def list_strategies():
    """Static description of what each strategy actually needs - reflects
    the real ExperimentRequest validation, not aspirational docs."""
    return STRATEGIES


@app.post("/experiments", response_model=ExperimentDetailOut, status_code=201)
def create_experiment(req: ExperimentRequest):
    conn = db.get_connection()
    created_at = dt.datetime.utcnow().isoformat()

    experiment_id = db.insert_experiment(
        conn,
        created_at=created_at,
        symbol=req.symbol,
        dataset=req.dataset,
        side=req.side,
        quantity=req.quantity,
        strategy=req.strategy,
        config=req.model_dump(),
        status="running",
    )
    conn.commit()

    try:
        run = run_experiment(req)
    except ExperimentError as exc:
        conn.execute(
            "UPDATE experiments SET status = ?, error = ? WHERE id = ?",
            ("failed", str(exc), experiment_id),
        )
        conn.commit()
        log_event("experiment_failed", experiment_id=experiment_id, error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))

    with db.transaction() as conn:
        db.insert_execution_run(conn, experiment_id, run.result)
        db.insert_fills(conn, experiment_id, run.fills)
        db.insert_strategy_result(conn, experiment_id, run.costs, run.impact)
        conn.execute("UPDATE experiments SET status = ? WHERE id = ?", ("completed", experiment_id))

    return _load_experiment_detail(experiment_id)


@app.get("/experiments", response_model=list[ExperimentSummaryOut])
def list_experiments(limit: int = 100):
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