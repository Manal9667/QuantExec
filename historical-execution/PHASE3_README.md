# Phase 3: Execution Experiments + Analytics

## Overview

Phase 3 transforms the project into a **reproducible execution research platform** for comparing trading strategies under identical historical conditions.

The key insight: **controlled comparison requires all variables to be identical except the one you're testing.**

This platform runs 18 controlled experiments comparing TWAP, VWAP, and POV strategies across different order sizes (500, 2500, 5000 shares) and sides (BUY, SELL), using real Alpaca market data.

## Quick Start

### Prerequisites
- C++ bindings built (from Phase 1/2): `../build/executor.cpython-*.so`
- Python 3.7+
- Historical market data: `datasets/historical/AAPL_2024-01-03_0930-1030ET.csv`

### Run All Experiments
```bash
cd historical-execution
PYTHONPATH=../build python3 run_phase3_experiments.py
```

Output:
- `phase3_results.csv` — 18 rows, one per experiment
- `phase3_results.json` — Full configuration and metrics
- `phase3_analysis.txt` — Human-readable summary

Typical runtime: ~10 seconds for all 18 experiments.

## Understanding the Experiment Matrix

### Configuration
```
Sides:      BUY, SELL                  (2 values)
Sizes:      500, 2500, 5000 shares     (3 values)  
Strategies: TWAP, VWAP, POV            (3 values)
Total:      2 × 3 × 3 = 18 experiments
```

### Why These Sizes?
- **500 shares (small):** ~3–4 minutes of average market liquidity
- **2500 shares (medium):** ~15–20 minutes of liquidity
- **5000 shares (large):** ~30+ minutes of liquidity (fills in ~60-minute window)

All three are realistic for institutional execution and show how strategy performance scales with order size.

### What's Identical Across All Experiments?
✓ Dataset file (same market data)
✓ Time window (2024-01-03, 09:30-10:30 ET)
✓ Price derivation (both strategies use same limit/arrival)
✓ Slices (60 = one per minute bar)
✓ Fees (0.5 bps commission + 0.1 bps exchange fee)
✓ Latency (zero)
✓ POV participation (20%)

**Only the strategy changes.** This ensures observed differences are due to strategy, not data or assumptions.

## Interpreting Results

### Key Metrics

Per experiment, the system reports:

| Metric | Meaning |
|---|---|
| `requested_quantity` | Original order size |
| `filled_quantity` | Shares actually executed |
| `unfilled_quantity` | Shares not filled |
| `fill_rate` | filled / requested (0–100%) |
| `average_execution_price` | VWAP of all fills |
| `arrival_price` | Market mid at first data row |
| `slippage_bps` | (avg_price - arrival) in basis points |
| `implementation_shortfall` | slippage + half spread cost |
| `total_cost_bps` | Commission + fees + half spread |
| `completion_time_ms` | Total execution duration |
| `participation_rate` | % of estimated daily volume |
| `market_vwap` | Volume-weighted mid from data (0 if no volume) |

### Example Interpretation

**BUY 500 shares, TWAP:**
```
filled_quantity: 500 (100% fill)
average_execution_price: 184.6466
arrival_price: 184.7000
slippage_bps: -2.89  (negative = better than arrival)
total_cost_bps: 1.14 (commission + exchange fee)
```

