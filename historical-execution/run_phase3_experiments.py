#!/usr/bin/env python3
"""
Phase 3: Execution Experiments + Analytics

This module implements Phase 3 as specified:
1. Clean experiment configuration system
2. Controlled comparisons (identical conditions, strategy varies only)
3. Multiple meaningful experiments (sides × sizes × strategies)
4. Comprehensive analytics reporting
5. Machine-readable results (CSV + JSON)
6. No overinterpretation (facts only, no bias)

Experiment matrix:
  - Sides: BUY, SELL
  - Order sizes (relative to observed liquidity):
    * Small: 500 shares   (typically 3-4 min of avg liquidity)
    * Medium: 2500 shares (typically 15-20 min of avg liquidity)
    * Large: 5000 shares  (typically 30+ min of avg liquidity)
  - Strategies: TWAP, VWAP, POV
  - Repeated for identical conditions, only strategy changes

Conventions for fairness:
  - All experiments use the same dataset file
  - All use the same 60-minute window (2024-01-03, 09:30-10:30 ET)
  - All use num_slices=60 (one child order per one-minute bar)
  - All derive limit/arrival prices from first row (same rule as Phase 2)
  - All use identical TransactionCostConfig
  - POV participation rate fixed at 20% (disclosed in config)
  - All latency assumptions identical (zero simulated latency)

Metrics reported per experiment:
  - requested_quantity
  - filled_quantity
  - unfilled_quantity (= requested - filled)
  - fill_rate
  - average_execution_price
  - arrival_price (market mid at first row)
  - market_vwap (computed from data)
  - slippage (avg_price - arrival_price, in bps)
  - implementation_shortfall (cost + slippage)
  - total_cost_bps
  - completion_time_ms
  - participation_rate (avg daily volume participation)
  - commission, exchange_fees, spread_cost (in bps)

Output:
  - phase3_results.csv: machine-readable results
  - phase3_results.json: detailed results + configuration
  - phase3_analysis.txt: human-readable summary

Usage:
    PYTHONPATH=../build python3 run_phase3_experiments.py
"""
from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import NamedTuple

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
NUM_SLICES = 60
POV_PARTICIPATION = 0.20  # 20% participation rate

# Experiment configuration matrix
SIDES = [OrderSide.Buy, OrderSide.Sell]
SIZE_CONFIGS = {
    "small": 500,
    "medium": 2500,
    "large": 5000,
}
STRATEGIES = ["TWAP", "VWAP", "POV"]


@dataclass
class ExperimentConfig:
    """Specification for a single experiment. Ensures all conditions except
    strategy are identical."""
    dataset_path: Path
    symbol: str
    side: str  # "BUY" or "SELL"
    quantity: int
    strategy: str  # "TWAP", "VWAP", or "POV"
    num_slices: int
    pov_participation: float
    commission_bps: float
    exchange_fee_bps: float
    
    def to_dict(self) -> dict:
        return {
            "dataset": str(self.dataset_path.relative_to(REPO_ROOT)),
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "strategy": self.strategy,
            "num_slices": self.num_slices,
            "pov_participation": self.pov_participation,
            "commission_bps": self.commission_bps,
            "exchange_fee_bps": self.exchange_fee_bps,
        }


class ExecutionResult(NamedTuple):
    """Single experiment's measured result."""
    config: ExperimentConfig
    requested_quantity: int
    filled_quantity: int
    unfilled_quantity: int
    fill_rate: float
    average_execution_price: float
    arrival_price: float
    market_vwap: float
    slippage_bps: float
    implementation_shortfall: float
    total_cost_bps: float
    completion_time_ms: float
    participation_rate: float
    commission_bps: float
    exchange_fees_bps: float
    spread_cost_bps: float


