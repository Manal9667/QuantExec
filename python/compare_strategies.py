#!/usr/bin/env python3
"""
Fair strategy comparison across sessions, sizes, and market regimes (Step 5).

Answers the question this whole project exists to answer:

    "Given the same historical [or, currently, synthetic/stress] market
    conditions, how would different execution algorithms have executed
    the same parent order, and why did their results differ?"

Every strategy in one run receives EXACTLY the same:
  - dataset (and therefore the same market data, same checksum)
  - parent order (side, quantity, time window)
  - arrival price / limit-price derivation rule
  - cost model

This is what "fair" means here: no strategy gets a data or config
advantage over another. What's compared:
    TWAP  vs  VWAP  vs  POV  vs  an immediate-execution baseline
                                 (single order, submitted at the first
                                 replayed event - TWAP with num_slices=1)

across every (dataset x quantity) combination in the sweep, so a claim
like "VWAP beat TWAP" is backed by a distribution over conditions, not one
lucky run.

Usage:
    PYTHONPATH=build python3 python/compare_strategies.py \
        --datasets datasets/sample_synthetic.csv datasets/stress/*.csv \
        --quantities 200 1000 5000 \
        --out-json comparison_results.json --out-csv comparison_results.csv
"""
from __future__ import annotations

import argparse
import csv as csv_module
import glob
import hashlib
import json
import statistics
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

