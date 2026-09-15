"""
Historical market-data ingestion (Phase 3, section 3.1).

    Alpaca historical quotes + bars
                |
        merge_into_rows()          <-- documents exactly what's real vs approximated
                |
        write_historical_csv()
                |
        the SAME CSV schema CsvMarketSource has consumed since Phase 1
                |
        Order Book / Execution Engine / TWAP / VWAP   <-- completely unchanged

Why Alpaca (not Databento) for Phase 3:
    Same provider as Phase 2 (one set of credentials, one client, reused
    field-mapping code via quote_to_top_of_book). Free tier covers historical
    quotes and bars going back further than the 15-minute real-time delay
    restriction. Databento has better multi-venue tick coverage and is
    arguably the "more correct" choice for serious backtesting, but it's a
    paid service and a second integration to maintain for a personal
    project - not worth it unless IEX-only coverage turns out to be a real
    problem for your analysis.

WHAT THIS DATASET ACTUALLY CONTAINS (per 3.1's "document exactly what
information is available" requirement):
    * Timestamp        - yes, nanosecond precision from Alpaca, truncated to ms.
    * Bid/ask           - yes, real NBBO ticks from the IEX feed (quotes endpoint).
    * Top-of-book size   - yes (bs/as from the same ticks).
    * Full L2 market depth - NO. Alpaca's free tier exposes top-of-book only;
      there is no multi-level order book in this dataset. Every row's
      book has exactly one bid level and one ask level.
    * Volume            - approximated. Alpaca's quotes endpoint carries no
      trade/volume data, so bar volume (from the bars endpoint, coarser
      granularity - default 1-minute) is joined onto quote ticks by nearest
      preceding bar. This means: (a) volume within a bar is attributed
      entirely to the first quote tick after that bar closes, not spread
      across the ticks that actually happened during it, and (b) precision
      is capped at 1 minute even though quotes arrive far more frequently.
    * Last traded price - approximated using the nearest preceding bar's
      close price, NOT actual trade-by-trade prints (that would require also
      ingesting the trades endpoint and merging three streams; skipped here
      to keep the pipeline maintainable for a personal project).

None of this is hidden from the execution engine - it just receives
MarketState rows with bid/ask populated accurately and volume/last_price
populated approximately, exactly like the "may not have full information"
warning in the phase plan anticipates.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from bisect import bisect_right
from dataclasses import dataclass
from typing import List, Optional

try:
    from .alpaca_adapter import (
        AlpacaCredentials,
        AlpacaMarketDataClient,
        AlpacaDataUnavailable,
        quote_to_top_of_book,
        _parse_rfc3339_to_ms,
    )
except ImportError:
    from alpaca_adapter import (
        AlpacaCredentials,
        AlpacaMarketDataClient,
        AlpacaDataUnavailable,
        quote_to_top_of_book,
        _parse_rfc3339_to_ms,
    )

CSV_COLUMNS = ["timestamp_ms", "last", "bid", "ask", "bid_size", "ask_size", "volume", "bar_volume"]


@dataclass
class HistoricalRow:
    timestamp_ms: int
    last: float
    bid: float
    ask: float
    bid_size: int
    ask_size: int
    volume: int       # cumulative volume as of this row
    bar_volume: int    # volume attributed to THIS row only (0 for most rows - see module docstring)


def merge_into_rows(quotes: List[dict], bars: List[dict]) -> List[HistoricalRow]:
    """
    Join a chronological quote-tick stream with a coarser bar stream.

    Bars are sorted by their open timestamp. For each quote, we find the
    latest bar whose open time is <= the quote's time. The FIRST quote that
    maps to a given bar gets that bar's volume as `bar_volume` (and its
    close as `last`); every subsequent quote mapped to the same bar gets
    bar_volume=0 (to avoid counting that bar's volume once per quote tick -
    see execution.cpp's `event_volume` logic, which sums bar_volume across
    ticks for the market VWAP calculation).

    Quotes with no usable bid/ask (both zero) are dropped, same as the
    real-time adapter does for empty quotes.
    """
    sorted_bars = sorted(bars, key=lambda b: b["t"])
    bar_times_ms = [_parse_rfc3339_to_ms(b["t"]) for b in sorted_bars]

    rows: List[HistoricalRow] = []
    cumulative_volume = 0
    last_bar_index_used: Optional[int] = None

    for quote in sorted(quotes, key=lambda q: q["t"]):
        try:
            bid, bid_size, ask, ask_size, ts_ms = quote_to_top_of_book(quote)
        except AlpacaDataUnavailable:
            continue

        # bisect_right - 1: index of the latest bar at or before this quote.
        bar_index = bisect_right(bar_times_ms, ts_ms) - 1
        last_price = rows[-1].last if rows else 0.0
        bar_volume_for_row = 0

        if bar_index >= 0:
            bar = sorted_bars[bar_index]
            last_price = float(bar["c"])
            if bar_index != last_bar_index_used:
                bar_volume_for_row = int(bar["v"])
                cumulative_volume += bar_volume_for_row
                last_bar_index_used = bar_index

        rows.append(HistoricalRow(
            timestamp_ms=ts_ms,
            last=last_price,
            bid=bid,
            ask=ask,
            bid_size=bid_size,
            ask_size=ask_size,
            volume=cumulative_volume,
            bar_volume=bar_volume_for_row,
        ))

    return rows


def write_historical_csv(rows: List[HistoricalRow], path: str) -> None:
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_COLUMNS)
        for row in rows:
            writer.writerow([row.timestamp_ms, row.last, row.bid, row.ask,
                             row.bid_size, row.ask_size, row.volume, row.bar_volume])


def fetch_and_write(symbol: str, start_iso: str, end_iso: str, out_path: str,
                     timeframe: str = "1Min") -> int:
    """Full pipeline: Alpaca -> merged rows -> CSV. Returns row count."""
    credentials = AlpacaCredentials.from_env()
    client = AlpacaMarketDataClient(credentials)
    quotes = list(client.get_historical_quotes(symbol, start_iso, end_iso))
    bars = list(client.get_historical_bars(symbol, start_iso, end_iso, timeframe=timeframe))
    rows = merge_into_rows(quotes, bars)
    write_historical_csv(rows, out_path)
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch Alpaca historical data into a replay CSV")
    parser.add_argument("symbol")
    parser.add_argument("start", help="RFC-3339 start, e.g. 2024-06-03T13:30:00Z")
    parser.add_argument("end", help="RFC-3339 end, e.g. 2024-06-03T14:00:00Z")
    parser.add_argument("--out", default=None, help="Output CSV path (default: <symbol>_historical.csv)")
    parser.add_argument("--timeframe", default="1Min")
    args = parser.parse_args()

    out_path = args.out or f"{args.symbol}_historical.csv"
    try:
        count = fetch_and_write(args.symbol, args.start, args.end, out_path, args.timeframe)
    except Exception as exc:  # noqa: BLE001 - CLI entry point, want a clean message
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote {count} rows to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())