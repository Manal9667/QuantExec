"""
Alpaca real-market adapter (Phase 2).

    External Market Data (Alpaca JSON)
            |
    Market Data Adapter        <-- this file
            |
    Internal Market State      <-- executor.MarketSnapshot (C++ struct via pybind11)
            |
    Internal Order Book / Execution Engine   <-- untouched, same as Phase 1

Nothing downstream of `snapshot_to_market_state()` ever sees an Alpaca field
name. If Alpaca changes their schema, or we swap providers entirely, only
this file needs to change - the engine, TWAP/VWAP algorithms, and
ExecutionSession are completely unaware a REST provider exists.

Alpaca free tier ("Basic") notes, as of writing:
  * Market data comes from the IEX feed only (pass feed="iex" explicitly;
    Alpaca defaults free accounts to IEX but we don't rely on the default).
  * Auth is via the APCA-API-KEY-ID / APCA-API-SECRET-KEY headers.
  * Rate limit is generous for polling once every few seconds, but this
    adapter does not implement backoff/retry - add that before relying on
    it for anything unattended.
  * IEX-only means this is a *partial* view of the NBBO, not the full
    consolidated tape. That's a real limitation of the free tier, not a
    bug in this adapter - treat prices/sizes as directionally useful for
    a personal project, not as a production-grade quote.

Endpoint used: GET /v2/stocks/{symbol}/snapshot
It bundles latestTrade, latestQuote, minuteBar, dailyBar, prevDailyBar in one
call, which keeps this adapter to a single request per poll instead of three.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import requests

# Make the compiled `executor` module importable, same convention as the
# other python/ scripts in this repo.
_build_dir_release = os.path.join(os.path.dirname(__file__), '..', 'build', 'Release')
_build_dir = os.path.join(os.path.dirname(__file__), '..', 'build')
if os.path.exists(_build_dir_release):
    sys.path.insert(0, _build_dir_release)
elif os.path.exists(_build_dir):
    sys.path.insert(0, _build_dir)

from executor import MarketSnapshot, BookLevel, RealtimeMarketSource, normalize_market_state  # noqa: E402

ALPACA_DATA_BASE_URL = "https://data.alpaca.markets/v2"

# Quote sizes ("bs"/"as") from SIP-derived feeds are conventionally reported
# in round lots (1 = 100 shares). Trade size ("s") is already in shares.
# Verify this against Alpaca's current docs before trusting it for anything
# volume-sensitive - vendors have changed this convention before.
QUOTE_SIZE_LOT_MULTIPLIER = 100


class AlpacaAuthError(RuntimeError):
    """Raised when Alpaca credentials are missing or rejected."""


class AlpacaDataUnavailable(RuntimeError):
    """Raised when a snapshot has no usable quote (e.g. market closed)."""


@dataclass(frozen=True)
class AlpacaCredentials:
    key_id: str
    secret_key: str

    @staticmethod
    def from_env() -> "AlpacaCredentials":
        key_id = os.environ.get("ALPACA_API_KEY_ID")
        secret_key = os.environ.get("ALPACA_API_SECRET_KEY")
        if not key_id or not secret_key:
            raise AlpacaAuthError(
                "Set ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY environment "
                "variables (from your Alpaca paper-trading account) before "
                "using AlpacaMarketDataClient."
            )
        return AlpacaCredentials(key_id=key_id, secret_key=secret_key)


class AlpacaMarketDataClient:
    """Thin REST wrapper. Knows about Alpaca's HTTP API and nothing else."""

    def __init__(self, credentials: AlpacaCredentials, feed: str = "iex",
                 session: Optional[requests.Session] = None, timeout_s: float = 5.0):
        self._credentials = credentials
        self._feed = feed
        self._timeout_s = timeout_s
        self._session = session or requests.Session()
        self._session.headers.update({
            "APCA-API-KEY-ID": credentials.key_id,
            "APCA-API-SECRET-KEY": credentials.secret_key,
        })

    def get_snapshot(self, symbol: str) -> dict:
        """
        Fetch the combined snapshot (latest trade + quote + minute/day bars)
        for one symbol. Raises requests.HTTPError on non-2xx responses.
        """
        url = f"{ALPACA_DATA_BASE_URL}/stocks/{symbol}/snapshot"
        response = self._session.get(url, params={"feed": self._feed}, timeout=self._timeout_s)
        response.raise_for_status()
        return response.json()

    def get_historical_quotes(self, symbol: str, start_iso: str, end_iso: str, limit: int = 10000):
        """
        Yield every quote in [start_iso, end_iso) for `symbol`, transparently
        following next_page_token. Each yielded item has the same
        {t, ax, ap, as, bx, bp, bs, c} shape as a live quote - see
        quote_to_top_of_book() for the field mapping both share.
        """
        url = f"{ALPACA_DATA_BASE_URL}/stocks/{symbol}/quotes"
        page_token = None
        while True:
            params = {"start": start_iso, "end": end_iso, "limit": limit, "feed": self._feed}
            if page_token:
                params["page_token"] = page_token
            response = self._session.get(url, params=params, timeout=self._timeout_s)
            response.raise_for_status()
            payload = response.json()
            for quote in payload.get("quotes", []):
                yield quote
            page_token = payload.get("next_page_token")
            if not page_token:
                return

    def get_historical_bars(self, symbol: str, start_iso: str, end_iso: str,
                             timeframe: str = "1Min", limit: int = 10000):
        """
        Yield every bar in [start_iso, end_iso) for `symbol`, following
        next_page_token. Each bar has {t, o, h, l, c, v, n, vw}.
        """
        url = f"{ALPACA_DATA_BASE_URL}/stocks/{symbol}/bars"
        page_token = None
        while True:
            params = {"start": start_iso, "end": end_iso, "timeframe": timeframe,
                      "limit": limit, "feed": self._feed}
            if page_token:
                params["page_token"] = page_token
            response = self._session.get(url, params=params, timeout=self._timeout_s)
            response.raise_for_status()
            payload = response.json()
            for bar in payload.get("bars", []):
                yield bar
            page_token = payload.get("next_page_token")
            if not page_token:
                return