from executor import (
    CsvMarketSource,
    ExecutionSession,
    OrderSide,
    POVAlgorithm,
    TransactionCostConfig,
    TWAPAlgorithm,
    VWAPAlgorithm,
    compute_transaction_costs,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
STRATEGIES = ["IMMEDIATE", "TWAP", "VWAP", "POV"]


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve_prices(dataset_path: Path) -> tuple[float, float]:
    """Same rule as run_experiment.py / experiment_service.py: derive from
    the dataset's first row so every strategy in the sweep gets an
    identical, dataset-derived benchmark - never a per-strategy guess."""
    with open(dataset_path, newline="") as f:
        reader = csv_module.DictReader(f)
        first = next(reader)
    bid, ask = float(first["bid"]), float(first["ask"])
    mid = (bid + ask) / 2.0
    limit_price = ask * 1.02
    arrival_price = mid
    return limit_price, arrival_price


@dataclass
class RunRecord:
    result_id: str
    dataset: str
    dataset_checksum: str
    strategy: str
    side: str
    requested_quantity: int
    filled_quantity: int
    completion_rate: float
    average_execution_price: float
    market_vwap: float
    implementation_shortfall: float
    slippage: float
    spread_cost: float
    explicit_fees: float
    participation_rate: float
    time_to_completion_ms: int
    unfilled_quantity: int
    failed: bool
    failure_reason: Optional[str] = None


def make_result_id(dataset_checksum: str, strategy: str, side: str, quantity: int) -> str:
    """Deterministic ID from configuration + dataset checksum (Step 5,
    'generate a deterministic result ID from the configuration and dataset
    checksum'). Same inputs always produce the same ID, so a result can be
    referenced without re-running anything."""
    payload = f"{dataset_checksum}|{strategy}|{side}|{quantity}"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def run_one(dataset_path: Path, checksum: str, strategy: str, side: OrderSide, quantity: int) -> RunRecord:
    side_str = "BUY" if side == OrderSide.Buy else "SELL"
    result_id = make_result_id(checksum, strategy, side_str, quantity)

    try:
        limit_price, arrival_price = resolve_prices(dataset_path)
        source = CsvMarketSource(str(dataset_path))
        if not source.ok():
            raise RuntimeError(f"Dataset failed to load: {dataset_path}")

        session = ExecutionSession()
        num_slices = 5

        if strategy == "IMMEDIATE":
            algo = TWAPAlgorithm()
            orders = algo.generate_orders(1, side, quantity, limit_price, 1)
            result = session.run(source, orders, arrival_price)
            participation_rate = 0.0
        elif strategy == "TWAP":
            algo = TWAPAlgorithm()
            orders = algo.generate_orders(1, side, quantity, limit_price, num_slices)
            result = session.run(source, orders, arrival_price)
            participation_rate = 0.0
        elif strategy == "VWAP":
            # Use an explicit, non-uniform profile so this comparison is not
            # silently the same as TWAP. This is a documented assumption for the
            # fairness sweep, not a hidden default that happens to work.
            algo = VWAPAlgorithm()
            algo.set_volume_profile([0.35, 0.25, 0.20, 0.12, 0.08])
            orders = algo.generate_orders(1, side, quantity, limit_price, num_slices)
            result = session.run(source, orders, arrival_price)
            participation_rate = 0.0
        elif strategy == "POV":
            pov = POVAlgorithm(0.2, 1, 0)  # 20% participation, same for every dataset/size
            result = session.run_pov(source, side, quantity, limit_price, pov, arrival_price)
            participation_rate = 0.2
        else:
            raise ValueError(f"Unknown strategy {strategy}")

        cost_cfg = TransactionCostConfig()
        cost_cfg.commission_bps = 0.5
        cost_cfg.exchange_fee_bps = 0.1
        costs = compute_transaction_costs(result, cost_cfg)

        return RunRecord(
            result_id=result_id,
            dataset=str(dataset_path),
            dataset_checksum=checksum,
            strategy=strategy,
            side=side_str,
            requested_quantity=result.requested_quantity,
            filled_quantity=result.filled_quantity,
            completion_rate=result.fill_rate,
            average_execution_price=result.average_execution_price,
            market_vwap=result.market_vwap,
            implementation_shortfall=result.implementation_shortfall,
            slippage=result.slippage,
            spread_cost=costs.spread_cost,
            explicit_fees=costs.commission + costs.exchange_fees + costs.fixed_fees,
            participation_rate=participation_rate,
            time_to_completion_ms=result.completion_time_ms,
            unfilled_quantity=result.requested_quantity - result.filled_quantity,
            failed=False,
        )
    except Exception as exc:  # noqa: BLE001 - a failed run is a first-class, reported outcome
        return RunRecord(
            result_id=result_id,
            dataset=str(dataset_path),
            dataset_checksum=checksum,
            strategy=strategy,
            side=side_str,
            requested_quantity=quantity,
            filled_quantity=0,
            completion_rate=0.0,
            average_execution_price=0.0,
            market_vwap=0.0,
            implementation_shortfall=0.0,
            slippage=0.0,
            spread_cost=0.0,
            explicit_fees=0.0,
            participation_rate=0.0,
            time_to_completion_ms=0,
            unfilled_quantity=quantity,
            failed=True,
            failure_reason=str(exc),
        )


def summarize(records: list[RunRecord]) -> dict:
    """Mean, median, stdev, percentiles, and failure counts per strategy -
    Step 5's requirement that results carry distributions, not just
    averages."""
    by_strategy: dict[str, list[RunRecord]] = {s: [] for s in STRATEGIES}
    for r in records:
        by_strategy[r.strategy].append(r)

    summary = {}
    for strategy, runs in by_strategy.items():
        ok_runs = [r for r in runs if not r.failed]
        failed_count = len(runs) - len(ok_runs)
        if not ok_runs:
            summary[strategy] = {"runs": len(runs), "failed": failed_count, "note": "no successful runs"}
            continue

        def stats_for(values: list[float]) -> dict:
            values_sorted = sorted(values)
            n = len(values_sorted)
            return {
                "mean": statistics.mean(values_sorted),
                "median": statistics.median(values_sorted),
                "stdev": statistics.pstdev(values_sorted) if n > 1 else 0.0,
                "p10": values_sorted[max(0, int(0.10 * (n - 1)))],
                "p90": values_sorted[max(0, int(0.90 * (n - 1)))],
                "min": values_sorted[0],
                "max": values_sorted[-1],
            }

        summary[strategy] = {
            "runs": len(runs),
            "failed": failed_count,
            "completion_rate": stats_for([r.completion_rate for r in ok_runs]),
            "slippage": stats_for([r.slippage for r in ok_runs]),
            "implementation_shortfall": stats_for([r.implementation_shortfall for r in ok_runs]),
            "spread_cost": stats_for([r.spread_cost for r in ok_runs]),
            "explicit_fees": stats_for([r.explicit_fees for r in ok_runs]),
            "unfilled_quantity": stats_for([r.unfilled_quantity for r in ok_runs]),
        }
    return summary


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--datasets", nargs="+", required=True, help="Dataset paths or globs")
    parser.add_argument("--quantities", nargs="+", type=int, default=[200, 1000])
    parser.add_argument("--sides", nargs="+", default=["BUY", "SELL"])
    parser.add_argument("--out-json", type=Path, default=REPO_ROOT / "comparison_results.json")
    parser.add_argument("--out-csv", type=Path, default=REPO_ROOT / "comparison_results.csv")
    args = parser.parse_args(argv)

    dataset_paths: list[Path] = []
    for pattern in args.datasets:
        matched = glob.glob(pattern)
        dataset_paths.extend(Path(p) for p in (matched or [pattern]))
    dataset_paths = sorted(set(dataset_paths))

    checksums = {str(p): sha256_of(p) for p in dataset_paths}

    records: list[RunRecord] = []
    for dataset_path in dataset_paths:
        checksum = checksums[str(dataset_path)]
        for side_str in args.sides:
            side = OrderSide.Buy if side_str == "BUY" else OrderSide.Sell
            for quantity in args.quantities:
                for strategy in STRATEGIES:
                    records.append(run_one(dataset_path, checksum, strategy, side, quantity))

    summary = summarize(records)

    output = {
        "sweep": {
            "datasets": [{"path": str(p), "sha256": checksums[str(p)]} for p in dataset_paths],
            "quantities": args.quantities,
            "sides": args.sides,
            "strategies": STRATEGIES,
            "total_runs": len(records),
        },
        "summary": summary,
        "runs": [asdict(r) for r in records],
    }

    args.out_json.write_text(json.dumps(output, indent=2))

    with open(args.out_csv, "w", newline="") as f:
        writer = csv_module.DictWriter(f, fieldnames=list(asdict(records[0]).keys()))
        writer.writeheader()
        for r in records:
            writer.writerow(asdict(r))

    print(f"Ran {len(records)} experiments across {len(dataset_paths)} dataset(s), "
          f"{len(args.quantities)} size(s), {len(args.sides)} side(s), {len(STRATEGIES)} strategies.")
    print(f"Wrote {args.out_json} and {args.out_csv}")
    print()
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
