"""
Determinism / reproducibility benchmark.

Runs the SAME experiment many times through the real C++ engine and verifies
that every repetition produces byte-identical results: fills, quantities,
execution prices, completion status, and all analytics. This is the property
that makes QuantExec's historical execution research reproducible (spec §27).

Method: for each run we build a canonical signature string of every
ExecutionResult field plus every individual fill (timestamp, price, qty,
bid, ask, market_volume) and SHA-256 it. Two runs are "identical" iff their
signatures match. We report runs / identical / mismatches per strategy and
dataset, so a statement like "1000/1000 repeated executions produced
identical results" is backed by an actual count.

Two configurations (both REAL data), so the claim covers a fast small
session at high repetition count AND a large session:
  * datasets/historical/AAPL_2024-01-03_0930-1030ET.csv  @ 1000 reps
  * data/raw/alpaca/AAPL/AAPL_2024-01-03_1430-1530_quotes.csv @ 100 reps

Reproduce:
    PYTHONPATH=build python3 benchmarks/determinism.py
Options:
    --small-reps 1000   --large-reps 100
"""

from __future__ import annotations

import argparse
import hashlib
import time
from pathlib import Path

import harness as H

SMALL_DATASET = "datasets/historical/AAPL_2024-01-03_0930-1030ET.csv"
LARGE_DATASET = "data/raw/alpaca/AAPL/AAPL_2024-01-03_1430-1530_quotes.csv"

STRATEGIES = ["TWAP", "VWAP", "POV", "ADAPTIVE"]
QUANTITY = 1000
SIDE = "BUY"


def _run_once(ex, du, dataset_path: Path, strategy: str):
    limit_buy, arrival = du.resolve_prices(dataset_path, None, None)
    source = ex.CsvMarketSource(str(dataset_path))
    session = ex.ExecutionSession()
    s = ex.OrderSide.Buy
    if strategy == "TWAP":
        orders = ex.TWAPAlgorithm().generate_orders(1, s, QUANTITY, limit_buy, 5)
        return session.run(source, orders, arrival)
    if strategy == "VWAP":
        a = ex.VWAPAlgorithm(); a.set_volume_profile([0.35, 0.25, 0.20, 0.12, 0.08])
        orders = a.generate_orders(1, s, QUANTITY, limit_buy, 5)
        return session.run(source, orders, arrival)
    if strategy == "POV":
        return session.run_pov(source, s, QUANTITY, limit_buy, ex.POVAlgorithm(0.2, 1, 0), arrival)
    if strategy == "ADAPTIVE":
        return session.run_adaptive(source, s, QUANTITY, limit_buy, ex.AdaptiveAlgorithm(0.2, 5.0, 1, 1.0), arrival)
    raise ValueError(strategy)


def _signature(result) -> str:
    """Canonical, exact signature of a full ExecutionResult (all analytics +
    every fill). repr() of floats is exact round-trippable in CPython, so
    this catches any bit-level difference."""
    parts = [
        repr(result.requested_quantity), repr(result.filled_quantity),
        repr(result.arrival_price), repr(result.average_execution_price),
        repr(result.market_vwap), repr(result.fill_rate), repr(result.slippage),
        repr(result.implementation_shortfall), repr(result.vwap_deviation),
        repr(result.completion_time_ms), repr(result.market_price_drift),
        repr(result.estimated_spread_cost), repr(result.estimated_execution_cost),
    ]
    for f in result.fills:
        parts.append(f"{f.timestamp_ms},{f.trade.price!r},{f.trade.qty},{f.bid!r},{f.ask!r},{f.market_volume}")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def run_config(ex, du, dataset: str, reps: int) -> dict:
    dpath = H.REPO_ROOT / dataset
    if not dpath.exists():
        return {"dataset": dataset, "status": "missing", "reps": reps}
    per_strategy = {}
    for strat in STRATEGIES:
        t0 = time.perf_counter()
        first_sig = None
        identical = 0
        mismatches = []
        first_summary = None
        for i in range(reps):
            res = _run_once(ex, du, dpath, strat)
            sig = _signature(res)
            if i == 0:
                first_sig = sig
                first_summary = {
                    "filled_quantity": res.filled_quantity,
                    "requested_quantity": res.requested_quantity,
                    "average_execution_price": res.average_execution_price,
                    "fill_rate": res.fill_rate,
                    "num_fills": len(res.fills),
                    "completion_status": "complete" if res.filled_quantity >= res.requested_quantity else "partial",
                }
            if sig == first_sig:
                identical += 1
            elif len(mismatches) < 3:
                mismatches.append({"run_index": i, "signature": sig[:16]})
        elapsed = time.perf_counter() - t0
        per_strategy[strat] = {
            "runs": reps,
            "identical_runs": identical,
            "mismatches": reps - identical,
            "all_identical": identical == reps,
            "reference_signature_sha256": first_sig,
            "reference_result": first_summary,
            "mismatch_samples": mismatches,
            "wall_time_s": round(elapsed, 3),
            "runs_per_second": round(reps / elapsed, 1) if elapsed > 0 else None,
        }
        print(f"  {dataset.split('/')[-1]:<40} {strat:<9} "
              f"{identical}/{reps} identical (mismatches={reps-identical})", flush=True)
    return {
        "dataset": dataset,
        "dataset_sha256": H.sha256_file(dpath),
        "data_rows": H.count_data_rows(dpath),
        "reps": reps,
        "side": SIDE,
        "quantity": QUANTITY,
        "status": "ok",
        "per_strategy": per_strategy,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="QuantExec determinism benchmark")
    ap.add_argument("--small-reps", type=int, default=1000)
    ap.add_argument("--large-reps", type=int, default=100)
    args = ap.parse_args()

    ex = H.import_executor()
    du = H.import_dataset_utils()

    print(f"[determinism] small dataset @ {args.small_reps} reps ...", flush=True)
    small = run_config(ex, du, SMALL_DATASET, args.small_reps)
    print(f"[determinism] large dataset @ {args.large_reps} reps ...", flush=True)
    large = run_config(ex, du, LARGE_DATASET, args.large_reps)

    configs = [small, large]
    total_runs = 0
    total_identical = 0
    for c in configs:
        if c.get("status") == "ok":
            for st in c["per_strategy"].values():
                total_runs += st["runs"]
                total_identical += st["identical_runs"]

    payload = {
        "_meta": H.new_meta(
            "determinism",
            "PYTHONPATH=build python3 benchmarks/determinism.py",
            extra={
                "engine": "real C++ ExecutionSession (run / run_pov / run_adaptive)",
                "method": "SHA-256 of full ExecutionResult + every fill; identical iff signatures match",
                "category": "OBSERVED (repeated real executions) -> CALCULATED identical-run counts",
            },
        ),
        "totals": {
            "total_runs": total_runs,
            "total_identical_runs": total_identical,
            "total_mismatches": total_runs - total_identical,
            "all_identical": total_runs == total_identical,
        },
        "configurations": configs,
    }
    out = H.write_json("determinism.json", payload)
    print(f"\nTOTAL: {total_identical}/{total_runs} identical. Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