def _parse_rfc3339_to_ms(timestamp: str) -> int:
    """
    Alpaca timestamps look like '2022-01-04T21:58:24.500619778Z' - RFC-3339
    with nanosecond precision. Python's fromisoformat only handles up to
    microseconds, so truncate the fractional part before parsing.
    """
    if timestamp.endswith("Z"):
        timestamp = timestamp[:-1] + "+00:00"
    if "." in timestamp:
        head, rest = timestamp.split(".", 1)
        frac, _, offset = rest.partition("+")
        frac = (frac + "000000")[:6]  # pad/truncate to microseconds
        timestamp = f"{head}.{frac}+{offset}" if offset else f"{head}.{frac}"
    dt = datetime.fromisoformat(timestamp)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def quote_to_top_of_book(quote: dict, quote_size_lot_multiplier: int = QUOTE_SIZE_LOT_MULTIPLIER):
    """
    Map ONE Alpaca quote object (the {t, ax, ap, as, bx, bp, bs, c} shape
    used identically by the latest-quote, snapshot, and historical-quotes
    endpoints) to (bid, bid_size, ask, ask_size, timestamp_ms).

    This is the one place that knows Alpaca's quote field names. Both the
    Phase 2 real-time adapter (snapshot_to_market_state, below) and the
    Phase 3 historical ingestion (alpaca_historical.py) call this instead
    of each re-parsing bp/ap/bs/as independently - exactly the kind of
    duplication the project's architecture is trying to avoid, just one
    layer up from the C++ TWAP/VWAP classes.

    Raises AlpacaDataUnavailable if bid/ask are both zero (empty quote).
    """
    bid = float(quote.get("bp", 0.0) or 0.0)
    ask = float(quote.get("ap", 0.0) or 0.0)
    if bid <= 0.0 or ask <= 0.0:
        raise AlpacaDataUnavailable(f"Empty quote: bid={bid}, ask={ask}")
    bid_size = int(quote.get("bs", 0) or 0) * quote_size_lot_multiplier
    ask_size = int(quote.get("as", 0) or 0) * quote_size_lot_multiplier
    timestamp_ms = _parse_rfc3339_to_ms(quote["t"]) if quote.get("t") else 0
    return bid, bid_size, ask, ask_size, timestamp_ms


