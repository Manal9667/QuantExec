# QuantExec Benchmark Report

All numbers below were produced by actually running the real C++ execution engine, its test suites, or real historical-data experiments. Nothing is hardcoded or hand-entered. Values are tagged OBSERVED / CALCULATED / ASSUMED / ESTIMATED where relevant (see machine-readable JSON under `benchmarks/results/` for the full detail behind every table).

- Generated: 2026-09-21T13:12:54.965322+00:00
- Git commit: `6bbe82f45a53596f5889e8a31b8bd31a4de13380`
- Machine: Linux-6.1.182-227.379.amzn2023.x86_64-x86_64-with-glibc2.34 | 8 logical CPUs | Python 3.11.15

> Performance numbers are machine-specific (single shared cloud sandbox). Treat them as this machine's measurements, not a hardware-independent claim.

## Engine Performance

Real C++ engine throughput via `benchmark_v2` (3 warm-up + 10 measured iterations per stage). Headline stage = `full_execution` = CsvMarketSource replay + `ExecutionSession.run` (TWAP, 5 slices). `replay` = pure event replay.

| Workload | Events | full_execution (events/s) | µs/event | replay (events/s) | peak RSS |
|---|--:|--:|--:|--:|--:|
| synthetic 10,000 | 10,000 | 957,801 | 1.044 | 1,069,092 | 18 MB |
| synthetic 100,000 | 100,000 | 923,953 | 1.082 | 1,012,320 | 47 MB |
| synthetic 1,000,000 | 1,000,000 | 931,851 | 1.073 | 1,020,876 | 417 MB |
| synthetic 10,000,000 | 10,000,000 | 886,966 | 1.127 | 967,179 | 4,190 MB |
| **REAL** AAPL_2024-01-03_1430-1530_quotes.csv | 171,293 | **927,766** | 1.078 | 1,007,592 | 83 MB |

Peak measured full-execution throughput (synthetic): **957,801 events/s**.

## Historical Dataset Scale

- Distinct real symbols: **1** (AAPL)
- Distinct real sessions: **1** (AAPL 2024-01-03 09:30-10:30 America/New_York (== 14:30-15:30 UTC))
- Engine-ready real files: **2** (largest **171,293** quote events)
- Total engine-ready real quote events: **171,353**
- Trade data available: **False** (quote-only capture)

| Dataset | Rows | Symbol | Feed | Level | CsvMarketSource valid | Trades |
|---|--:|---|---|---|---|--:|
| datasets/historical/AAPL_2024-01-03_0930-1030ET.csv | 60 | AAPL | IEX | None | True | 0 |
| data/raw/alpaca/AAPL/AAPL_2024-01-03_1430-1530_quotes.csv | 171,293 | AAPL | iex | L1 | True | 0 |
| historical-execution/data/raw/alpaca/AAPL_2024-01-03_1430-1530_quotes.csv | 325,196 | AAPL | None | L1 | False | 0 |

> Real historical coverage is intentionally small (free Alpaca IEX, quote-only, one AAPL session). The benchmark infrastructure accepts additional datasets with no redesign - add engine-schema CSVs (+ manifests) via scripts/build_dataset_manifest.py / python/alpaca_ingest.py and re-run.

## Strategy Experiments

- Total experiments: **32** (strategies: TWAP, VWAP, POV, ADAPTIVE; identical dataset/side/quantity/cost assumptions per comparison).

Descriptive per-strategy statistics across all experiments (implementation shortfall and slippage are CALCULATED from OBSERVED data). **No strategy is declared superior** - this is a tiny, single-session sample.

| Strategy | Exps | Completion rate | Median IS | Median slippage | Median fill rate | Median cost (bps) |
|---|--:|--:|--:|--:|--:|--:|
| TWAP | 8 | 0.00 | 32.2500 | 0.000178 | 0.360 | 1.278 |
| VWAP | 8 | 0.00 | 32.2500 | 0.000178 | 0.350 | 1.278 |
| POV | 8 | 0.50 | 0.0000 | 0.000000 | 0.500 | 0.707 |
| ADAPTIVE | 8 | 1.00 | 127.2850 | 0.000515 | 1.000 | 1.278 |

