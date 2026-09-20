# Known Limitations

This document exists so every limitation lives in one place instead of
being scattered across code comments someone has to go find. Nothing
here is a secret or a surprise — each item is also documented closer to
the relevant code, and this file just consolidates them for anyone doing
a release/adoption review.

## 1. Data

- **One real historical dataset is bundled (Phase 2), alongside the
  original synthetic fixtures (kept, unmodified, for tests).**
  `datasets/historical/AAPL_2024-01-03_0930-1030ET.csv` is real AAPL
  quote data from Alpaca's IEX feed. It has real, disclosed gaps:
  - **Quote-only, no trades.** The environment that built this dataset had
    no `ALPACA_API_KEY`/`ALPACA_SECRET_KEY` and no network path to
    Alpaca's API, so `historical-execution/download_trades.py` could not
    be run. `last` is the quote midpoint, not a real trade print, and
    `volume` is 0 for every row. A direct consequence: the **POV strategy
    cannot produce any fills against this dataset** (it sizes child
    orders from realized volume, which is always 0 here) — see
    `historical-execution/PHASE2_STATUS.md` for the actual experiment
    result showing this.
  - **~15.5% of raw quotes were dropped as outliers** (anomalous
    ask=$199.00 / bid<$100 prints, evidently bad ticks, not real NBBO) —
    see `historical-execution/normalize.py` and `inspect_outliers.py`.
  - **Resampled to one row per minute** (60 rows for the 60-minute
    session), not full tick resolution, so that the number of dataset
    rows matches the execution engine's one-child-order-per-market-event
    design at a sensible (per-minute) granularity for a TWAP/VWAP/POV
    comparison. This means intra-minute price/quote movement is not
    replayed.
  - **Single venue (IEX), not consolidated SIP.** Verified from the raw
    data's exchange fields, not assumed.
  - This does not generalize to "how TWAP/VWAP/POV perform on real
    markets" — it is one symbol, one hour, one day, one venue, with no
    real trade data. See `historical-execution/PHASE2_STATUS.md` for the
    full accounting and `dataset.md` §"Acquiring a real historical
    dataset" for how to add another one (e.g. with real trades, once
    credentials/network access are available).
- **The manifest tool (`scripts/build_dataset_manifest.py`) validates
  structure, not economic plausibility.** It will accept a file with
  correct types and ordering but implausible prices — it is not a
  market-sanity checker.
- **No multi-venue, multi-symbol, or cross-asset data model.** One
  symbol, one venue, per dataset and per experiment.

## 2. Market microstructure

- **Queue position is explicitly not modeled.** See
  `docs/EXECUTION_ASSUMPTIONS.md` §3 for why this is a deliberate choice,
  not a gap the project intends to silently approximate.
- **No hidden/iceberg liquidity modeling** — only displayed size/depth
  from the dataset is ever available to match against.
- **No venue fragmentation** — one book, one venue, per experiment. A
  real parent order routed across multiple venues is out of scope.
- **No full L3 order-book reconstruction.** Depth is limited to whatever
  levels the dataset's `bid_depth`/`ask_depth` columns provide (typically
  1–3 levels in the bundled fixtures).
- **Cancellation is not exercised in historical replay.** `cancel_order`
  exists and is unit-tested at the engine level, but the replay loop
  never carries a resting order across events for there to be anything
  to cancel — see `docs/EXECUTION_ASSUMPTIONS.md` §4.

## 3. Execution realism

- **Latency is a fixed, configurable delay, not a network/exchange
  simulation.** See `docs/EXECUTION_ASSUMPTIONS.md` §5.
- **The market-impact estimate (`estimate_market_impact`) is a
  simplified, non-fitted, educational model.** It is off by default in
  the backend (`ImpactConfig.enabled = False`) for exactly this reason.
- **Trade side is not observable from the CSV schema** — the
  event-pipeline's synthetic `Trade` events record `side=Buy` by
  convention, not from any real signal. See `include/replay.h`.

## 4. Strategy comparison scope

