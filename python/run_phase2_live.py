"""
Phase 2 entry point: run TWAP/VWAP against real market conditions via Alpaca.

    Real Market Data (Alpaca)
           |
    Real Market State            <- alpaca_adapter.snapshot_to_market_state
           |
    Order Book / Matching Engine <- unchanged from Phase 1
           |
    TWAP / VWAP                  <- unchanged from Phase 1 (same C++ classes)
           |
    Fills + ExecutionResult

This intentionally re-uses executor.TWAPAlgorithm / executor.VWAPAlgorithm
and executor.ExecutionSession exactly as Phase 1 does. The only Phase-2-
specific code is AlpacaRealtimeAdapter, which produces the same
executor.MarketSnapshot objects VectorMarketSource/CsvMarketSource produce.

Usage:
    export ALPACA_API_KEY_ID=...
    export ALPACA_API_SECRET_KEY=...
    python3 run_phase2_live.py AAPL --qty 500 --slices 5 --interval 5 --algo twap

Note: this polls Alpaca's REST snapshot endpoint once per slice rather than
streaming, which is simpler and fine for a personal project on the free
tier. Swap in a websocket client behind the same AlpacaRealtimeAdapter.source
interface later without touching anything below this adapter.
"""

from __future__ import annotations

import argparse
import sys
import time

from alpaca_adapter import (
    AlpacaCredentials,
    AlpacaMarketDataClient,
    AlpacaRealtimeAdapter,
    AlpacaAuthError,
)
from executor import ExecutionSession, OrderSide, TWAPAlgorithm, VWAPAlgorithm


def build_algorithm(name: str):
    if name == "twap":
        return TWAPAlgorithm()
    if name == "vwap":
        algo = VWAPAlgorithm()
        # Simple front-loaded default profile; override with real intraday
        # volume curves once Phase 3's historical data is available.
        algo.set_volume_profile([0.3, 0.25, 0.2, 0.15, 0.1])
        return algo
    raise ValueError(f"Unknown algorithm: {name}")


def marketable_limit_price(side: str, arrival_state, buffer_pct: float = 0.02) -> float:
    """
    TWAPAlgorithm/VWAPAlgorithm always create Limit orders (see algorithms.cpp),
    matching the convention test_phase.cpp uses for synthetic sources. To get
    "market-like" behavior against a real quote, pass a price aggressive
    enough to cross the book: above the ask for buys, below the bid for sells.
    A fixed 2% buffer is a blunt instrument - for real use, size the buffer to
    the symbol's typical spread/volatility instead of a flat percentage.
    """
    if side == "buy":
        return arrival_state.ask * (1.0 + buffer_pct)
    return arrival_state.bid * (1.0 - buffer_pct)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run TWAP/VWAP against live Alpaca market data")
    parser.add_argument("symbol")
    parser.add_argument("--qty", type=int, default=500, help="Total shares to buy")
    parser.add_argument("--slices", type=int, default=5, help="Number of child orders")
    parser.add_argument("--interval", type=float, default=5.0, help="Seconds between polls")
    parser.add_argument("--algo", choices=["twap", "vwap"], default="twap")
    parser.add_argument("--side", choices=["buy", "sell"], default="buy")
    args = parser.parse_args()

    try:
        credentials = AlpacaCredentials.from_env()
    except AlpacaAuthError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    client = AlpacaMarketDataClient(credentials)
    adapter = AlpacaRealtimeAdapter(client)

    # Arrival price: the mid at the moment we decide to trade, used as the
    # execution-quality benchmark (slippage, implementation shortfall).
    arrival_snapshot = adapter.poll_once(args.symbol)
    if arrival_snapshot is None:
        print(f"error: no usable quote for {args.symbol} right now (market closed?)", file=sys.stderr)
        return 1
    arrival_price = arrival_snapshot.mid_price

    side = OrderSide.Buy if args.side == "buy" else OrderSide.Sell
    algorithm = build_algorithm(args.algo)
    limit_price = marketable_limit_price(args.side, arrival_snapshot)
    orders = algorithm.generate_orders(1, side, args.qty, limit_price, args.slices)
    print(f"{args.algo.upper()} split {args.qty} shares into {len(orders)} slices: "
          f"{[o.qty for o in orders]}")

    for i in range(1, args.slices):
        time.sleep(args.interval)
        if adapter.poll_once(args.symbol) is None:
            print(f"  [tick {i}] no quote, skipping this slice's market update")

    session = ExecutionSession()
    result = session.run(adapter.source, orders, arrival_price)

    print("\n--- Execution Result (Phase 2: real market) ---")
    print(f"Requested quantity:        {result.requested_quantity}")
    print(f"Filled quantity:           {result.filled_quantity}")
    print(f"Fill rate:                 {result.fill_rate:.2%}")
    print(f"Arrival price:             {result.arrival_price:.4f}")
    print(f"Average execution price:   {result.average_execution_price:.4f}")
    print(f"Market VWAP:               {result.market_vwap:.4f}")
    print(f"Slippage:                  {result.slippage:.4%}")
    print(f"Implementation shortfall:  {result.implementation_shortfall:.2f}")
    print(f"VWAP deviation:            {result.vwap_deviation:.4%}")
    print(f"Fills captured:            {len(result.fills)}")
    for fill in result.fills:
        print(f"  t={fill.timestamp_ms} price={fill.trade.price:.4f} qty={fill.trade.qty} "
              f"bid={fill.bid:.4f} ask={fill.ask:.4f} mkt_vol={fill.market_volume}")

    return 0


if __name__ == "__main__":
    sys.exit(main())