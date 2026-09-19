#!/usr/bin/env python3
"""
Phase 2, Step 9: the one real experiment the brief asks for.

    AAPL, BUY, 5,000 shares, 09:30-10:30 ET (2024-01-03), TWAP vs VWAP vs POV,
    identical conditions for every strategy.

"Identical conditions" here means, for every strategy:
  - the same normalized historical dataset (same file, same sha256)
  - the same parent order (side=BUY, quantity=5000)
  - the same arrival price and limit price, derived the same way
    (mid/ask of the dataset's first row - the same rule run_experiment.py
    and compare_strategies.py already use, kept identical here on purpose)
  - the same TransactionCostConfig
  - num_slices=60, matching the dataset's 60 one-minute bars 1:1, so TWAP
    and VWAP each place exactly one child order per minute of the session
    (see historical-execution/normalize.py, step 2, for why minute
    granularity - not second granularity - is what makes `slices` mean
    what it says for this dataset)

This script does not modify the C++ engine or any Phase 1 strategy code;
it only calls the existing pybind11 bindings, exactly as
python/run_experiment.py and python/compare_strategies.py already do.

Usage:
    PYTHONPATH=../build python3 run_phase2_experiment.py
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

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
DATASET = REPO_ROOT / "datasets" / "historical" / "AAPL_2024-01-03_0930-1030ET.csv"
SYMBOL = "AAPL"
SIDE = OrderSide.Buy
QUANTITY = 5000
NUM_SLICES = 60  # one child order per one-minute bar - see module docstring
POV_PARTICIPATION = 0.2


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve_prices(dataset_path: Path) -> tuple[float, float]:
    """Same rule as run_experiment.py / compare_strategies.py: derive both
    prices from the dataset's first row so every strategy in this
    experiment gets an identical, dataset-derived benchmark."""
    with open(dataset_path, newline="") as f:
        reader = csv.DictReader(f)
        first = next(reader)
    bid, ask = float(first["bid"]), float(first["ask"])
    mid = (bid + ask) / 2.0
    limit_price = ask * 1.02
    arrival_price = mid
    return limit_price, arrival_price


def run_strategy(name: str, limit_price: float, arrival_price: float) -> dict:
    source = CsvMarketSource(str(DATASET))
    if not source.ok():
        raise RuntimeError(f"Could not load dataset {DATASET} - check schema per dataset.md")

    session = ExecutionSession()

    if name == "TWAP":
        algo = TWAPAlgorithm()
        orders = algo.generate_orders(1, SIDE, QUANTITY, limit_price, NUM_SLICES)
        result = session.run(source, orders, arrival_price)
    elif name == "VWAP":
        algo = VWAPAlgorithm()
        # No real volume_profile is available (no trade data acquired - see
        # LIMITATIONS.md), so VWAP falls back to an even split across
        # NUM_SLICES, identical to TWAP's schedule. This is disclosed, not
        # hidden: a meaningful VWAP profile needs real intraday volume,
        # which requires the trades this environment could not fetch.
        orders = algo.generate_orders(1, SIDE, QUANTITY, limit_price, NUM_SLICES)
        result = session.run(source, orders, arrival_price)
    elif name == "POV":
        pov = POVAlgorithm(POV_PARTICIPATION, 1, 0)
        result = session.run_pov(source, SIDE, QUANTITY, limit_price, pov, arrival_price)
    else:
        raise ValueError(name)

    cost_cfg = TransactionCostConfig()
    cost_cfg.commission_bps = 0.5
    cost_cfg.exchange_fee_bps = 0.1
    costs = compute_transaction_costs(result, cost_cfg)

    return {
        "strategy": name,
        "requested_quantity": result.requested_quantity,
        "filled_quantity": result.filled_quantity,
        "fill_rate": result.fill_rate,
        "average_execution_price": result.average_execution_price,
        "market_vwap": result.market_vwap,
        "slippage": result.slippage,
        "implementation_shortfall": result.implementation_shortfall,
        "vwap_deviation": result.vwap_deviation,
        "completion_time_ms": result.completion_time_ms,
        "commission": costs.commission,
        "exchange_fees": costs.exchange_fees,
        "spread_cost": costs.spread_cost,
        "total_cost_bps": costs.total_cost_bps,
    }


def main() -> int:
    checksum = sha256_of(DATASET)
    limit_price, arrival_price = resolve_prices(DATASET)

    print(f"Dataset:        {DATASET.relative_to(REPO_ROOT)}")
    print(f"Dataset sha256: {checksum}")
    print(f"Symbol/Side/Qty: {SYMBOL} BUY {QUANTITY}")
    print(f"Slices:         {NUM_SLICES}")
    print(f"Limit price:    {limit_price:.4f}")
    print(f"Arrival price:  {arrival_price:.4f}")
    print()

    results = [run_strategy(name, limit_price, arrival_price) for name in ("TWAP", "VWAP", "POV")]

    for r in results:
        print(f"--- {r['strategy']} ---")
        print(f"  Filled:                   {r['filled_quantity']} / {r['requested_quantity']} "
              f"({r['fill_rate']:.1%})")
        print(f"  Average execution price:  {r['average_execution_price']:.4f}")
        print(f"  Market VWAP (from data):  {r['market_vwap']:.4f}")
        print(f"  Slippage:                 {r['slippage']:.4%}")
        print(f"  Implementation shortfall: {r['implementation_shortfall']:.2f}")
        print(f"  Total cost:               {r['total_cost_bps']:.2f} bps")
        print()

    output = {
        "dataset": str(DATASET.relative_to(REPO_ROOT)),
        "dataset_sha256": checksum,
        "symbol": SYMBOL,
        "side": "BUY",
        "quantity": QUANTITY,
        "num_slices": NUM_SLICES,
        "pov_participation_rate": POV_PARTICIPATION,
        "limit_price": limit_price,
        "arrival_price": arrival_price,
        "results": results,
    }
    out_path = Path(__file__).resolve().parent / "phase2_experiment_results.json"
    out_path.write_text(json.dumps(output, indent=2))
    print(f"Wrote {out_path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
