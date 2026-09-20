# QuantExec

A reproducible research/backtesting system that answers one question:

> **Given the same historical market conditions, how would different
> execution algorithms have executed the same parent order, and why did
> their results differ?**

This is a **research and backtesting system, not a production trading
platform or a live broker.** Nothing here connects to a real exchange or
executes real orders. See [`LIMITATIONS.md`](LIMITATIONS.md) for the full,
current list of what this system does not yet do.

## What's actually in this repository

Everything below is implemented, tested, and was re-verified (build +
full test suite + a determinism check) as this documentation was written
— see [`BASELINE.md`](BASELINE.md) for the exact commands and results.

| Layer | What it does | Where |
|---|---|---|
| Order book + matching engine | Price-time-priority matching, market/limit orders, partial fills | `include/book.h`, `include/engine.h`, `src/` |
| Market data / replay | CSV loading with strict validation, plus a formal `MarketEvent → MarketState` pipeline with explicit replay controls | `include/market_data.h`, `include/replay.h`, `src/replay.cpp` |
| Execution strategies | TWAP, VWAP, POV, plus an immediate-execution baseline | `include/algorithms.h` |
| Cost & slippage analytics | Commission/exchange/fixed fees, spread cost, slippage, implementation shortfall, optional impact estimate | `include/costs.h`, `include/impact.h` |
| Dataset provenance tooling | Validates and manifests any CSV before it's trusted; distinguishes synthetic from historical data | `scripts/build_dataset_manifest.py` |
| Fair multi-strategy comparison | Runs every strategy under identical data/config, reports distributions | `python/compare_strategies.py` |
| Python bindings | Full pybind11 surface over the C++ engine | `src/py_bindings.cpp` |
| Backend API | FastAPI + SQLite, with dataset checksums, structured errors, duplicate-submission handling, experiment states | `backend/` |
| Dashboard | React/Vite frontend over the backend API | `frontend/` |
| Benchmarking | Evidence-based, staged, repeatable performance protocol | `benchmarks/benchmark_v2.cpp`, `docs/BENCHMARKING.md` |

## Quick start

**Requires:** a C++17/20 compiler, CMake ≥ 3.15, Python ≥ 3.10, pybind11,
Node.js (for the frontend).

### Windows (recommended in this workspace)

```powershell
# 1. Create a local environment for backend tests
python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt -r backend\requirements-dev.txt

# 2. Build (Release)
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release

# 3. C++ tests (10 suites)
ctest --test-dir build -C Release --output-on-failure

# 4. Backend tests
$env:PYTHONPATH = "build\Release"
python -m unittest discover -s backend/tests -v

# 5. Frontend build
Push-Location frontend
npm install
npm run build
Pop-Location

# 6. Run one reproducible experiment
$env:PYTHONPATH = "build\Release"
python python/run_experiment.py configs/example_experiment.yaml

# 7. Run the backend + dashboard locally
uvicorn backend.main:app --reload --port 8000           # in one terminal
Push-Location frontend; npm run dev; Pop-Location        # in another
```

### Linux / macOS

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt
mkdir -p build && cd build
cmake -DCMAKE_BUILD_TYPE=Release \
      -Dpybind11_DIR="$(python3 -c 'import pybind11; print(pybind11.get_cmake_dir())')" ..
cmake --build . --config Release -j"$(nproc)"
cd ..
PYTHONPATH=build python3 -m unittest discover -s backend/tests -v
PYTHONPATH=build python3 python/run_experiment.py configs/example_experiment.yaml
```

Every command above is exactly what this repository's current tests and
scripts expect for a local run. The key portability detail is that on
Windows the compiled Python extension sits under `build/Release`, not
`build`.

## Data: synthetic vs. historical

**This repository ships only synthetic data.** `datasets/sample_synthetic.csv`
is deterministic and generated (`datasets/generate_sample.py`) — it is
useful for testing the engine's own correctness and determinism, but it
is not evidence about how any strategy would perform on a real market.

No real historical dataset is bundled, and that's a disclosed limitation,
not an oversight (see `LIMITATIONS.md`). Before treating any CSV as a
trustworthy input, run it through the provenance tool:

```bash
python3 scripts/build_dataset_manifest.py <your_file>.csv \
    --data-type historical --provider "..." --source-url "..." \
    --license "..." --timezone "..." --symbol ... --venue ... --resolution "..."