> ⚠️ Only 2 distinct real historical session(s) are available (32 experiments total). This sample is FAR too small to support any general claim about relative strategy performance on real markets. Numbers are reported descriptively for this specific data only. Add more real sessions via the Alpaca ingestion pipeline (python/alpaca_ingest.py) to grow N.

## Determinism

- **4,400 / 4,400** repeated executions produced byte-identical results (mismatches: 0).
- Signature = SHA-256 of every ExecutionResult field + every fill.

| Dataset | Reps/strategy | Strategies | Identical |
|---|--:|---|---|
| AAPL_2024-01-03_0930-1030ET.csv | 1000 | TWAP, VWAP, POV, ADAPTIVE | 4000/4000 |
| AAPL_2024-01-03_1430-1530_quotes.csv | 100 | TWAP, VWAP, POV, ADAPTIVE | 400/400 |

## Order Book

- Scenarios: **53**, passed **53**, failed **0**, skipped 0 (across 5 real GoogleTest suites).
- Execution time: 0.0096 s (~5,520.8 scenarios/s, incl. process startup).

Required order-book behaviors, each backed by a named test:
- `market_orders`: ✓ (e.g. `enginetest.test_market_order_fills`)
- `limit_orders`: ✓ (e.g. `enginetest.test_limit_order_rests`)
- `partial_fills`: ✓ (e.g. `enginetest.test_partial_fill_across_levels`)
- `multi_level_fills`: ✓ (e.g. `booktest.test_fifo_at_level`)
- `price_time_priority`: ✓ (e.g. `booktest.test_fifo_at_level`)
- `cancellations`: ✓ (e.g. `booktest.test_cancel`)
- `insufficient_liquidity`: ✓ (e.g. `enginetest.test_market_insufficient_liquidity`)
- `multiple_orders`: ✓ (e.g. `algorithmstest.test_adaptive_generate_orders_throws`)
- `different_order_sizes`: ✓ (e.g. `algorithmstest.test_large_order`)

## Automated Tests

- CI-covered total: **172/172 passed** (0 failed, 0 skipped) across cpp, backend, frontend.

| Layer | Runner | Total | Passed | Failed | Skipped |
|---|---|--:|--:|--:|--:|
| cpp | GoogleTest/ctest | 106 | 106 | 0 | 0 |
| backend | pytest | 57 | 57 | 0 | 0 |
| frontend | vitest | 9 | 9 | 0 | 0 |

Single command for the full suite: `ctest --test-dir build --output-on-failure && PYTHONPATH=build:backend python -m pytest backend/tests -q && (cd frontend && npm test)`

Coverage tooling: not configured in this repository (not fabricated).

## Data Integrity

- No-lookahead validated: **True**.
  - C++ replay tests: 6 run, 0 failures (chronological ordering, monotonic timestamps, no-lookahead before/after seek, CSV-vs-event determinism cross-check).
  - Truncation-invariance on real data (AAPL_2024-01-03_1430-1530_quotes.csv): all_pass=True - fills before the truncation boundary are identical whether or not future events exist, proving no future data leaks into earlier decisions.

**OBSERVED / CALCULATED / ASSUMED / ESTIMATED separation** is enforced in every strategy experiment record (see `strategy_experiments.json`): OBSERVED = raw historical quotes; CALCULATED = metrics derived from them (slippage, IS, VWAP, fill/participation rate, drift, costs); ASSUMED = user/config parameters (side, quantity, fees, latency, strategy params); ESTIMATED = model output (square-root market-impact estimate). Real data is L1 quote-only Alpaca IEX (no full-depth/L2 claim, no trade prints) - see `dataset_inventory.json` and `LIMITATIONS.md`.

---
_Machine-readable results: `benchmarks/results/*.json`. Regenerate everything: `PYTHONPATH=build python3 benchmarks/run_all.py`._
