# QuantExec Benchmark Suite

Reproducible, evidence-based benchmarks for QuantExec. Every number produced
here comes from **actually running the real C++ execution engine, its test
suites, or a real historical-data experiment** — nothing is hardcoded,
estimated, or hand-entered (except values explicitly tagged `ASSUMED`
configuration or `ESTIMATED` model output).

The suite does **not** change any execution semantics, add ML/prediction, or
replace real data with synthetic data for headline metrics. C++ stays the
execution core; this is pure measurement + orchestration in Python.

## What it measures

| Benchmark | Script | Output JSON | What it produces |
|---|---|---|---|
| Engine throughput | `engine_throughput.py` | `results/engine_throughput.json` | events/sec + µs/event + peak RSS at 10k/100k/1M/10M synthetic events, plus the real ~171k-quote AAPL dataset, via the real `benchmark_v2` binary |
| Strategy study | `strategy_study.py` | `results/strategy_experiments.json` | TWAP/VWAP/POV/Adaptive under identical real conditions; all execution-quality metrics + descriptive aggregation (no winner declared) |
| Determinism | `determinism.py` | `results/determinism.json` | repeated identical runs per strategy; identical/mismatch counts |
| Order-book correctness | `orderbook_correctness.py` | `results/orderbook_correctness.json` | pass/fail + throughput for the real GoogleTest matching/book/stress scenarios |
| Test inventory | `test_inventory.py` | `results/test_inventory.json` | total/passed/failed/skipped across C++, backend, frontend |
| No-lookahead | `no_lookahead.py` | `results/no_lookahead.json` | C++ replay tests + real-data truncation-invariance demonstration |
| Dataset inventory | `dataset_inventory.py` | `results/dataset_inventory.json` | real datasets with provenance + `CsvMarketSource` validation |
| Reports | `generate_report.py` | `BENCHMARK_REPORT.md`, `RESUME_METRICS.md` | human-readable aggregation of all of the above |

## Prerequisites

- **C++17/20 compiler**, **CMake ≥ 3.15**, **Python ≥ 3.10** with **pybind11**.
- **Node.js** (only for the frontend portion of the test inventory).
- No paid data. No credentials. Never commit `.env` or API keys.

### 1. Build the engine + Python module + tests + benchmark

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
      -DPython3_EXECUTABLE="$(which python3)" \
      -Dpybind11_DIR="$(python3 -c 'import pybind11; print(pybind11.get_cmake_dir())')"
cmake --build build --config Release -j"$(nproc)"
```

This produces `build/executor*.so`, `build/benchmark_v2`, and the 10
`build/test_*` binaries. On Windows the module/binaries land under
`build/Release` (the harness auto-detects either location; override with
`QUANTEXEC_BUILD_DIR`).

### 2. Install the Python + backend dependencies

```bash
python3 -m pip install pybind11
python3 -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt
```

(`fastapi` + `pydantic` are required for the backend portion of the test
inventory. The offline `python/test_alpaca_*` tests additionally need
`requests` / `alpaca-py`; they are optional and excluded from the CI-covered
total.)

### 3. (Optional, for the frontend test count) install frontend deps

```bash
cd frontend && npm install && cd ..
```

## Run everything

```bash
PYTHONPATH=build python3 benchmarks/run_all.py
# fast smoke run (skips 1M/10M throughput, fewer determinism reps):
PYTHONPATH=build python3 benchmarks/run_all.py --quick
```

Or run any single benchmark, e.g.:

```bash
PYTHONPATH=build python3 benchmarks/engine_throughput.py
PYTHONPATH=build python3 benchmarks/strategy_study.py
PYTHONPATH=build python3 benchmarks/determinism.py
```

### Single command for the full automated test suite

```bash
ctest --test-dir build --output-on-failure && \
PYTHONPATH=build:backend python -m pytest backend/tests -q && \
(cd frontend && npm test)
```

## Output locations

- Machine-readable: `benchmarks/results/*.json` (each carries a `_meta` block
  with the git commit, environment, reproduce command, and an honesty note).
- Human-readable: `benchmarks/BENCHMARK_REPORT.md` and
  `benchmarks/RESUME_METRICS.md`.

## Data honesty

- **OBSERVED** — values read directly from historical market data.
- **CALCULATED** — values mathematically derived from observed data
  (slippage, implementation shortfall, VWAP, fill/participation rate, drift,
  transaction costs).
- **ASSUMED** — user/config parameters (side, quantity, strategy params,
  latency, commission/exchange/fixed fees).
- **ESTIMATED** — model output (the simplified square-root market-impact
  estimate). Never presented as observed.

The bundled real data is **L1 quote-only** Alpaca IEX data for a **single
AAPL trading hour** (2024-01-03, 09:30–10:30 ET). It is deliberately small
and is **not** a basis for any general claim about strategy performance on
real markets. The suite is built so additional real sessions/securities can
be added (via `scripts/build_dataset_manifest.py` / `python/alpaca_ingest.py`)
and benchmarked with **no code changes** — just drop engine-schema CSVs in
and re-run.
