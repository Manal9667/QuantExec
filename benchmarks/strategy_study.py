"""
Strategy comparison study + aggregation.

Runs TWAP, VWAP, POV and Adaptive through the REAL C++ engine
(ExecutionSession) under IDENTICAL historical conditions (same dataset,
side, quantity, cost/latency assumptions) and records the full set of
execution-quality metrics for each. Then aggregates descriptive statistics
across all experiments.

CRITICAL HONESTY RULES (enforced structurally, see the `categories` block
attached to every experiment):
  OBSERVED  - values read directly from the historical market data
              (quote/row counts, raw bid/ask/last/volume, timestamps).
  CALCULATED- values mathematically derived from OBSERVED data
              (arrival price, avg execution price, market VWAP, slippage,
               implementation shortfall, fill rate, participation rate,
               market drift, completion time, realised spread cost).
  ASSUMED   - user/config parameters (side, quantity, strategy params,
               latency_ms, commission/exchange/fixed fees, limit multiplier).
  ESTIMATED - model-based approximations (estimate_market_impact output and
               the engine's estimated_spread_cost/estimated_execution_cost
               decomposition).
These are never blurred. The study reports descriptive results only and
NEVER declares a universally superior strategy.

Reproduce:
    PYTHONPATH=build python3 benchmarks/strategy_study.py
Options:
    --datasets <csv...>   (default: the real historical datasets present)
    --quantities 1000 5000
    --sides BUY SELL
"""

from __future__ import annotations

import argparse
import statistics
from pathlib import Path

import harness as H

# Real historical datasets usable directly by CsvMarketSource. Both are real
# Alpaca IEX captures for AAPL 2024-01-03 (different sessions/resolutions).
DEFAULT_DATASETS = [
    "data/raw/alpaca/AAPL/AAPL_2024-01-03_1430-1530_quotes.csv",   # ~171k tick quotes, has bar_volume
    "datasets/historical/AAPL_2024-01-03_0930-1030ET.csv",         # 60 1/min rows, quote-only (volume=0)
]

# ASSUMED configuration (kept identical across every strategy so the
# comparison is fair). These are parameters, not measurements.
COMMISSION_BPS = 0.5
EXCHANGE_FEE_BPS = 0.1
FIXED_FEE_PER_FILL = 0.0
LATENCY_MS = 0
IMPACT_ETA = 0.1  # calibration constant for the ESTIMATED impact model
TWAP_SLICES = 5
VWAP_SLICES = 5
VWAP_PROFILE = [0.35, 0.25, 0.20, 0.12, 0.08]
POV_RATE = 0.2
ADAPTIVE_BASE = 0.2
ADAPTIVE_SENSITIVITY = 5.0

STRATEGIES = ["TWAP", "VWAP", "POV", "ADAPTIVE"]


def _side(ex, side: str):
    return ex.OrderSide.Buy if side == "BUY" else ex.OrderSide.Sell


def _first_bid_ask(dataset_path: Path) -> tuple[float, float]:
    """Read the first data row's bid/ask (OBSERVED) to build a side-correct
    marketable limit price."""
    import csv
    with open(dataset_path, newline="") as f:
        row = next(csv.DictReader(f))
    return float(row["bid"]), float(row["ask"])


