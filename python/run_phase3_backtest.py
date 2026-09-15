"""
Phase 3 entry point: controlled TWAP vs VWAP comparison over historical data.

    Historical Market Data (CSV, from alpaca_historical.py)
              |
    CsvMarketSource   <-- same class since Phase 1, chronological, no lookahead
              |
    Order Book / Matching Engine   <-- unchanged
              |
        ┌─────┴─────┐
        ▼           ▼
      TWAP         VWAP            <-- unchanged Phase 1 classes
        |           |
        └─────┬─────┘
              ▼
      Execution Analytics (incl. market impact decomposition)

Both strategies are run against a fresh CsvMarketSource pointed at the same
CSV file, so both see byte-identical market conditions - the whole point of
Phase 3's "controlled comparison" (section 3.4). Re-running this script on
the same file with the same arguments should print identical numbers every
time (section 3.3's reproducibility requirement); there's no randomness
anywhere in this path.

Usage:
    python3 run_phase3_backtest.py AAPL_historical.csv --qty 1000 --slices 6
"""

from __future__ import annotations

import argparse
import sys

from executor import CsvMarketSource, ExecutionSession, OrderSide, TWAPAlgorithm, VWAPAlgorithm


def run_one(path: str, algorithm_name: str, qty: int, slices: int,
            limit_price: float, arrival_price: float):
    if algorithm_name == "twap":
        algo = TWAPAlgorithm()
    else:
        algo = VWAPAlgorithm()
        # Even split by default; a real volume profile could be derived from
        # the same historical bars used to build the CSV (bar 'v' column).
        algo.set_volume_profile([1.0 / slices] * slices)

    orders = algo.generate_orders(1, OrderSide.Buy, qty, limit_price, slices)
    source = CsvMarketSource(path)  # fresh source per run: no shared iterator state
    session = ExecutionSession()
    return session.run(source, orders, arrival_price)


def print_result(name: str, result) -> None:
    print(f"\n--- {name} ---")
    print(f"Requested / Filled:        {result.requested_quantity} / {result.filled_quantity} "
          f"({result.fill_rate:.1%})")
    print(f"Completion time:           {result.completion_time_ms} ms")
    print(f"Arrival price:             {result.arrival_price:.4f}")
    print(f"Average execution price:   {result.average_execution_price:.4f}")
    print(f"Market VWAP:               {result.market_vwap:.4f}")
    print(f"Slippage:                  {result.slippage:.4%}")
    print(f"VWAP deviation:            {result.vwap_deviation:.4%}")
    print(f"Implementation shortfall:  {result.implementation_shortfall:.2f}")
    print("Market impact decomposition (see execution.h for caveats):")
    print(f"  market_price_drift:      {result.market_price_drift:.4%}  (overall market movement)")
    print(f"  estimated_spread_cost:   {result.estimated_spread_cost:.4%}  (cost of crossing the book once)")
    print(f"  estimated_execution_cost:{result.estimated_execution_cost:.4%}  (residual - not a clean causal estimate)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare TWAP and VWAP over identical historical data")
    parser.add_argument("csv_path")
    parser.add_argument("--qty", type=int, default=1000)
    parser.add_argument("--slices", type=int, default=6)
    parser.add_argument("--limit-price", type=float, default=None,
                        help="Marketable limit price for both strategies (default: derived from first row)")
    parser.add_argument("--arrival-price", type=float, default=None,
                        help="Benchmark arrival price (default: derived from first row's mid)")
    args = parser.parse_args()

    if args.limit_price is None or args.arrival_price is None:
        with open(args.csv_path) as f:
            header = f.readline().strip().split(",")
            first = dict(zip(header, f.readline().strip().split(",")))
        mid = (float(first["bid"]) + float(first["ask"])) / 2.0
        limit_price = args.limit_price if args.limit_price is not None else float(first["ask"]) * 1.02
        arrival_price = args.arrival_price if args.arrival_price is not None else mid
    else:
        limit_price, arrival_price = args.limit_price, args.arrival_price

    twap_result = run_one(args.csv_path, "twap", args.qty, args.slices, limit_price, arrival_price)
    vwap_result = run_one(args.csv_path, "vwap", args.qty, args.slices, limit_price, arrival_price)

    print(f"Comparing TWAP vs VWAP on {args.csv_path} "
          f"(qty={args.qty}, slices={args.slices}, same market data for both)")
    print_result("TWAP", twap_result)
    print_result("VWAP", vwap_result)

    print("\n--- Head-to-head ---")
    print(f"Slippage:  TWAP {twap_result.slippage:.4%}  vs  VWAP {vwap_result.slippage:.4%}")
    print(f"VWAP dev.: TWAP {twap_result.vwap_deviation:.4%}  vs  VWAP {vwap_result.vwap_deviation:.4%}")
    print(f"Fill rate: TWAP {twap_result.fill_rate:.1%}  vs  VWAP {vwap_result.fill_rate:.1%}")
    print("(Both saw market_price_drift = "
          f"{twap_result.market_price_drift:.4%} - identical, since it's the same underlying data.)")

    return 0


if __name__ == "__main__":
    sys.exit(main())