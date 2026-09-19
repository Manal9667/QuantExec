#!/usr/bin/env python3
"""
Normalize raw Alpaca historical quote data into the schema documented in
dataset.md and consumed by CsvMarketSource / ReplayController:

    timestamp_ms, last, bid, ask, bid_size, ask_size, volume

This script does NOT invent any column the C++ replay engine wasn't already
designed to read (per dataset.md), and it does not silently upgrade the
data's resolution or claim depth/trade information that was never acquired.
Every transformation applied here is listed below and repeated in the
dataset's manifest `notes` field so a reviewer never has to reverse-engineer
what happened to the raw file.

Transformations applied (and why):

1. Row filtering (dataset.md "Validation Rules"):
   - drop quotes with bid_price <= 0 or ask_price <= 0 (one-sided/empty book)
   - drop crossed quotes (bid_price > ask_price)
   These are exactly the CsvMarketSource / build_dataset_manifest.py rules;
   rows violating them cannot be loaded by the engine at all.

1b. Outlier filtering (data-quality issue found by inspection, NOT a
    dataset.md rule): after the above filter, ~15% of remaining quotes are
    clustered at an ask price of exactly 199.00 (a suspiciously round
    number far from the day's ~$184-185 trading range) or a bid far below
    it (e.g. minimum bid_price observed: 99.76). These are almost certainly
    away/indicative or malformed quotes rather than genuine tradeable NBBO
    prints - see historical-execution/inspect_outliers.py, which was used
    to find them, for the raw evidence. We drop any quote whose bid or ask
    is more than 2% away from the session's median bid/ask. This threshold
    and the row count it removes are reported below and recorded in the
    dataset's manifest notes; nothing is corrected or imputed, only
    excluded.

2. Resampling to 1-minute bars (NOT 1-second - see note below):
   Raw IEX quotes arrive at sub-millisecond, bursty intervals (this capture
   has ~1.9 quotes/ms on average, up to 26 in a single millisecond). The
   engine's CSV schema requires STRICTLY increasing timestamp_ms with one
   row = one market snapshot, and - this is the part that matters here -
   ExecutionSession::run()/run_pov() (src/execution.cpp) submits exactly
   ONE child order per market-data row it replays (see the doc comment on
   `slices` in configs/example_experiment.yaml: "the strategy submits one
   child order per market event it observes, up to `slices` orders total").
   That design is correct and is NOT being changed here (see "do not
   redesign the architecture" in the Phase 2 brief) - but it means the
   dataset's row granularity IS the strategy's decision granularity. An
   initial pass of this script resampled to 1-second bars (3,518 rows for
   the hour) and a 5-slice TWAP against that dataset only ever reached the
   first 5 *seconds* of a 60-*minute* order window - a real bug in how this
   dataset was prepared, not in the engine. Resampling to one row per
   **minute** (60 rows for a 60-minute session) instead makes `slices=60`
   correspond to "one child order per minute," which is what a TWAP over a
   60-minute window should mean. We keep the LAST valid quote observed in
   each calendar minute as that minute's representative snapshot - every
   kept row is a genuine, unmodified quote that was actually printed by
   IEX at that moment, not an average or interpolation.

3. `last` (trade price) is NOT available in this dataset - no trade data was
   acquired (see LIMITATIONS in the metadata file this script writes).
   `last` is set to the quote midpoint, `(bid + ask) / 2`, which is exactly
   what `normalize_market_state()` in src/market_data.cpp would derive
   anyway per dataset.md rule 2 ("If last_price <= 0, set
   last_price = mid_price"). We compute it here explicitly so it is visible
   in the CSV rather than hidden inside a C++ fallback.

4. `volume` is set to 0 for every row. No trade prints were acquired, so
   there is no genuine cumulative-volume figure to report, and inventing
   one would violate the "do not fabricate historical depth [or other
   facts]" instruction. This is a real, documented gap - see LIMITATIONS.
   (Consequence: POVAlgorithm, which sizes its child orders off realized
   volume, sees event_volume == 0 for every row and therefore cannot size
   any order - see PHASE2_STATUS.md for how the POV run is reported given
   this.)

5. `bid_size`/`ask_size` are converted from ROUND LOTS to SHARES by
   multiplying by 100. Alpaca's CTA/UTP quote sizes for data from this
   period (pre-November 2025) are reported in round lots, not shares -
   confirmed via Alpaca's own changelog ("Alpaca will display the CTA/UTP
   (US stock) quote sizes in shares, instead of round lots, starting
   November 3, 2025" - https://docs.alpaca.markets/changelog/marketdata-bid-and-ask-size-display-change)
   and AAPL's round lot size for this price range is 100 shares under the
   standard (pre-tiered) convention in effect in January 2024. Without this
   conversion, raw bid_size/ask_size values of 1-3 look like 1-3 SHARES of
   displayed liquidity, which is not what was actually quoted (it was
   100-300 shares) and made a 5,000-share order look almost entirely
   unfillable against real top-of-book depth. This is a units correction
   backed by Alpaca's own documentation, not an invented liquidity boost.

6. No `bid_depth` / `ask_depth` columns are emitted. This dataset is
   top-of-book (L1) only; the engine's own book/matching logic (already
   implemented in Phase 1 - see src/book.cpp, src/simulator.cpp) is what
   supplies the multi-level liquidity model fills are matched against, not
   fabricated CSV columns. See dataset.md for how CsvMarketSource treats a
   file with no depth columns ("top-of-book only is available"). Per the
   Phase 2 brief's own honest-description example, this dataset is
   described as "historical quote/trade replay" (quote-only, in this
   run) - it is explicitly NOT described as L2/L3 depth anywhere in this
   project's docs, and no multi-level liquidity is simulated in the CSV
   itself.

Usage:
    python3 normalize.py \
        --input data/raw/alpaca/AAPL_2024-01-03_1430-1530_quotes.csv \
        --output data/normalized/AAPL_2024-01-03_0930-1030ET.csv
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def normalize(input_path: Path, output_path: Path) -> dict:
    df = pd.read_csv(input_path)

    raw_row_count = len(df)

    # --- Step 1: row filtering (dataset.md validation rules) -----------
    valid = df[
        (df["bid_price"] > 0)
        & (df["ask_price"] > 0)
        & (df["bid_price"] <= df["ask_price"])
    ].copy()
    dropped_invalid = raw_row_count - len(valid)

    # --- Step 1b: outlier filtering (see module docstring) --------------
    median_bid = valid["bid_price"].median()
    median_ask = valid["ask_price"].median()
    band = 0.02  # +/- 2% around the session median
    before_outlier_filter = len(valid)
    valid = valid[
        valid["bid_price"].between(median_bid * (1 - band), median_bid * (1 + band))
        & valid["ask_price"].between(median_ask * (1 - band), median_ask * (1 + band))
    ].copy()
    dropped_outliers = before_outlier_filter - len(valid)

    valid["timestamp"] = pd.to_datetime(valid["timestamp"], utc=True, format="mixed")

    # --- Step 2: resample to 1-minute bars, keep latest quote per minute -
    valid = valid.sort_values("timestamp")
    valid["minute_bucket"] = valid["timestamp"].dt.floor("min")
    resampled = valid.groupby("minute_bucket", as_index=False).last()
    dropped_by_resample = len(valid) - len(resampled)

    # --- Step 3/4/5/6: build normalized schema --------------------------
    out = pd.DataFrame()
    out["timestamp_ms"] = (resampled["minute_bucket"].astype("int64") // 1_000).astype("int64")
    out["bid"] = resampled["bid_price"].astype(float)
    out["ask"] = resampled["ask_price"].astype(float)
    out["last"] = (out["bid"] + out["ask"]) / 2.0
    ROUND_LOT = 100  # see step 5 in the module docstring
    out["bid_size"] = (resampled["bid_size"].round().astype("int64") * ROUND_LOT)
    out["ask_size"] = (resampled["ask_size"].round().astype("int64") * ROUND_LOT)
    out["volume"] = 0

    out = out.sort_values("timestamp_ms").reset_index(drop=True)

    # Final safety check: strictly increasing timestamps (1-second flooring
    # is already unique by construction here, but assert rather than assume).
    assert out["timestamp_ms"].is_monotonic_increasing, "timestamp_ms not monotonic after resampling"
    assert out["timestamp_ms"].is_unique, "duplicate timestamp_ms after resampling"
    assert (out["bid"] <= out["ask"]).all(), "crossed quote survived filtering"
    assert (out[["bid", "ask", "last"]] > 0).all().all(), "non-positive price survived filtering"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(output_path, index=False)

    return {
        "input": str(input_path),
        "output": str(output_path),
        "raw_row_count": raw_row_count,
        "dropped_invalid_quotes": int(dropped_invalid),
        "dropped_outlier_quotes": int(dropped_outliers),
        "median_bid": float(median_bid),
        "median_ask": float(median_ask),
        "dropped_by_1s_resampling": int(dropped_by_resample),
        "normalized_row_count": len(out),
        "start_timestamp_ms": int(out["timestamp_ms"].iloc[0]),
        "end_timestamp_ms": int(out["timestamp_ms"].iloc[-1]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    stats = normalize(args.input, args.output)
    for k, v in stats.items():
        print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