**Interpretation:** The TWAP algorithm filled the full order at prices ~2.9 bps better than the market mid (passive execution, didn't cross spread). Total transaction cost was 1.14 bps.

**SELL 5000 shares, VWAP:**
```
filled_quantity: 5000 (100% fill)
average_execution_price: 184.3074
arrival_price: 184.7000
slippage_bps: +21.26  (positive = worse than arrival)
total_cost_bps: 1.14
```

**Interpretation:** Selling passively (at the bid) means accepting prices ~21 bps worse than mid. This is normal for sell-side execution; the slippage reflects the bid-ask spread and is not a strategy failure.

## Using the Platform

### Run a Custom Experiment

Edit `run_phase3_experiments.py` to change configuration:

```python
# Example: Just TWAP and VWAP, skip POV
STRATEGIES = ["TWAP", "VWAP"]

# Example: Smaller sizes
SIZE_CONFIGS = {
    "small": 100,
    "medium": 500,
    "large": 1000,
}

# Example: Different fees
cost_cfg.commission_bps = 1.0  # 1 bps commission
cost_cfg.exchange_fee_bps = 0.5  # 0.5 bps exchange fee
```

Then run:
```bash
PYTHONPATH=../build python3 run_phase3_experiments.py
```

### Use a Different Dataset

Add your own historical dataset to `datasets/historical/`:

```python
# In run_phase3_experiments.py
DATASET = REPO_ROOT / "datasets" / "historical" / "YOUR_FILE.csv"
```

Dataset must have columns: `timestamp_ms,bid,ask,last,bid_size,ask_size,volume`

### Add a New Strategy

Modify `run_experiment()` to handle your algorithm:

```python
elif config.strategy == "CUSTOM":
    algo = MyCustomAlgorithm()
    orders = algo.generate_orders(1, cpp_side, config.quantity, limit_price, config.num_slices)
    cpp_result = session.run(source, orders, arrival_price)
```

Add to `STRATEGIES`:
```python
STRATEGIES = ["TWAP", "VWAP", "POV", "CUSTOM"]
```

## Results Format

### CSV Output: `phase3_results.csv`

One row per experiment. Columns:
```
side, quantity, size_category, strategy, requested_quantity, filled_quantity,
unfilled_quantity, fill_rate, average_execution_price, arrival_price,
slippage_bps, implementation_shortfall, total_cost_bps, commission_bps,
exchange_fees_bps, spread_cost_bps, completion_time_ms, participation_rate,
market_vwap
```

Easy to import into Excel or Python/Pandas:
```python
import pandas as pd
df = pd.read_csv("phase3_results.csv")
df[df["strategy"] == "TWAP"]  # All TWAP results
df[(df["side"] == "BUY") & (df["quantity"] == 5000)]  # Big buy orders
```

### JSON Output: `phase3_results.json`

Full structure:
```json
{
  "phase": 3,
  "dataset": "datasets/historical/AAPL_2024-01-03_0930-1030ET.csv",
  "dataset_sha256": "43c06892...",
  "experiment_window": "2024-01-03 09:30-10:30 ET",
  "matrix": {
    "sides": ["Buy", "Sell"],
    "size_categories": ["small", "medium", "large"],
    "sizes": {"small": 500, ...},
    "strategies": ["TWAP", "VWAP", "POV"]
  },
  "cost_assumptions": {
    "commission_bps": 0.5,
    "exchange_fee_bps": 0.1
  },
  "results": [
    {
      "config": {...},
      "metrics": {...}
    },
    ...
  ]
}
```

Load in Python:
```python
import json
with open("phase3_results.json") as f:
    data = json.load(f)
for result in data["results"]:
    print(f"{result['config']['strategy']}: {result['metrics']['fill_rate']}")
```

### Analysis Output: `phase3_analysis.txt`

Human-readable summary:
- Experiment configuration
- Fairness statement (what's identical, what's not)
- Results by category (side × size × strategy)
- Key observations (fill rates, slippage, costs)
- Interpretation caveats (what NOT to conclude)
- Data provenance (source, limitations, normalization)

## Important Caveats

### ⚠️ These Results Are Limited To:
- **One day** (2024-01-03)
- **One symbol** (AAPL)
- **One hour** (09:30–10:30 ET)
- **One market condition** (mid-morning, no major events that day)
- **One data granularity** (one-minute bars)
- **One data type** (quotes only, no trades)

### ⚠️ Do NOT Conclude:
- "VWAP is always better than TWAP" — They're identical here (need volume data to differentiate)
- "POV never works" — It does, but not on quote-only data (need trades for volume)
- "Buy orders always get negative slippage" — Only under passive execution; aggressive buying would flip this
- "AAPL execution is always this good" — One snapshot; market conditions vary

### ✓ What You CAN Conclude:
- "Under these specific conditions (this dataset, these sizes, these strategies), TWAP and VWAP produce identical results because no volume profile differentiates them"
- "POV cannot execute on quote-only data (correct behavior, not a bug)"
- "Larger orders have slightly higher market impact (slippage grows with size)"
- "This platform enables controlled strategy comparison"

## Extending This Work

### Phase 3.1: Multiple Symbols
Add MSFT, GOOGL, TSLA, etc. to `datasets/historical/`. Run the same experiment matrix for each symbol. Compare strategy effectiveness across liquidity profiles.

### Phase 3.2: Multiple Times/Days
Acquire data for different hours (open, midday, close) and different market conditions (trending, ranging, volatile). Build a matrix of time × symbol × size × strategy.

### Phase 3.3: Trade Data
Run `download_trades.py` to acquire real volume data. Then:
- VWAP can actually participate in volume (not just fall back to TWAP)
- POV can fill based on real market volume
- Market VWAP can be computed accurately

### Phase 3.4: Market Impact Models
Add realistic market impact (price moves against you as you execute). Compare impact across strategies and order sizes.

### Phase 3.5: Multi-Venue Routing
Instead of single-venue (IEX) data, use consolidated SIP. Compare single-venue vs smart routing.

## Files

### Core
- `run_phase3_experiments.py` — Main experiment runner (this file)
- `PHASE3_STATUS.md` — Detailed findings, methodology, caveats
- `PHASE3_README.md` — This file

### Outputs (Generated)
- `phase3_results.csv` — Machine-readable results (18 experiments)
- `phase3_results.json` — Full configuration and metrics
- `phase3_analysis.txt` — Human-readable summary

### Historical Data
- `datasets/historical/AAPL_2024-01-03_0930-1030ET.csv` — Real market data (60 bars)
- `datasets/historical/AAPL_2024-01-03_0930-1030ET.manifest.json` — Data provenance

### Supporting (From Phase 2)
- `normalize.py` — Resampling/cleaning logic
- `download_quotes.py` — How the raw data was acquired
- `download_trades.py` — (Unexecuted; requires API key)

## Reproducibility

### Data Integrity
```bash
# Verify dataset hasn't changed
sha256sum datasets/historical/AAPL_2024-01-03_0930-1030ET.csv
# Should output:
# 43c06892602ccdaa389d4537e5cb0b6875213d1095388217b343377329d421ec
```

### Rebuild from Source
```bash
# From repo root
cd build
cmake --build . --config Release
cd ../historical-execution
PYTHONPATH=../build python3 run_phase3_experiments.py
```

Same configuration always produces identical results (no randomness in simulation).

## Questions & Issues

### "Why are TWAP and VWAP identical?"
VWAP requires a volume profile (trades per minute). This dataset has no trades, only quotes. VWAP defaults to an even split, which is TWAP. To see real VWAP differentiation, acquire trade data (`download_trades.py`).

### "Why does POV fill 0 shares?"
Same reason: POV sizes orders as `participation_rate × volume`. With `volume=0` for every row (no trade data), every child order is 0 shares. This is correct behavior. See `PHASE3_STATUS.md` for details.

### "Why do SELL orders have worse prices?"
Selling passively means offering at the bid. The bid is below mid by half the spread. This is expected, not a strategy failure. Aggressive selling (crossing the spread) would show better prices but higher market impact.

### "Can I add more experiments?"
Yes. Modify `SIDES`, `SIZE_CONFIGS`, or `STRATEGIES` in `run_phase3_experiments.py`. The experiment matrix is generated automatically.

### "Can I use my own market data?"
Yes. Add a CSV to `datasets/historical/` with columns: `timestamp_ms,bid,ask,last,bid_size,ask_size,volume`. Update `DATASET` in the script and run.

### "How long do experiments take?"
~10 seconds for all 18. Each experiment re-loads the dataset and runs one strategy. Parallelization possible but not implemented (GIL contention would limit speedup).

## For Developers

### Architecture
1. `ExperimentConfig` — Dataclass specifying one experiment's parameters
2. `generate_experiment_matrix()` — Creates all 18 configs
3. `run_experiment()` — Executes a single config, returns `ExecutionResult`
4. `write_csv_results()`, `write_json_results()`, `write_analysis()` — Output formatters
5. `main()` — Orchestrates all experiments and output

### Adding a New Metric
1. Compute it in `run_experiment()` after the strategy runs
2. Add field to `ExecutionResult` NamedTuple
3. Add to CSV columns in `write_csv_results()`
4. Add to JSON metrics in `write_json_results()`

### Testing
```bash
# Check one experiment runs
PYTHONPATH=../build python3 -c "
from run_phase3_experiments import *
cfg = ExperimentConfig(DATASET, 'AAPL', 'BUY', 500, 'TWAP', 60, 0.2, 0.5, 0.1)
result = run_experiment(cfg)
print(result.filled_quantity, result.fill_rate)
"
```

## Summary

Phase 3 provides a **reproducible research platform** for execution analysis:
- ✓ Controlled experiments (one variable: strategy)
- ✓ Real market data (Alpaca AAPL 2024-01-03)
- ✓ Clean configuration system
- ✓ Comprehensive metrics (19 per experiment)
- ✓ Multiple output formats (CSV, JSON, text)
- ✓ Honest caveats and limitations

Use it as a foundation for:
- Comparing strategies under identical conditions
- Testing new algorithms against historical data
- Understanding strategy behavior across order sizes
- Building multi-symbol/multi-day analysis pipelines

See `PHASE3_STATUS.md` for detailed findings and `phase3_results.json` for full experimental results.