def sha256_of(path: Path) -> str:
    """Compute SHA256 of file for reproducibility tracking."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve_prices(dataset_path: Path, side: str) -> tuple[float, float]:
    """Derive limit and arrival prices from dataset's first row.
    
    For BUY orders: limit_price = ask * 1.02 (willing to pay more)
    For SELL orders: limit_price = bid * 0.98 (willing to accept less)
    Arrival price (market mid) is identical for both sides.
    """
    with open(dataset_path, newline="") as f:
        reader = csv.DictReader(f)
        first = next(reader)
    bid, ask = float(first["bid"]), float(first["ask"])
    mid = (bid + ask) / 2.0
    
    if side == "BUY":
        limit_price = ask * 1.02  # Willing to pay up to 2% above ask
    else:  # SELL
        limit_price = bid * 0.98  # Willing to accept down to 2% below bid
    
    arrival_price = mid
    return limit_price, arrival_price


def load_market_data(dataset_path: Path) -> list[dict]:
    """Load market data rows for later analysis."""
    rows = []
    with open(dataset_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({
                "bid": float(row["bid"]),
                "ask": float(row["ask"]),
                "bid_size": int(row["bid_size"]),
                "ask_size": int(row["ask_size"]),
            })
    return rows


def compute_participation_rate(
    filled_quantity: int,
    market_data: list[dict],
) -> float:
    """Estimate daily volume participation rate.
    
    Assumes average quoted size represents instantaneous available volume.
    Daily volume participation = filled_qty / (avg_size * minutes * 390_minutes_per_day)
    """
    if not market_data or filled_quantity == 0:
        return 0.0
    
    avg_size = sum(row["bid_size"] + row["ask_size"] for row in market_data) / (
        len(market_data) * 2
    )
    minutes_traded = len(market_data)
    estimated_daily_volume = avg_size * 390  # 390 minutes in a trading day
    participation = filled_quantity / estimated_daily_volume if estimated_daily_volume > 0 else 0.0
    return min(participation, 1.0)  # Cap at 100%


def run_experiment(config: ExperimentConfig) -> ExecutionResult:
    """Execute a single experiment under controlled conditions."""
    # Load and validate dataset
    source = CsvMarketSource(str(config.dataset_path))
    if not source.ok():
        raise RuntimeError(f"Could not load dataset {config.dataset_path}")
    
    # Resolve prices (both strategies use identical prices)
    limit_price, arrival_price = resolve_prices(config.dataset_path, config.side)
    
    # Create session
    session = ExecutionSession()
    
    # Determine side for C++ engine
    if config.side == "BUY":
        cpp_side = OrderSide.Buy
    elif config.side == "SELL":
        cpp_side = OrderSide.Sell
    else:
        raise ValueError(f"Invalid side: {config.side}")
    
    # Run strategy
    if config.strategy == "TWAP":
        algo = TWAPAlgorithm()
        orders = algo.generate_orders(1, cpp_side, config.quantity, limit_price, config.num_slices)
        cpp_result = session.run(source, orders, arrival_price)
    elif config.strategy == "VWAP":
        algo = VWAPAlgorithm()
        orders = algo.generate_orders(1, cpp_side, config.quantity, limit_price, config.num_slices)
        cpp_result = session.run(source, orders, arrival_price)
    elif config.strategy == "POV":
        pov = POVAlgorithm(config.pov_participation, 1, 0)
        cpp_result = session.run_pov(source, cpp_side, config.quantity, limit_price, pov, arrival_price)
    else:
        raise ValueError(f"Invalid strategy: {config.strategy}")
    
    # Compute transaction costs
    cost_cfg = TransactionCostConfig()
    cost_cfg.commission_bps = config.commission_bps
    cost_cfg.exchange_fee_bps = config.exchange_fee_bps
    costs = compute_transaction_costs(cpp_result, cost_cfg)
    
    # Compute participation rate
    market_data = load_market_data(config.dataset_path)
    participation_rate = compute_participation_rate(cpp_result.filled_quantity, market_data)
    
    # Package result
    return ExecutionResult(
        config=config,
        requested_quantity=cpp_result.requested_quantity,
        filled_quantity=cpp_result.filled_quantity,
        unfilled_quantity=cpp_result.requested_quantity - cpp_result.filled_quantity,
        fill_rate=cpp_result.fill_rate,
        average_execution_price=cpp_result.average_execution_price,
        arrival_price=arrival_price,
        market_vwap=cpp_result.market_vwap,
        slippage_bps=cpp_result.slippage * 10000,  # Convert to bps
        implementation_shortfall=cpp_result.implementation_shortfall,
        total_cost_bps=costs.total_cost_bps,
        completion_time_ms=cpp_result.completion_time_ms,
        participation_rate=participation_rate,
        commission_bps=costs.commission / cpp_result.filled_quantity if cpp_result.filled_quantity > 0 else 0.0,
        exchange_fees_bps=costs.exchange_fees / cpp_result.filled_quantity if cpp_result.filled_quantity > 0 else 0.0,
        spread_cost_bps=costs.spread_cost / cpp_result.filled_quantity if cpp_result.filled_quantity > 0 else 0.0,
    )


def generate_experiment_matrix() -> list[ExperimentConfig]:
    """Generate the full controlled experiment matrix.
    
    Matrix structure:
      - 2 sides × 3 sizes × 3 strategies = 18 experiments
      - All identical conditions except strategy varies
      - Same dataset, same time window, same prices, same cost assumptions
    """
    configs = []
    
    for side in SIDES:
        side_str = "BUY" if side == OrderSide.Buy else "SELL"
        
        for size_label, quantity in SIZE_CONFIGS.items():
            
            for strategy in STRATEGIES:
                config = ExperimentConfig(
                    dataset_path=DATASET,
                    symbol=SYMBOL,
                    side=side_str,
                    quantity=quantity,
                    strategy=strategy,
                    num_slices=NUM_SLICES,
                    pov_participation=POV_PARTICIPATION,
                    commission_bps=0.5,
                    exchange_fee_bps=0.1,
                )
                configs.append(config)
    
    return configs


def write_csv_results(results: list[ExecutionResult], output_path: Path) -> None:
    """Write results to machine-readable CSV format."""
    with open(output_path, "w", newline="") as f:
        fieldnames = [
            "side",
            "quantity",
            "size_category",
            "strategy",
            "requested_quantity",
            "filled_quantity",
            "unfilled_quantity",
            "fill_rate",
            "average_execution_price",
            "arrival_price",
            "slippage_bps",
            "implementation_shortfall",
            "total_cost_bps",
            "commission_bps",
            "exchange_fees_bps",
            "spread_cost_bps",
            "completion_time_ms",
            "participation_rate",
            "market_vwap",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        
        for result in results:
            # Infer size category
            size_cat = None
            for label, qty in SIZE_CONFIGS.items():
                if result.config.quantity == qty:
                    size_cat = label
                    break
            
            writer.writerow({
                "side": result.config.side,
                "quantity": result.config.quantity,
                "size_category": size_cat or "unknown",
                "strategy": result.config.strategy,
                "requested_quantity": result.requested_quantity,
                "filled_quantity": result.filled_quantity,
                "unfilled_quantity": result.unfilled_quantity,
                "fill_rate": f"{result.fill_rate:.4f}",
                "average_execution_price": f"{result.average_execution_price:.4f}",
                "arrival_price": f"{result.arrival_price:.4f}",
                "slippage_bps": f"{result.slippage_bps:.2f}",
                "implementation_shortfall": f"{result.implementation_shortfall:.2f}",
                "total_cost_bps": f"{result.total_cost_bps:.2f}",
                "commission_bps": f"{result.commission_bps:.2f}",
                "exchange_fees_bps": f"{result.exchange_fees_bps:.2f}",
                "spread_cost_bps": f"{result.spread_cost_bps:.2f}",
                "completion_time_ms": f"{result.completion_time_ms:.0f}",
                "participation_rate": f"{result.participation_rate:.4f}",
                "market_vwap": f"{result.market_vwap:.4f}",
            })


def write_json_results(
    results: list[ExecutionResult],
    dataset_sha256: str,
    output_path: Path,
) -> None:
    """Write detailed results to JSON format with full configuration."""
    output = {
        "phase": 3,
        "description": "Controlled execution experiments with identical conditions, strategies vary only",
        "dataset": str(DATASET.relative_to(REPO_ROOT)),
        "dataset_sha256": dataset_sha256,
        "symbol": SYMBOL,
        "experiment_window": "2024-01-03 09:30-10:30 ET (60 one-minute bars)",
        "pov_participation_rate": POV_PARTICIPATION,
        "num_experiments": len(results),
        "matrix": {
            "sides": [s.name for s in SIDES],
            "size_categories": list(SIZE_CONFIGS.keys()),
            "sizes": SIZE_CONFIGS,
            "strategies": STRATEGIES,
        },
        "cost_assumptions": {
            "commission_bps": 0.5,
            "exchange_fee_bps": 0.1,
        },
        "results": [
            {
                "config": result.config.to_dict(),
                "metrics": {
                    "requested_quantity": result.requested_quantity,
                    "filled_quantity": result.filled_quantity,
                    "unfilled_quantity": result.unfilled_quantity,
                    "fill_rate": round(result.fill_rate, 6),
                    "average_execution_price": round(result.average_execution_price, 4),
                    "arrival_price": round(result.arrival_price, 4),
                    "market_vwap": round(result.market_vwap, 4),
                    "slippage_bps": round(result.slippage_bps, 2),
                    "implementation_shortfall": round(result.implementation_shortfall, 2),
                    "total_cost_bps": round(result.total_cost_bps, 2),
                    "commission_bps": round(result.commission_bps, 2),
                    "exchange_fees_bps": round(result.exchange_fees_bps, 2),
                    "spread_cost_bps": round(result.spread_cost_bps, 2),
                    "completion_time_ms": round(result.completion_time_ms, 1),
                    "participation_rate": round(result.participation_rate, 6),
                },
            }
            for result in results
        ],
    }
    output_path.write_text(json.dumps(output, indent=2))


def write_analysis(results: list[ExecutionResult], output_path: Path) -> None:
    """Write human-readable analysis and summary."""
    lines = []
    
    lines.append("=" * 80)
    lines.append("PHASE 3: EXECUTION EXPERIMENTS + ANALYTICS")
    lines.append("=" * 80)
    lines.append("")
    lines.append(f"Dataset:     {DATASET.relative_to(REPO_ROOT)}")
    lines.append(f"Symbol:      {SYMBOL}")
    lines.append(f"Window:      2024-01-03 09:30-10:30 ET (60 one-minute bars)")
    lines.append(f"Experiments: {len(results)}")
    lines.append("")
    
    lines.append("EXPERIMENT CONFIGURATION")
    lines.append("-" * 80)
    lines.append(f"Sides:              {', '.join(s.name for s in SIDES)}")
    lines.append(f"Order sizes:        {', '.join(f'{v} ({k})' for k, v in SIZE_CONFIGS.items())}")
    lines.append(f"Strategies:         {', '.join(STRATEGIES)}")
    lines.append(f"Dataset slices:     {NUM_SLICES} (one per one-minute bar)")
    lines.append(f"Resampling:         One-minute bars")
    lines.append(f"Latency:            Zero (simulated)")
    lines.append(f"Commission:         0.5 bps")
    lines.append(f"Exchange fee:       0.1 bps")
    lines.append(f"POV participation:  {POV_PARTICIPATION:.1%}")
    lines.append("")
    
    # Fairness statement
    lines.append("FAIRNESS STATEMENT")
    lines.append("-" * 80)
    lines.append("All experiments use identical conditions EXCEPT strategy:")
    lines.append("  ✓ Same dataset file (same sha256)")
    lines.append("  ✓ Same time window (2024-01-03, 09:30-10:30 ET)")
    lines.append("  ✓ Same limit/arrival prices (derived from first row)")
    lines.append("  ✓ Same number of slices (60 = one per minute)")
    lines.append("  ✓ Same transaction cost assumptions")
    lines.append("  ✓ Same latency assumptions (zero)")
    lines.append("  ✓ Strategy is the ONLY variable")
    lines.append("")
    
    # Results by category
    lines.append("RESULTS SUMMARY")
    lines.append("-" * 80)
    lines.append("")
    
    # Group by side and size
    from collections import defaultdict
    grouped = defaultdict(list)
    for result in results:
        key = (result.config.side, result.config.quantity)
        grouped[key].append(result)
    
    for (side, qty), group in sorted(grouped.items()):
        size_label = None
        for label, q in SIZE_CONFIGS.items():
            if q == qty:
                size_label = label
                break
        
        lines.append(f"{side} {qty} shares ({size_label}):")
        lines.append("  " + "-" * 76)
        lines.append(f"  {'Strategy':<10} {'Filled':<12} {'Fill%':<10} {'Avg Price':<12} {'Slippage':<12} {'Cost (bps)':<12}")
        lines.append("  " + "-" * 76)
        
        for result in sorted(group, key=lambda r: r.config.strategy):
            filled_str = f"{result.filled_quantity}/{result.requested_quantity}"
            fill_pct = f"{result.fill_rate:.1%}"
            avg_price = f"{result.average_execution_price:.4f}"
            slippage = f"{result.slippage_bps:.2f} bps"
            cost = f"{result.total_cost_bps:.2f}"
            
            lines.append(
                f"  {result.config.strategy:<10} {filled_str:<12} {fill_pct:<10} "
                f"{avg_price:<12} {slippage:<12} {cost:<12}"
            )
        lines.append("")
    
    # Key observations (factual only, no overinterpretation)
    lines.append("KEY OBSERVATIONS")
    lines.append("-" * 80)
    
    # Check fill rates
    twap_results = [r for r in results if r.config.strategy == "TWAP"]
    vwap_results = [r for r in results if r.config.strategy == "VWAP"]
    pov_results = [r for r in results if r.config.strategy == "POV"]
    
    lines.append("Fill rates:")
    lines.append(f"  TWAP: {sum(r.fill_rate for r in twap_results) / len(twap_results):.1%} average")
    lines.append(f"  VWAP: {sum(r.fill_rate for r in vwap_results) / len(vwap_results):.1%} average")
    lines.append(f"  POV:  {sum(r.fill_rate for r in pov_results) / len(pov_results):.1%} average")
    lines.append("")
    
    lines.append("Average slippage (bps):")
    lines.append(f"  TWAP: {sum(r.slippage_bps for r in twap_results) / len(twap_results):.2f} bps")
    lines.append(f"  VWAP: {sum(r.slippage_bps for r in vwap_results) / len(vwap_results):.2f} bps")
    lines.append(f"  POV:  {sum(r.slippage_bps for r in pov_results) / len(pov_results):.2f} bps")
    lines.append("")
    
    lines.append("Average total cost (bps):")
    lines.append(f"  TWAP: {sum(r.total_cost_bps for r in twap_results) / len(twap_results):.2f} bps")
    lines.append(f"  VWAP: {sum(r.total_cost_bps for r in vwap_results) / len(vwap_results):.2f} bps")
    lines.append(f"  POV:  {sum(r.total_cost_bps for r in pov_results) / len(pov_results):.2f} bps")
    lines.append("")
    
    # Caveats
    lines.append("INTERPRETATION CAVEATS")
    lines.append("-" * 80)
    lines.append("Strategy performance varies with:")
    lines.append("  • Market conditions (price volatility, trending)")
    lines.append("  • Order size (small orders have higher fill rates)")
    lines.append("  • Execution window (longer windows allow more passive fills)")
    lines.append("  • Available liquidity (changes by time and symbol)")
    lines.append("  • Assumptions (fees, latency, tick sizes, market impact)")
    lines.append("")
    lines.append("These results demonstrate behavior under ONE set of historical")
    lines.append("conditions. Do not generalize to other markets, times, or assumptions.")
    lines.append("")
    
    # Data provenance
    lines.append("DATA PROVENANCE")
    lines.append("-" * 80)
    lines.append(f"Symbol:             {SYMBOL}")
    lines.append(f"Date:               2024-01-03")
    lines.append(f"Time window:        09:30-10:30 ET (60 one-minute bars)")
    lines.append(f"Source:             Alpaca IEX feed")
    lines.append(f"Data type:          Quote replay (no trades, no depth)")
    lines.append(f"Raw quote count:    325,196 (processed to 60 after normalization)")
    lines.append(f"Normalization:")
    lines.append(f"  - Bad prints removed (crossed bid/ask, outliers 2%+ from median)")
    lines.append(f"  - Resampled to one-minute bars")
    lines.append(f"  - Quote sizes converted from round lots to shares")
    lines.append("")
    
    lines.append("=" * 80)
    lines.append("END OF ANALYSIS")
    lines.append("=" * 80)
    
    output_path.write_text("\n".join(lines))


def main() -> int:
    # Verify dataset exists and compute checksum
    if not DATASET.exists():
        print(f"ERROR: Dataset not found: {DATASET}")
        return 1
    
    dataset_sha256 = sha256_of(DATASET)
    
    print("=" * 80)
    print("PHASE 3: EXECUTION EXPERIMENTS + ANALYTICS")
    print("=" * 80)
    print()
    print(f"Dataset:        {DATASET.relative_to(REPO_ROOT)}")
    print(f"Dataset sha256: {dataset_sha256}")
    print(f"Experiments:    {len(SIDES)} sides × {len(SIZE_CONFIGS)} sizes × {len(STRATEGIES)} strategies = {len(SIDES) * len(SIZE_CONFIGS) * len(STRATEGIES)} total")
    print()
    
    # Generate and run experiments
    configs = generate_experiment_matrix()
    results = []
    
    for i, config in enumerate(configs, 1):
        print(f"[{i:2d}/{len(configs)}] {config.side:4s} {config.quantity:5d} shares {config.strategy:4s}...", end=" ", flush=True)
        try:
            result = run_experiment(config)
            results.append(result)
            print(f"✓ ({result.filled_quantity}/{result.requested_quantity}, {result.fill_rate:.1%})")
        except Exception as e:
            print(f"✗ FAILED: {e}")
            return 1
    
    print()
    
    # Write outputs
    output_dir = Path(__file__).resolve().parent
    
    csv_path = output_dir / "phase3_results.csv"
    write_csv_results(results, csv_path)
    print(f"Wrote {csv_path.relative_to(REPO_ROOT)}")
    
    json_path = output_dir / "phase3_results.json"
    write_json_results(results, dataset_sha256, json_path)
    print(f"Wrote {json_path.relative_to(REPO_ROOT)}")
    
    analysis_path = output_dir / "phase3_analysis.txt"
    write_analysis(results, analysis_path)
    print(f"Wrote {analysis_path.relative_to(REPO_ROOT)}")
    
    print()
    print("Phase 3 experiments complete. Results ready in:")
    print(f"  - CSV: {csv_path.relative_to(REPO_ROOT)}")
    print(f"  - JSON: {json_path.relative_to(REPO_ROOT)}")
    print(f"  - Analysis: {analysis_path.relative_to(REPO_ROOT)}")
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
