"""
Reproducible experiment runner (Phase 1, section 21).

Loads a YAML experiment config (see configs/example_experiment.yaml),
runs the requested strategy against the requested historical dataset
through the C++ engine (CsvMarketSource -> ExecutionSession), applies the
configured TransactionCostModel, and prints every input alongside the
result so the whole run can be reproduced from the printed output alone.

There is no randomness anywhere in this path: the same dataset + the same
config always produce the same ExecutionResult and the same costs.

Usage:
    python3 run_experiment.py configs/example_experiment.yaml
"""

from __future__ import annotations

import argparse
import sys

import yaml

from executor import (
    CsvMarketSource,
    ExecutionSession,
    OrderSide,
    TransactionCostConfig,
    TWAPAlgorithm,
    VWAPAlgorithm,
    compute_transaction_costs,
)


def load_config(path: str) -> dict:
    with open(path) as f:
        config = yaml.safe_load(f)

    required = ["symbol", "dataset", "side", "quantity", "slices", "strategy"]
    missing = [key for key in required if key not in config]
    if missing:
        raise ValueError(f"Config {path} is missing required keys: {missing}")
    return config


def resolve_prices(config: dict):
    """Derive limit_price / arrival_price from the dataset's first row when
    the config leaves them null - same default rule run_phase3_backtest.py
    uses, kept here so both entry points agree."""
    limit_price = config.get("limit_price")
    arrival_price = config.get("arrival_price")
    if limit_price is not None and arrival_price is not None:
        return float(limit_price), float(arrival_price)

    with open(config["dataset"]) as f:
        header = f.readline().strip().split(",")
        first = dict(zip(header, f.readline().strip().split(",")))
    mid = (float(first["bid"]) + float(first["ask"])) / 2.0
    if limit_price is None:
        limit_price = float(first["ask"]) * 1.02
    if arrival_price is None:
        arrival_price = mid
    return float(limit_price), float(arrival_price)


def build_algorithm(config: dict):
    strategy = config["strategy"].upper()
    if strategy == "TWAP":
        return TWAPAlgorithm()
    if strategy == "VWAP":
        algo = VWAPAlgorithm()
        profile = config.get("volume_profile")
        if profile:
            algo.set_volume_profile([float(p) for p in profile])
        # else: VWAPAlgorithm falls back to an even split internally.
        return algo
    raise ValueError(f"Unknown strategy '{config['strategy']}' (expected TWAP or VWAP)")


def run(config: dict):
    side = OrderSide.Buy if str(config["side"]).upper() == "BUY" else OrderSide.Sell
    limit_price, arrival_price = resolve_prices(config)
    algo = build_algorithm(config)

    orders = algo.generate_orders(1, side, int(config["quantity"]), limit_price, int(config["slices"]))
    source = CsvMarketSource(config["dataset"])
    if not source.ok():
        raise RuntimeError(
            f"Could not load dataset '{config['dataset']}' - check the path and "
            "the required CSV columns documented in dataset.md"
        )

    session = ExecutionSession()
    result = session.run(source, orders, arrival_price)

    cost_cfg = TransactionCostConfig()
    costs = config.get("costs", {}) or {}
    cost_cfg.commission_bps = float(costs.get("commission_bps", 0.0))
    cost_cfg.exchange_fee_bps = float(costs.get("exchange_fee_bps", 0.0))
    cost_cfg.fixed_fee_per_fill = float(costs.get("fixed_fee_per_fill", 0.0))
    cost_breakdown = compute_transaction_costs(result, cost_cfg)

    return result, cost_breakdown, limit_price, arrival_price


def print_report(config: dict, result, costs, limit_price: float, arrival_price: float) -> None:
    print(f"Symbol:          {config['symbol']}")
    print(f"Dataset:         {config['dataset']}")
    print(f"Strategy:        {config['strategy']}")
    print(f"Side / Quantity: {config['side']} {config['quantity']}")
    print(f"Slices:          {config['slices']}")
    print(f"Limit price:     {limit_price:.4f}")
    print(f"Arrival price:   {arrival_price:.4f}")
    print()
    print("--- Execution result ---")
    print(f"Requested / Filled:       {result.requested_quantity} / {result.filled_quantity} "
          f"({result.fill_rate:.1%})")
    print(f"Average execution price:  {result.average_execution_price:.4f}")
    print(f"Market VWAP:              {result.market_vwap:.4f}")
    print(f"Slippage:                 {result.slippage:.4%}")
    print(f"Implementation shortfall: {result.implementation_shortfall:.2f}")
    print()
    print("--- Transaction costs (configurable, see costs.h) ---")
    print(f"Commission:      {costs.commission:.4f}")
    print(f"Exchange fees:   {costs.exchange_fees:.4f}")
    print(f"Fixed fees:      {costs.fixed_fees:.4f}")
    print(f"Spread cost:     {costs.spread_cost:.4f}")
    print(f"Total cost:      {costs.total_cost:.4f}  ({costs.total_cost_bps:.2f} bps)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one reproducible execution experiment from a YAML config")
    parser.add_argument("config_path")
    args = parser.parse_args()

    config = load_config(args.config_path)
    result, costs, limit_price, arrival_price = run(config)
    print_report(config, result, costs, limit_price, arrival_price)
    return 0


if __name__ == "__main__":
    sys.exit(main())