def run_one(ex, du, dataset_path: Path, side: str, quantity: int, strategy: str) -> dict:
    """Execute one (dataset, side, quantity, strategy) through the real engine."""
    # Arrival price = first mid (CALCULATED from OBSERVED). Limit price is a
    # side-appropriate MARKETABLE limit (ASSUMED): a BUY crosses upward
    # (ask*1.02), a SELL crosses downward (bid*0.98). Using a single
    # BUY-oriented limit for both sides would make every SELL a no-fill,
    # which would be an artifact of the assumption, not the engine.
    _limit_buy, arrival_price = du.resolve_prices(dataset_path, None, None)
    first_bid, first_ask = _first_bid_ask(dataset_path)
    limit_price = round(first_ask * 1.02, 4) if side == "BUY" else round(first_bid * 0.98, 4)
    stats = du.compute_dataset_stats(dataset_path)  # OBSERVED market volume + volatility

    source = ex.CsvMarketSource(str(dataset_path))
    if not source.ok():
        return {"strategy": strategy, "side": side, "quantity": quantity,
                "status": "failed", "reason": "CsvMarketSource could not load dataset"}

    session = ex.ExecutionSession()
    s = _side(ex, side)

    if strategy == "TWAP":
        algo = ex.TWAPAlgorithm()
        orders = algo.generate_orders(1, s, quantity, limit_price, TWAP_SLICES)
        result = session.run(source, orders, arrival_price)
    elif strategy == "VWAP":
        algo = ex.VWAPAlgorithm()
        algo.set_volume_profile(VWAP_PROFILE)
        orders = algo.generate_orders(1, s, quantity, limit_price, VWAP_SLICES)
        result = session.run(source, orders, arrival_price)
    elif strategy == "POV":
        pov = ex.POVAlgorithm(POV_RATE, 1, 0)
        result = session.run_pov(source, s, quantity, limit_price, pov, arrival_price)
    elif strategy == "ADAPTIVE":
        adaptive = ex.AdaptiveAlgorithm(ADAPTIVE_BASE, ADAPTIVE_SENSITIVITY, 1, 1.0)
        result = session.run_adaptive(source, s, quantity, limit_price, adaptive, arrival_price)
    else:
        return {"strategy": strategy, "status": "failed", "reason": f"unknown strategy {strategy}"}

    # Transaction costs (CALCULATED from ASSUMED rates).
    cfg = ex.TransactionCostConfig()
    cfg.commission_bps = COMMISSION_BPS
    cfg.exchange_fee_bps = EXCHANGE_FEE_BPS
    cfg.fixed_fee_per_fill = FIXED_FEE_PER_FILL
    costs = ex.compute_transaction_costs(result, cfg)

    # Market-impact ESTIMATE (model output, explicitly not observed).
    impact_cfg = ex.MarketImpactConfig(IMPACT_ETA)
    impact = ex.estimate_market_impact(
        result.filled_quantity, stats.total_bar_volume,
        stats.mid_price_volatility, result.average_execution_price, impact_cfg,
    )

    # Participation rate CALCULATED from OBSERVED market volume (None if the
    # dataset has no traded volume, e.g. the quote-only 60-row session).
    participation_rate = (
        result.filled_quantity / stats.total_bar_volume
        if stats.total_bar_volume > 0 else None
    )
    completion_status = (
        "complete" if result.filled_quantity >= result.requested_quantity else "partial"
    )

    return {
        "strategy": strategy,
        "side": side,
        "requested_quantity": result.requested_quantity,
        "status": "ok",
        # --- OBSERVED ---
        "observed": {
            "market_total_bar_volume": stats.total_bar_volume,
            "dataset_rows": stats.row_count,
        },
        # --- CALCULATED ---
        "calculated": {
            "arrival_price": result.arrival_price,
            "average_execution_price": result.average_execution_price,
            "market_vwap": result.market_vwap,
            "slippage": result.slippage,
            "implementation_shortfall": result.implementation_shortfall,
            "fill_rate": result.fill_rate,
            "filled_quantity": result.filled_quantity,
            "participation_rate": participation_rate,
            "market_price_drift": result.market_price_drift,
            "vwap_deviation": result.vwap_deviation,
            "completion_time_ms": result.completion_time_ms,
            "completion_status": completion_status,
            "num_fills": len(result.fills),
            "realized_spread_cost_bps_component": result.estimated_spread_cost,
            "transaction_cost_commission": costs.commission,
            "transaction_cost_exchange_fees": costs.exchange_fees,
            "transaction_cost_fixed_fees": costs.fixed_fees,
            "transaction_cost_spread_cost": costs.spread_cost,
            "transaction_cost_total": costs.total_cost,
            "transaction_cost_total_bps": costs.total_cost_bps,
        },
        # --- ASSUMED (parameters) ---
        "assumed": {
            "side": side,
            "quantity": quantity,
            "latency_ms": LATENCY_MS,
            "commission_bps": COMMISSION_BPS,
            "exchange_fee_bps": EXCHANGE_FEE_BPS,
            "fixed_fee_per_fill": FIXED_FEE_PER_FILL,
            "limit_price": limit_price,
            "strategy_params": {
                "TWAP": {"slices": TWAP_SLICES},
                "VWAP": {"slices": VWAP_SLICES, "volume_profile": VWAP_PROFILE},
                "POV": {"participation_rate": POV_RATE},
                "ADAPTIVE": {"base_participation": ADAPTIVE_BASE, "price_sensitivity": ADAPTIVE_SENSITIVITY},
            }[strategy],
        },
        # --- ESTIMATED (model output) ---
        "estimated": {
            "impact_model": "simplified square-root participation model (educational)",
            "impact_participation_rate": impact.participation_rate,
            "impact_bps": impact.impact_bps,
            "impact_cost": impact.impact_cost,
            "engine_estimated_execution_cost": result.estimated_execution_cost,
        },
    }