def snapshot_to_market_state(
    payload: dict,
    quote_size_lot_multiplier: int = QUOTE_SIZE_LOT_MULTIPLIER,
) -> MarketSnapshot:
    """
    Pure translation function: Alpaca snapshot JSON -> internal MarketState.

    No network calls happen here, which is what makes this unit-testable
    without hitting Alpaca (see python/test_alpaca_adapter.py).

    Raises AlpacaDataUnavailable if the quote is empty (bid/ask == 0), which
    Alpaca returns for illiquid symbols or when the market is closed and no
    recent quote exists - publishing a zero-price snapshot would corrupt
    mid-price and slippage calculations downstream.
    """
    quote = payload.get("latestQuote") or {}
    trade = payload.get("latestTrade") or {}
    minute_bar = payload.get("minuteBar") or {}
    daily_bar = payload.get("dailyBar") or {}

    bid, bid_size, ask, ask_size, timestamp_ms = quote_to_top_of_book(
        quote, quote_size_lot_multiplier
    )
    if not timestamp_ms and trade.get("t"):
        timestamp_ms = _parse_rfc3339_to_ms(trade["t"])

    state = MarketSnapshot()
    state.bid = bid
    state.ask = ask
    state.bid_volume = bid_size
    state.ask_volume = ask_size
    state.bids = [BookLevel()]
    state.bids[0].price = bid
    state.bids[0].qty = bid_size
    state.asks = [BookLevel()]
    state.asks[0].price = ask
    state.asks[0].qty = ask_size
    state.timestamp_ms = timestamp_ms

    if trade.get("p"):
        state.last_price = float(trade["p"])
    if daily_bar.get("v"):
        state.volume = int(daily_bar["v"])            # cumulative volume today
    if minute_bar.get("v"):
        state.bar_volume = int(minute_bar["v"])        # volume in this event/bar

    # Fill in mid_price and reconcile depth exactly the way every other
    # source (CSV, vector, realtime) does - reuse the engine's own
    # normalization instead of recomputing it here.
    normalize_market_state(state)
    return state


class AlpacaRealtimeAdapter:
    """
    Bridges AlpacaMarketDataClient -> RealtimeMarketSource.

    This is the object Phase 2 code actually holds onto: it looks exactly
    like "a market data source that happens to be backed by Alpaca" to
    everything downstream.
    """

    def __init__(self, client: AlpacaMarketDataClient):
        self._client = client
        self.source = RealtimeMarketSource()
        self.last_state: Optional[MarketSnapshot] = None

    def poll_once(self, symbol: str) -> Optional[MarketSnapshot]:
        """
        Fetch one snapshot from Alpaca, adapt it, and publish it into the
        RealtimeMarketSource. Returns the published MarketSnapshot, or None
        (without raising) if the market has no usable quote right now, so a
        polling loop can just skip a tick rather than crash outside market
        hours. The last successfully published state is also cached on
        `self.last_state` so callers don't need to re-fetch to read it.
        """
        payload = self._client.get_snapshot(symbol)
        try:
            state = snapshot_to_market_state(payload)
        except AlpacaDataUnavailable:
            return None
        if not self.source.publish(state):
            return None
        self.last_state = state
        return state