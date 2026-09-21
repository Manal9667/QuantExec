"""
Core experiment execution logic (Phase 2, spec section 32).

This module is the one place backend/main.py calls into the actual
compiled C++ engine (the `executor` pybind11 module) - every number that
comes back from an API call originates from a real ExecutionSession run
against the requested dataset (spec section 32: "no mocked responses;
every result must originate from actual engine execution").

Mirrors the logic in python/run_experiment.py (Phase 1) but generalized to
also support POV and the latency model, and to compute the optional
market-impact estimate. Kept separate from run_experiment.py rather than
importing it, since run_experiment.py is a Phase 1 CLI entry point with
its own argparse/print surface - duplicating the ~20 lines of "resolve
prices, build the algorithm, run the session" logic here is cheaper than
coupling a library import to a Phase 1 script's CLI concerns.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from executor import (
    AdaptiveAlgorithm,
    CsvMarketSource,
    ExecutionSession,
    MarketImpactConfig,
    OrderSide,
    POVAlgorithm,
    TransactionCostConfig,
    TWAPAlgorithm,
    VWAPAlgorithm,
    compute_transaction_costs,
    estimate_market_impact,
)

from dataset_utils import DatasetError, compute_dataset_stats, resolve_prices
from logging_utils import log_event, timed_stage
from schemas import ExperimentRequest

REPO_ROOT = Path(__file__).resolve().parent.parent


class ExperimentError(ValueError):
    """Raised for request-level problems (bad dataset, bad config) so
    main.py can turn them into a structured 4xx instead of a 500.

    `error_type` is one of a small, documented, stable set of machine-
    readable reasons (Step 6: 'return structured validation errors') -
    the message text is for humans, `error_type` is for client code that
    wants to branch on the failure without string-matching:

        dataset_not_found   - the dataset path doesn't exist under the repo
        dataset_path_unsafe - the path tried to escape the repo root
        dataset_unloadable  - the file exists but the engine couldn't load it
                               (see scripts/build_dataset_manifest.py for why),
                               or it is empty / missing required columns
        unknown_strategy    - strategy isn't one of TWAP/VWAP/POV
        engine_error        - unexpected failure inside the engine or the
                               persistence layer (a server-side problem, 500)
    """

    def __init__(self, message: str, error_type: str = "invalid_request"):
        super().__init__(message)
        self.error_type = error_type


def _resolve_dataset_path(dataset: str) -> Path:
    path = (REPO_ROOT / dataset).resolve()
    repo_root_resolved = REPO_ROOT.resolve()
    if repo_root_resolved != path and repo_root_resolved not in path.parents:
        raise ExperimentError("Dataset path must stay inside the project directory", error_type="dataset_path_unsafe")
    # is_file(), not just exists(): a directory would otherwise pass this
    # check and blow up later as an unhandled IsADirectoryError (HTTP 500).
    if not path.is_file():
        raise ExperimentError(f"Dataset not found: {dataset}", error_type="dataset_not_found")
    return path


# Public alias - main.py needs this before run_experiment() to compute the
# dataset checksum for the duplicate-submission check (Step 6), so it's
# part of this module's public surface rather than a private helper.
resolve_dataset_path = _resolve_dataset_path


def compute_dataset_checksum(dataset_path: Path) -> str:
    """SHA-256 of the exact bytes on disk (Step 6: 'store with every
    experiment: dataset checksum'). Same function and same algorithm as
    scripts/build_dataset_manifest.py, so a manifest's checksum and an
    experiment's stored checksum are directly comparable."""
    h = hashlib.sha256()
    with open(dataset_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_config_hash(req: ExperimentRequest, dataset_checksum: str) -> str:
    """Deterministic fingerprint of "would this run produce the same
    result as an existing one?" - the request body plus the dataset
    checksum (not just the dataset *path*, since a path can point to
    different bytes over time). Used for the duplicate-submission policy
    in main.py. `model_dump(mode="json")` + `sort_keys=True` guarantees
    the same logical request always hashes the same way regardless of
    field ordering."""
    payload = req.model_dump(mode="json")
    payload["_dataset_checksum"] = dataset_checksum
    canonical = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _build_algorithm(req: ExperimentRequest):
    if req.strategy == "TWAP":
        return TWAPAlgorithm()
    if req.strategy == "VWAP":
        algo = VWAPAlgorithm()
        if req.volume_profile:
            algo.set_volume_profile(list(req.volume_profile))
        return algo
    if req.strategy == "POV":
        return POVAlgorithm(req.participation_rate, req.min_order_qty, req.max_order_qty)
    if req.strategy == "ADAPTIVE":
        return AdaptiveAlgorithm(
            req.base_participation,
            req.price_sensitivity,
            req.min_order_qty,
            req.max_participation,
        )
    raise ExperimentError(f"Unknown strategy '{req.strategy}'", error_type="unknown_strategy")


def _result_to_dict(result, limit_price: float) -> dict:
    return {
        "requested_quantity": result.requested_quantity,
        "filled_quantity": result.filled_quantity,
        "arrival_price": result.arrival_price,
        "limit_price": limit_price,
        "average_execution_price": result.average_execution_price,
        "market_vwap": result.market_vwap,
        "fill_rate": result.fill_rate,
        "slippage": result.slippage,
        "implementation_shortfall": result.implementation_shortfall,
        "vwap_deviation": result.vwap_deviation,
        "completion_time_ms": result.completion_time_ms,
        "market_price_drift": result.market_price_drift,
        "estimated_spread_cost": result.estimated_spread_cost,
        "estimated_execution_cost": result.estimated_execution_cost,
    }


def _fills_to_list(result) -> list[dict]:
    return [
        {
            "timestamp_ms": f.timestamp_ms,
            "price": f.trade.price,
            "qty": f.trade.qty,
            "bid": f.bid,
            "ask": f.ask,
            "market_volume": f.market_volume,
        }
        for f in result.fills
    ]


@dataclass
class ExperimentRun:
    result: dict
    fills: list[dict]
    costs: dict
    impact: Optional[dict] = None


def run_experiment(req: ExperimentRequest) -> ExperimentRun:
    """Run one experiment end-to-end through the real C++ engine.

    Raises ExperimentError for request-level problems (bad dataset path,
    engine reports it could not load the CSV).
    """
    dataset_path = _resolve_dataset_path(req.dataset)
    side = OrderSide.Buy if req.side == "BUY" else OrderSide.Sell

    with timed_stage("data_loading", dataset=req.dataset):
        try:
            limit_price, arrival_price = resolve_prices(dataset_path, req.limit_price, req.arrival_price)
        except DatasetError as exc:
            raise ExperimentError(str(exc), error_type="dataset_unloadable") from exc
        source = CsvMarketSource(str(dataset_path))
        if not source.ok():
            raise ExperimentError(
                f"Could not load dataset '{req.dataset}' - check the path and required CSV columns",
                error_type="dataset_unloadable",
            )

    session = ExecutionSession()
    log_event("replay_started", symbol=req.symbol, dataset=req.dataset, strategy=req.strategy)

    with timed_stage("execution", strategy=req.strategy):
        if req.strategy == "POV":
            pov = _build_algorithm(req)
            result = session.run_pov(source, side, req.quantity, limit_price, pov, arrival_price)
        elif req.strategy == "ADAPTIVE":
            adaptive = _build_algorithm(req)
            result = session.run_adaptive(source, side, req.quantity, limit_price, adaptive, arrival_price)
        else:
            algo = _build_algorithm(req)
            orders = algo.generate_orders(1, side, req.quantity, limit_price, req.slices)
            if req.latency_ms > 0:
                result = session.run_with_latency(source, orders, arrival_price, req.latency_ms)
            else:
                result = session.run(source, orders, arrival_price)

    if result.filled_quantity < result.requested_quantity:
        log_event(
            "insufficient_liquidity",
            symbol=req.symbol,
            requested=result.requested_quantity,
            filled=result.filled_quantity,
        )
    log_event(
        "replay_completed",
        symbol=req.symbol,
        filled_quantity=result.filled_quantity,
        fill_rate=result.fill_rate,
    )

    with timed_stage("analytics"):
        cost_cfg = TransactionCostConfig()
        cost_cfg.commission_bps = req.costs.commission_bps
        cost_cfg.exchange_fee_bps = req.costs.exchange_fee_bps
        cost_cfg.fixed_fee_per_fill = req.costs.fixed_fee_per_fill
        costs = compute_transaction_costs(result, cost_cfg)

        impact_out = None
        if req.impact.enabled:
            try:
                stats = compute_dataset_stats(dataset_path)
            except DatasetError as exc:
                raise ExperimentError(str(exc), error_type="dataset_unloadable") from exc
            impact_cfg = MarketImpactConfig(req.impact.eta)
            impact = estimate_market_impact(
                result.filled_quantity,
                stats.total_bar_volume,
                stats.mid_price_volatility,
                result.average_execution_price,
                impact_cfg,
            )
            impact_out = {
                "participation_rate": impact.participation_rate,
                "impact_bps": impact.impact_bps,
                "impact_cost": impact.impact_cost,
            }

    log_event("experiment_completed", symbol=req.symbol, strategy=req.strategy)

    return ExperimentRun(
        result=_result_to_dict(result, limit_price),
        fills=_fills_to_list(result),
        costs={
            "commission": costs.commission,
            "exchange_fees": costs.exchange_fees,
            "fixed_fees": costs.fixed_fees,
            "spread_cost": costs.spread_cost,
            "total_cost": costs.total_cost,
            "total_cost_bps": costs.total_cost_bps,
        },
        impact=impact_out,
    )


STRATEGIES = [
    {
        "name": "TWAP",
        "description": "Splits the parent order into equal-sized slices, one per replayed market event.",
        "required_fields": ["quantity", "slices"],
        "optional_fields": ["limit_price", "arrival_price", "latency_ms"],
    },
    {
        "name": "VWAP",
        "description": "Splits the parent order according to a historical intraday volume profile.",
        "required_fields": ["quantity", "slices"],
        "optional_fields": ["volume_profile", "limit_price", "arrival_price", "latency_ms"],
    },
    {
        "name": "POV",
        "description": "Targets a fixed percentage of realized market volume per replayed event.",
        "required_fields": ["quantity", "participation_rate"],
        "optional_fields": ["min_order_qty", "max_order_qty", "limit_price", "arrival_price"],
    },
    {
        "name": "ADAPTIVE",
        "description": "Paces off remaining quantity, trading faster when the price is favorable vs arrival and slower when it is not.",
        "required_fields": ["quantity", "base_participation"],
        "optional_fields": ["price_sensitivity", "max_participation", "min_order_qty", "limit_price", "arrival_price"],
    },
]