```

It refuses to label anything "historical" without provenance, and checks
every row for missing columns, malformed data, duplicate/non-monotonic
timestamps, invalid bid/ask, and non-finite or negative values. Full
schema and validation rules: [`dataset.md`](dataset.md).

## Documentation map

| Document | What's in it |
|---|---|
| [`BASELINE.md`](BASELINE.md) | Frozen, reproducible baseline: environment, exact commands, results, determinism proof |
| [`dataset.md`](dataset.md) | CSV schema, validation rules, provenance/manifest tooling, synthetic-vs-historical policy |
| [`docs/EXECUTION_ASSUMPTIONS.md`](docs/EXECUTION_ASSUMPTIONS.md) | Exactly what the matching/fill model does and doesn't simulate (partial fills, queue position, latency, cost decomposition, buy/sell sign conventions) |
| [`docs/BENCHMARKING.md`](docs/BENCHMARKING.md) | Benchmark methodology, recorded numbers, how to set your own regression thresholds |
| [`LIMITATIONS.md`](LIMITATIONS.md) | Everything this system does not do yet, stated plainly |

## Project structure

```
orderbook/
├── CMakeLists.txt
├── README.md                       # this file
├── BASELINE.md                     # reproducible baseline report
├── dataset.md                      # CSV schema + provenance/manifest tooling
├── LIMITATIONS.md                  # honest, current limitations list
├── docs/
│   ├── EXECUTION_ASSUMPTIONS.md
│   └── BENCHMARKING.md
├── include/                        # C++ public headers
│   ├── types.h  book.h  engine.h  market_data.h  replay.h
│   ├── execution.h  algorithms.h  costs.h  impact.h  market.h
├── src/                            # C++ implementation + pybind11 module
├── tests/                          # C++ test suites (10, see below)
├── benchmarks/
│   ├── benchmark.cpp               # original ad-hoc benchmarks
│   └── benchmark_v2.cpp            # Step 7 evidence-based protocol
├── scripts/
│   └── build_dataset_manifest.py   # dataset validation + provenance manifest
├── python/
│   ├── run_experiment.py           # single-experiment CLI
│   ├── compare_strategies.py       # fair multi-strategy comparison sweep
│   └── benchmark_python_boundary.py
├── configs/
│   └── example_experiment.yaml
├── datasets/
│   ├── sample_synthetic.csv        # synthetic fixture (NOT real market data)
│   ├── generate_sample.py
│   ├── historical/                 # empty - see dataset.md for how to add real data
│   └── stress/                     # 6 fixtures exercising execution-model edge cases
├── backend/                        # FastAPI + SQLite
│   ├── main.py  schemas.py  db.py  experiment_service.py  dataset_utils.py
│   └── tests/                      # 44 backend tests
└── frontend/                       # React/Vite dashboard
```

## C++ test suites (10, all passing as of this writing)

`test_book`, `test_engine`, `test_simulator`, `test_algorithms`,
`test_integrate`, `test_phase`, `test_costs`, `test_phase2`,
`test_replay` (Step 3 event/replay pipeline), `test_stress` (Step 4
execution realism under stressed market conditions).

## Configuration

### Backend runtime configuration (environment / `.env`)

Backend runtime knobs are read from environment variables (spec section 41)
rather than hardcoded — copy [`.env.example`](.env.example) to `.env` at the
repo root and edit, or export the variables directly. Every one is optional
and defaults to the value that was previously hardcoded, so an absent `.env`
changes nothing. Real shell variables always override the `.env` file.

| Variable | Default | Purpose |
|---|---|---|
| `QUANTEXEC_DB_PATH` | `experiments/experiments.db` | SQLite database location |
| `QUANTEXEC_API_HOST` / `QUANTEXEC_API_PORT` | `127.0.0.1` / `8000` | Host/port for `python backend/main.py` |
| `QUANTEXEC_CORS_ORIGINS` | `*` | Comma-separated CORS allow-list (tighten before deploying) |
| `QUANTEXEC_LOG_LEVEL` | `INFO` | Log level (`DEBUG`…`CRITICAL`) |
| `QUANTEXEC_COMMISSION_BPS` / `QUANTEXEC_EXCHANGE_FEE_BPS` / `QUANTEXEC_FIXED_FEE_PER_FILL` | `0.0` | Default transaction-cost assumptions applied when a request omits `costs` |

See [`backend/config.py`](backend/config.py) for the (dependency-free) loader.

### Experiment configuration

Experiments are configured via YAML for the CLI, or JSON for the API —
same underlying fields either way:

```yaml
symbol: SYN
dataset: datasets/sample_synthetic.csv
side: BUY
quantity: 1000
slices: 6
strategy: TWAP
arrival_price: null  # auto-derived from the dataset's first mid price
limit_price: null    # auto-derived from the dataset's first ask * 1.02
costs:
  commission_bps: 0.5
  exchange_fee_bps: 0.1
  fixed_fee_per_fill: 0.0
```

## What this system is not

- Not a live trading platform, broker, or exchange connector.
- Not validated against real historical market data yet (see `dataset.md`).
- Not a full L3 order-book reconstruction (queue position, cancellations
  across replayed events, and venue fragmentation are explicitly not
  modeled — see `docs/EXECUTION_ASSUMPTIONS.md`).
- Not a portfolio or multi-symbol system — one parent order, one symbol,
  per experiment.

See [`LIMITATIONS.md`](LIMITATIONS.md) for the complete, current list.
