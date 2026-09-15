"""
Offline tests for Phase 3 historical ingestion. No network calls - uses
fixture quotes/bars shaped like Alpaca's documented schema, then round-trips
the result through the REAL C++ CsvMarketSource (via pybind11) to make sure
the CSV this module writes is actually valid input to Phase 1's replay
engine, not just internally self-consistent.

Run with: python3 test_alpaca_historical.py
"""

import os
import sys

from python.alpaca_historical import merge_into_rows, write_historical_csv
from executor import CsvMarketSource, ExecutionSession, OrderSide, TWAPAlgorithm, VWAPAlgorithm


# Three quotes spanning two 1-minute bars.
FIXTURE_QUOTES = [
    {"t": "2024-06-03T13:30:05.000000000Z", "ax": "V", "ap": 100.50, "as": 5,
     "bx": "V", "bp": 100.40, "bs": 5, "c": ["R"]},
    {"t": "2024-06-03T13:30:45.000000000Z", "ax": "V", "ap": 100.55, "as": 4,
     "bx": "V", "bp": 100.45, "bs": 6, "c": ["R"]},
    {"t": "2024-06-03T13:31:10.000000000Z", "ax": "V", "ap": 100.60, "as": 3,
     "bx": "V", "bp": 100.50, "bs": 5, "c": ["R"]},
]

FIXTURE_BARS = [
    {"t": "2024-06-03T13:30:00Z", "o": 100.40, "h": 100.55, "l": 100.38, "c": 100.48,
     "v": 5000, "n": 42, "vw": 100.47},
    {"t": "2024-06-03T13:31:00Z", "o": 100.48, "h": 100.62, "l": 100.46, "c": 100.58,
     "v": 3000, "n": 30, "vw": 100.55},
]


def test_merge_assigns_bar_volume_only_once_per_bar():
    rows = merge_into_rows(FIXTURE_QUOTES, FIXTURE_BARS)
    assert len(rows) == 3

    # First two quotes fall inside the 13:30 bar -> only the first gets that
    # bar's volume; the second must NOT double-count it.
    assert rows[0].bar_volume == 5000
    assert rows[1].bar_volume == 0
    # Third quote falls inside the 13:31 bar -> gets that bar's volume.
    assert rows[2].bar_volume == 3000

    # Cumulative volume accumulates correctly across the bar transition.
    assert rows[0].volume == 5000
    assert rows[1].volume == 5000
    assert rows[2].volume == 8000

    # `last` uses the covering bar's close price, not the quote mid.
    assert rows[0].last == 100.48
    assert rows[2].last == 100.58

    # Real bid/ask ticks pass through untouched.
    assert rows[0].bid == 100.40 and rows[0].ask == 100.50
    assert rows[0].bid_size == 5 * 100 and rows[0].ask_size == 5 * 100

    # Chronological order preserved.
    assert rows[0].timestamp_ms < rows[1].timestamp_ms < rows[2].timestamp_ms
    print("test_merge_assigns_bar_volume_only_once_per_bar passed")


def test_twap_vs_vwap_same_historical_conditions():
    """
    Phase 3 section 3.4: run TWAP and VWAP over the SAME market data and
    confirm both complete using the identical ExecutionSession/engine code
    path - the comparison is only meaningful if both strategies actually
    see the same ticks, which session.run()'s internal source.reset() should
    guarantee.
    """
    rows = merge_into_rows(FIXTURE_QUOTES, FIXTURE_BARS)
    path = "test_phase3_compare.csv"
    write_historical_csv(rows, path)
    try:
        twap = TWAPAlgorithm()
        twap_orders = twap.generate_orders(1, OrderSide.Buy, 90, 200.0, 3)

        vwap = VWAPAlgorithm()
        vwap.set_volume_profile([0.5, 0.3, 0.2])
        vwap_orders = vwap.generate_orders(2, OrderSide.Buy, 90, 200.0, 3)

        source = CsvMarketSource(path)
        session = ExecutionSession()
        twap_result = session.run(source, twap_orders, 100.45)

        source2 = CsvMarketSource(path)
        session2 = ExecutionSession()
        vwap_result = session2.run(source2, vwap_orders, 100.45)

        assert twap_result.requested_quantity == 90
        assert vwap_result.requested_quantity == 90
        assert twap_result.filled_quantity > 0
        assert vwap_result.filled_quantity > 0
        # Both should see the same market drift, since it's the same CSV.
        assert twap_result.market_price_drift == vwap_result.market_price_drift
    finally:
        if os.path.exists(path):
            os.remove(path)
    print("test_twap_vs_vwap_same_historical_conditions passed")


def test_reproducibility_across_two_independent_loads():
    rows = merge_into_rows(FIXTURE_QUOTES, FIXTURE_BARS)
    path = "test_phase3_repro.csv"
    write_historical_csv(rows, path)
    try:
        twap = TWAPAlgorithm()
        orders = twap.generate_orders(1, OrderSide.Buy, 90, 200.0, 3)

        source_a = CsvMarketSource(path)
        result_a = ExecutionSession().run(source_a, orders, 100.45)

        source_b = CsvMarketSource(path)
        result_b = ExecutionSession().run(source_b, orders, 100.45)

        assert result_a.filled_quantity == result_b.filled_quantity
        assert result_a.average_execution_price == result_b.average_execution_price
        assert result_a.market_price_drift == result_b.market_price_drift
        assert result_a.estimated_spread_cost == result_b.estimated_spread_cost
        assert len(result_a.fills) == len(result_b.fills)
    finally:
        if os.path.exists(path):
            os.remove(path)
    print("test_reproducibility_across_two_independent_loads passed")


if __name__ == "__main__":
    test_merge_assigns_bar_volume_only_once_per_bar()
    test_twap_vs_vwap_same_historical_conditions()
    test_reproducibility_across_two_independent_loads()
    print("\nAll Phase 3 historical ingestion tests passed (offline, no network calls)")
    sys.exit(0)