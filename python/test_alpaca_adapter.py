"""
Offline tests for the Phase 2 Alpaca adapter.

These do NOT hit the network. `snapshot_to_market_state` is a pure function,
so we test it against fixture payloads shaped exactly like Alpaca's
documented /v2/stocks/{symbol}/snapshot response
(https://docs.alpaca.markets/reference/stocksnapshotsingle). That's the
right boundary to test: everything upstream of it (the real HTTP client) is
untestable without live credentials and a market that's open; everything
downstream of it (RealtimeMarketSource, MatchingEngine, TWAP/VWAP,
ExecutionSession) is already covered by the C++ ctest suite and doesn't
care where a MarketSnapshot came from.

Run with:  python3 test_alpaca_adapter.py
"""

import sys

from python.alpaca_adapter import (
    snapshot_to_market_state,
    AlpacaDataUnavailable,
    AlpacaRealtimeAdapter,
    AlpacaMarketDataClient,
    AlpacaCredentials,
)
from executor import ExecutionSession, OrderSide, TWAPAlgorithm


# Shaped after Alpaca's documented snapshot example (AAPL), trimmed to the
# fields the adapter reads.
SAMPLE_SNAPSHOT = {
    "symbol": "AAPL",
    "latestTrade": {
        "t": "2022-01-04T21:49:04.055398242Z",
        "x": "V",
        "p": 477.38,
        "s": 500,
        "c": [" ", "T"],
        "i": 56592424269399,
        "z": "B",
    },
    "latestQuote": {
        "t": "2022-01-04T21:58:24.500619778Z",
        "ax": "V",
        "ap": 477.50,
        "as": 5,
        "bx": "V",
        "bp": 477.37,
        "bs": 5,
        "c": ["R"],
        "z": "B",
    },
    "minuteBar": {
        "t": "2022-01-04T21:49:00Z",
        "o": 477.38, "h": 477.53, "l": 477.38, "c": 477.42, "v": 4736,
    },
    "dailyBar": {
        "t": "2022-01-04T09:30:00Z",
        "o": 179.0, "h": 180.0, "l": 177.5, "c": 178.9, "v": 71161957,
    },
}

CLOSED_MARKET_SNAPSHOT = {
    "symbol": "SWAV",
    "latestQuote": {
        "t": "2021-11-11T21:00:00.000044814Z",
        "ax": "V", "ap": 0, "as": 0, "bx": "V", "bp": 0, "bs": 0, "c": ["R"], "z": "C",
    },
}


def test_snapshot_field_mapping():
    state = snapshot_to_market_state(SAMPLE_SNAPSHOT)
    assert state.bid == 477.37, state.bid
    assert state.ask == 477.50, state.ask
    assert state.bid_volume == 5 * 100  # lot multiplier
    assert state.ask_volume == 5 * 100
    assert state.last_price == 477.38
    assert state.volume == 71161957            # from dailyBar (cumulative)
    assert state.bar_volume == 4736             # from minuteBar (per-event)
    assert abs(state.mid_price - (477.37 + 477.50) / 2.0) < 1e-9
    # RFC-3339 nanosecond timestamp parses to millisecond epoch without crashing.
    assert state.timestamp_ms > 0
    assert len(state.bids) == 1 and state.bids[0].price == 477.37
    assert len(state.asks) == 1 and state.asks[0].price == 477.50
    print("test_snapshot_field_mapping passed")


def test_closed_market_raises():
    try:
        snapshot_to_market_state(CLOSED_MARKET_SNAPSHOT)
        assert False, "expected AlpacaDataUnavailable"
    except AlpacaDataUnavailable:
        pass
    print("test_closed_market_raises passed")


class _FakeAlpacaClient:
    """Stands in for AlpacaMarketDataClient so poll_once needs no network."""

    def __init__(self, snapshots):
        self._snapshots = list(snapshots)

    def get_snapshot(self, symbol):
        return self._snapshots.pop(0)


def test_adapter_poll_once_publishes_and_skips_bad_ticks():
    client = _FakeAlpacaClient([SAMPLE_SNAPSHOT, CLOSED_MARKET_SNAPSHOT])
    adapter = AlpacaRealtimeAdapter(client)

    state = adapter.poll_once("AAPL")
    assert state is not None
    assert adapter.last_state is state

    skipped = adapter.poll_once("SWAV")
    assert skipped is None
    print("test_adapter_poll_once_publishes_and_skips_bad_ticks passed")


def test_twap_executes_identically_over_synthetic_and_real_shaped_sources():
    """
    Phase 2's stated completion criterion: the same execution engine and the
    same TWAP/VWAP classes operate against synthetic AND real market
    conditions without duplicated logic. This test builds a RealtimeMarketSource
    the exact way the live Alpaca adapter does (via snapshot_to_market_state)
    and runs it through the identical ExecutionSession/TWAPAlgorithm code
    path Phase 1 uses with VectorMarketSource.
    """
    two_ticks = [
        SAMPLE_SNAPSHOT,
        {**SAMPLE_SNAPSHOT,
         "latestQuote": {**SAMPLE_SNAPSHOT["latestQuote"], "bp": 477.40, "ap": 477.55,
                         "t": "2022-01-04T21:58:25.000000000Z"}},
    ]
    client = _FakeAlpacaClient(two_ticks)
    adapter = AlpacaRealtimeAdapter(client)
    adapter.poll_once("AAPL")
    adapter.poll_once("AAPL")

    # TWAPAlgorithm always creates Limit orders (see algorithms.cpp) - to
    # execute "at market" you pass a marketable limit price, same convention
    # test_phase.cpp uses for the synthetic-source test. A buy limit far
    # above the quoted ask (~477.50 here) will cross every resting ask level
    # the session posts from the snapshot's book.
    twap = TWAPAlgorithm()
    orders = twap.generate_orders(1, OrderSide.Buy, 200, 500.0, 2)

    session = ExecutionSession()
    result = session.run(adapter.source, orders, 477.435)

    assert result.requested_quantity == 200
    assert result.filled_quantity > 0
    assert len(result.fills) > 0
    print("test_twap_executes_identically_over_synthetic_and_real_shaped_sources passed")


def test_credentials_from_env_missing(monkeypatch_env=None):
    import os
    saved = {k: os.environ.pop(k, None) for k in ("ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY")}
    try:
        try:
            AlpacaCredentials.from_env()
            assert False, "expected AlpacaAuthError"
        except Exception as exc:
            assert "ALPACA_API_KEY_ID" in str(exc)
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v
    print("test_credentials_from_env_missing passed")


if __name__ == "__main__":
    test_snapshot_field_mapping()
    test_closed_market_raises()
    test_adapter_poll_once_publishes_and_skips_bad_ticks()
    test_twap_executes_identically_over_synthetic_and_real_shaped_sources()
    test_credentials_from_env_missing()
    print("\nAll Phase 2 adapter tests passed (offline, no network calls)")
    sys.exit(0)