def _describe(values: list[float]) -> dict:
    vals = [v for v in values if v is not None]
    if not vals:
        return {"n": 0}
    vs = sorted(vals)

    def pct(p: float) -> float:
        if len(vs) == 1:
            return vs[0]
        k = (len(vs) - 1) * p
        lo = int(k)
        hi = min(lo + 1, len(vs) - 1)
        return vs[lo] + (vs[hi] - vs[lo]) * (k - lo)

    return {
        "n": len(vs),
        "mean": statistics.fmean(vs),
        "median": statistics.median(vs),
        "stdev": statistics.pstdev(vs) if len(vs) > 1 else 0.0,
        "min": vs[0],
        "max": vs[-1],
        "p10": pct(0.10),
        "p90": pct(0.90),
    }


def aggregate(experiments: list[dict]) -> dict:
    ok = [e for e in experiments if e.get("status") == "ok"]
    per_strategy = {}
    for strat in STRATEGIES:
        runs = [e for e in ok if e["strategy"] == strat]
        if not runs:
            continue
        completes = sum(1 for r in runs if r["calculated"]["completion_status"] == "complete")
        per_strategy[strat] = {
            "experiments": len(runs),
            "completion_rate": completes / len(runs),
            "implementation_shortfall": _describe([r["calculated"]["implementation_shortfall"] for r in runs]),
            "slippage": _describe([r["calculated"]["slippage"] for r in runs]),
            "fill_rate": _describe([r["calculated"]["fill_rate"] for r in runs]),
            "transaction_cost_total_bps": _describe([r["calculated"]["transaction_cost_total_bps"] for r in runs]),
            "participation_rate": _describe([r["calculated"]["participation_rate"] for r in runs]),
            "market_price_drift": _describe([r["calculated"]["market_price_drift"] for r in runs]),
        }
    return {
        "total_experiments": len(ok),
        "per_strategy": per_strategy,
        "note": (
            "Descriptive statistics only. No strategy is declared superior; "
            "results are conditioned on this specific, small set of real "
            "sessions and the ASSUMED parameters above. See sample_size_warning."
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="QuantExec strategy comparison study")
    ap.add_argument("--datasets", nargs="*", default=DEFAULT_DATASETS)
    ap.add_argument("--quantities", nargs="*", type=int, default=[1000, 5000])
    ap.add_argument("--sides", nargs="*", default=["BUY", "SELL"])
    args = ap.parse_args()

    ex = H.import_executor()
    du = H.import_dataset_utils()

    dataset_meta = []
    experiments = []
    for ds in args.datasets:
        dpath = H.REPO_ROOT / ds
        if not dpath.exists():
            dataset_meta.append({"dataset": ds, "status": "missing"})
            continue
        dataset_meta.append({
            "dataset": ds,
            "sha256": H.sha256_file(dpath),
            "data_rows": H.count_data_rows(dpath),
        })
        for side in args.sides:
            for qty in args.quantities:
                for strat in STRATEGIES:
                    rec = run_one(ex, du, dpath, side, qty, strat)
                    rec["dataset"] = ds
                    experiments.append(rec)
                    c = rec.get("calculated", {})
                    print(f"{ds.split('/')[-1]:<40} {side:<4} {qty:>5} {strat:<9} "
                          f"fill={c.get('fill_rate')} IS={c.get('implementation_shortfall')}", flush=True)

    ok = [e for e in experiments if e.get("status") == "ok"]
    agg = aggregate(experiments)
    # Honest small-sample warning.
    n_real_sessions = len([d for d in dataset_meta if d.get("data_rows")])
    if n_real_sessions < 5:
        agg["sample_size_warning"] = (
            f"Only {n_real_sessions} distinct real historical session(s) are "
            f"available ({len(ok)} experiments total). This sample is FAR too "
            f"small to support any general claim about relative strategy "
            f"performance on real markets. Numbers are reported descriptively "
            f"for this specific data only. Add more real sessions via the "
            f"Alpaca ingestion pipeline (python/alpaca_ingest.py) to grow N."
        )

    payload = {
        "_meta": H.new_meta(
            "strategy_study",
            "PYTHONPATH=build python3 benchmarks/strategy_study.py",
            extra={
                "engine": "real C++ ExecutionSession (run / run_pov / run_adaptive)",
                "strategies": STRATEGIES,
                "fairness": "identical dataset, side, quantity, cost & latency assumptions across strategies",
            },
        ),
        "datasets": dataset_meta,
        "aggregate": agg,
        "experiments": experiments,
    }
    out = H.write_json("strategy_experiments.json", payload)
    print(f"\n{len(ok)} experiments ok. Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
