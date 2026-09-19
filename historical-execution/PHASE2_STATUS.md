# Phase 2 status: real historical market data + replay

This document is the honest accounting the Phase 2 brief asked for. It
describes exactly what was acquired, what was not, what was done to it,
and what the one real experiment actually showed — including the parts
that didn't work as originally expected.

## 1. What was inspected before anything was built (Step 1)

- `dataset.md`, `include/market_data.h`, `include/replay.h`,
  `src/market_data.cpp`: the exact CSV schema the C++ replay engine reads
  (`timestamp_ms,last,bid,ask,bid_size,ask_size,volume`, optional
  `bar_volume`/`bid_depth`/`ask_depth`), and its validation rules.
- `scripts/build_dataset_manifest.py`: the existing provenance/validation
  gate — reused as-is, not modified.
- `python/run_experiment.py`, `python/compare_strategies.py`: the existing
  orchestration layer and its "derive limit/arrival price from the
  dataset's first row" convention — reused, not reinvented.
- `src/execution.cpp` (`ExecutionSession::run`, `run_pov`): confirmed that
  **exactly one child order is submitted per replayed market-data row**,
  and that `POVAlgorithm::next_order_qty` sizes its order from that row's
  *realized traded volume* — both facts turned out to matter a lot (see
  §4 and §5).
- The repo already had a partial Phase 2 start: a real Alpaca quotes CSV
  had already been downloaded to
  `historical-execution/data/raw/alpaca/AAPL_2024-01-03_1430-1530_quotes.csv`
  (325,196 rows) via `download_quotes.py`, plus some inspection scripts
  that had already found data-quality problems in it. This work built on
  that rather than re-downloading.

No architecture was redesigned. `CsvMarketSource`, `ReplayController`,
`ExecutionSession`, and the TWAP/VWAP/POV algorithms are all untouched.

## 2. What was actually acquired — and what was not

**Acquired (real):** 325,196 historical NBBO-style quotes for AAPL,
2024-01-03 14:30:00.991–15:29:59.834 UTC (=09:30–10:30 America/New_York),
from Alpaca's IEX feed, via `alpaca-py`'s `StockHistoricalDataClient
.get_stock_quotes`. This was downloaded in a prior session that had real
Alpaca credentials; it is preserved immutably at
`data/raw/alpaca/AAPL_2024-01-03_1430-1530_quotes.csv` with a companion
`.metadata.json` recording feed, symbol, window, and known gaps
(no exact retrieval timestamp, no request ID — see that file for why).

**Not acquired: trades.** This Phase 2 pass was run in an environment with:
- no `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` in the environment, and
- no network egress path to Alpaca's API host at all.

`historical-execution/download_trades.py` was written (mirroring
`download_quotes.py`) and is ready to run wherever both of those exist,
but **it was not executed**, and no trade data exists anywhere in this
repository. This is the single biggest limitation of this Phase 2 pass —
see §5 for its concrete effect on the POV strategy.

Credentials were never hard-coded or printed anywhere in this work, and no
`.env` file was created or committed.

## 3. Normalization (`historical-execution/normalize.py`)

Every transformation is commented in the script itself; summary:

1. Drop quotes with non-positive or crossed bid/ask (126 of 325,196).
2. Drop ~15.5% (50,411 rows) as outliers more than 2% from the session's
   median bid/ask. These were not a judgment call invented for this
   report — `inspect_outliers.py` (already in the repo before this pass)
   had already flagged a cluster of quotes with `ask_price == 199.00`
   exactly and `bid_price` as low as `99.76`, both far outside AAPL's
   actual ~$183–186 range that session. These are almost certainly
   away/bad prints, not real NBBO.
3. Resample to **one row per minute** (60 rows for the 60-minute session),
   keeping the last valid quote observed in each minute. An earlier
   attempt at 1-second resolution (3,518 rows) is exactly why this
   document exists in this form — see §4.
4. `last` = quote midpoint (no trade prints exist to provide a real last
   price). `volume` = 0 (no trade prints exist to provide a real
   cumulative volume). Both are disclosed gaps, not silent
   approximations.
5. `bid_size`/`ask_size` converted from **round lots to shares** (×100).
   Alpaca's own changelog confirms quote sizes for data from this period
   (pre-November 2025) are reported in round lots, not shares. Skipping
   this conversion was an actual bug caught during this pass (see §4) —
   it made a 5,000-share order look 100x less fillable than it really was.
6. No `bid_depth`/`ask_depth` columns are emitted — this is real
   top-of-book only, nothing deeper is simulated in the CSV.

Output: `datasets/historical/AAPL_2024-01-03_0930-1030ET.csv` (60 rows),
manifested at
`datasets/historical/AAPL_2024-01-03_0930-1030ET.manifest.json` with
`"data_type": "historical"` and full provenance (the manifest tool
refuses anything less).

**Honest one-line description of this dataset** (per the brief's own
example format): *Historical quote replay (real IEX top-of-book quotes,
resampled to one-minute bars) with no trade data and no simulated depth —
not OHLC bars, not L2/L3 depth, not consolidated SIP.*

## 4. A real bug this process caught: dataset granularity vs. engine design

The first version of this dataset was resampled to 1-second bars (3,518
rows). Running the Step 9 experiment against it produced almost no fills
(TWAP/VWAP filled 7 of 5,000 shares; POV filled 0). The cause was not a
liquidity problem — it was that `ExecutionSession::run()` submits exactly
one child order per replayed row, and a 5-slice TWAP therefore only ever
reaches the **first 5 rows** of the file, i.e. the first 5 *seconds* of a
60-*minute* order window. Combined with round-lot sizes not yet being
converted to shares (see §3.5), the available liquidity in those 5 seconds
was a handful of shares.