- **Only TWAP, VWAP, POV, and an immediate-execution baseline are
  implemented.** No implementation-shortfall-optimizing, adaptive, or
  ML-driven strategies exist yet.
- **`python/compare_strategies.py`'s sweep is only as broad as the
  datasets you point it at.** Out of the box it covers the synthetic
  fixture plus the 6 stress datasets — meaningful for correctness and
  edge-case coverage, not for a claim like "VWAP beats TWAP on real
  markets," which would require real historical data across many real
  sessions.

## 5. Backend / API

- **Experiment execution is synchronous.** A `POST /experiments` call
  runs the engine inline and blocks until it's done; there is no real
  job queue, so the `queued` status is momentary and the `cancelled`
  status can only ever apply to a row orphaned by a server crash, not to
  a genuinely in-flight run. See the docstring on `DELETE
  /experiments/{id}` in `backend/main.py`.
- **Duplicate-submission detection is content-based (config + dataset
  checksum), not request-based.** Two different HTTP requests with
  identical bodies against an identical dataset are treated as
  duplicates by design; this is not idempotency-key-based deduplication
  of the HTTP layer itself.
- **CORS is wide open (`allow_origins=["*"]`)** for local development
  convenience. Tighten this before deploying anywhere that isn't
  localhost.
- **No authentication/authorization anywhere in the API.** Anyone who
  can reach the port can create and read experiments.
- **No database migration framework.** Schema changes are additive,
  hand-written `ALTER TABLE ... ADD COLUMN` checks in `backend/db.py`
  (`_migrate_schema`) — adequate for the two nullable columns added so
  far, not a general-purpose migration system.

## 6. Testing

- **CI runs on GitHub Actions** (`.github/workflows/ci.yml`): it builds the
  C++ engine, runs the GoogleTest suites via ctest, runs the Python backend
  tests against the freshly built extension, builds the React dashboard, and
  runs the performance-regression check. `BASELINE.md` remains the frozen,
  hand-run reproducibility record.
- **Performance regression thresholds are wired into CI.**
  `scripts/check_perf_regression.py` compares `benchmark_v2 --json` output to
  a committed baseline (`docs/benchmarks/thresholds.json`) with a generous
  tolerance, so only large (algorithmic) regressions fail a build. The
  baseline's absolute numbers are machine-specific (see
  `docs/BENCHMARKING.md` §7); the tolerance band is what makes the check
  portable across CI hardware.
- **Frontend test coverage is a smoke/interaction layer, not exhaustive.**
  Vitest + Testing Library cover the primary dashboard workflow (the
  New-Experiment form's payload shaping and API interaction) and the API
  fetch wrapper (`frontend/src/**/*.test.{js,jsx}`, run in CI). The other
  views (dashboard list, detail, comparison) are still only exercised by
  `npm run build` succeeding, not by their own interaction tests.

## 7. Benchmarking

- **All recorded benchmark numbers are from one shared/virtualized,
  single-vCPU sandbox machine** (see `docs/BENCHMARKING.md` §1) — they
  are a methodology demonstration, not a performance claim about any
  other machine, and definitely not about a real historical-data-scale
  workload.
- **Peak RSS is measured once for the whole process, not per stage** —
  see `docs/BENCHMARKING.md` §6 for exactly what this does and doesn't
  tell you.

## 8. What is NOT a limitation (to avoid confusion)

For clarity, since some of these are commonly assumed to be missing in
prototypes like this but are actually implemented and tested here:

- Partial fills **are** supported and are the normal case, not an edge
  case (`docs/EXECUTION_ASSUMPTIONS.md` §2).
- Buy/sell sign conventions for slippage/shortfall **are** correct for
  both sides and are unit-tested (`tests/test_stress.cpp`).
- The engine **is** deterministic — the same dataset and config always
  produce byte-identical output (`BASELINE.md` §3.4).
- Dataset validation **does** happen, both in the C++ loader
  (`CsvMarketSource`) and independently in the manifest tool
  (`scripts/build_dataset_manifest.py`).