Neither of these was a defect in the C++ engine or in TWAP/VWAP/POV — the
engine's "one child order per row" design is documented and intentional
(see `configs/example_experiment.yaml`'s comment on `slices`). The fix was
in the dataset: resample to one row per **minute** (60 rows, matching a
60-minute session) and set `num_slices=60`, so "one child order per market
event" means "one child order per minute," which is what a TWAP over an
hour should mean. This is recorded here because it is exactly the kind of
silent, misleading result the brief's "honest data description" and
"validate ordering" requirements exist to catch.

## 5. The real experiment (Step 9)

Run via `historical-execution/run_phase2_experiment.py` (calls the
existing pybind11 bindings directly — no engine changes):

- **Dataset**: `datasets/historical/AAPL_2024-01-03_0930-1030ET.csv`
  (sha256 `43c06892602ccdaa389d4537e5cb0b6875213d1095388217b343377329d421ec`)
- **Symbol / side / quantity**: AAPL, BUY, 5,000 shares
- **Window**: 2024-01-03, 09:30–10:30 America/New_York
- **Slices**: 60 (one per one-minute bar)
- **Limit price**: 188.4042 (= first-row ask × 1.02, same rule as
  `run_experiment.py`) · **Arrival price**: 184.7000 (= first-row mid)
- Identical dataset, order, prices, and cost config (0.5 bps commission,
  0.1 bps exchange fee) were used for all three strategies.

| Strategy | Filled | Fill rate | Avg exec price | Slippage | Impl. shortfall | Total cost |
|---|---|---|---|---|---|---|
| TWAP | 4,997 / 5,000 | 99.9% | 184.6442 | −0.0302% | −278.71 | 1.14 bps |
| VWAP | 4,997 / 5,000 | 99.9% | 184.6442 | −0.0302% | −278.71 | 1.14 bps |
| POV (20% participation) | 0 / 5,000 | 0.0% | — | — | — | — |

**TWAP and VWAP are identical** here because no real volume profile exists
for VWAP to differentiate on (see §2) — `VWAPAlgorithm` falls back to an
even split, which is the same schedule TWAP produces. This is disclosed,
not hidden: a real VWAP-vs-TWAP comparison needs real intraday volume,
which needs the trades data this pass could not fetch.

**POV filled zero shares — and this is correct, not a bug.** `POVAlgorithm
::next_order_qty` sizes every child order as `participation_rate ×
event_volume`. `event_volume` is 0 for every row of this dataset (no trade
data — see §2/§3.4), so POV correctly computes a 0-share order every
single event. This is the concrete, working proof of exactly the
limitation the brief asked to be surfaced honestly: **a quote-only
dataset cannot support a volume-participation strategy**, and pretending
otherwise (e.g. by inventing a volume figure) would be fabrication.

The negative slippage (execution price slightly *better* than arrival mid)
and market_vwap of 0.0000 (no real trade prints to compute a real market
VWAP from) are both direct, correctly-computed consequences of the same
gap and are not claims about real AAPL execution quality that day.

Raw output: `historical-execution/phase2_experiment_results.json`.

## 6. Files this phase added or changed

**Added:**
- `historical-execution/normalize.py`
- `historical-execution/download_trades.py` (written, not executed — §2)
- `historical-execution/run_phase2_experiment.py`
- `historical-execution/requirements.txt`
- `historical-execution/data/raw/alpaca/AAPL_2024-01-03_1430-1530_quotes.metadata.json`
- `historical-execution/data/normalized/AAPL_2024-01-03_0930-1030ET.csv`
- `datasets/historical/AAPL_2024-01-03_0930-1030ET.csv`
- `datasets/historical/AAPL_2024-01-03_0930-1030ET.manifest.json`
- `historical-execution/phase2_experiment_results.json`
- this file

**Changed (documentation only, honesty updates — no engine/algorithm code
touched):**
- `dataset.md` — Data Provenance section now reflects that one real
  historical dataset exists, and describes what it actually is.
- `LIMITATIONS.md` — §1 (Data) updated with this dataset's specific,
  disclosed gaps.

**Not changed:** every C++ source/header file, every existing Python
strategy/algorithm module, every synthetic dataset
(`datasets/sample_synthetic.csv`, `datasets/stress/*`), every existing
test (`tests/*`, `backend/tests/*` — all still pass, see §7).

## 7. Build / test verification

`cmake` + `pybind11` were installed (`pip install cmake pybind11`) and the
existing `CMakeLists.txt` was built unmodified:

```
cmake --build build --config Release
ctest --output-on-failure   # 10/10 test suites passed, 100%
```

No test was changed, added, or skipped to make this pass. This confirms
Phase 1's synthetic-data correctness is untouched by this Phase 2 work.

## 8. Limitations (consolidated)

- No trade data anywhere in this repo (§2, §5) — no `ALPACA_API_KEY`/
  `ALPACA_SECRET_KEY`, no network path to Alpaca's API in this
  environment. `download_trades.py` exists but has never been run.
- POV cannot produce fills against this dataset for exactly that reason
  (§5) — this is a correct, disclosed behavior of a volume-driven
  strategy given quote-only input, not an engine bug.
- ~15.5% of raw quotes were excluded as apparent bad prints (§3.2); this
  is a documented judgment call based on evidence in the data, not a
  guaranteed-correct market-data-quality determination.
- One-minute resampling (§3.3, §4) means intra-minute price movement is
  not replayed; this dataset cannot support sub-minute-latency analysis.
- Single venue (IEX), single symbol, single hour, single day — see
  `LIMITATIONS.md` for the standing "no multi-venue/multi-symbol" limit,
  which this dataset does not change.
- Exact retrieval timestamp and Alpaca request ID for the raw quotes file
  were not captured (recorded honestly in its `.metadata.json` rather than
  guessed).
