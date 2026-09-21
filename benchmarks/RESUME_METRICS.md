# QuantExec — Resume Metrics (measured, reproducible)

Only metrics that were **actually measured** by this benchmark suite are listed. Each is paired with the exact command that produced it so it can be independently reproduced from a clean checkout. These are raw numbers, not polished resume bullets. Performance figures are specific to the machine recorded in the JSON `_meta.environment`.

### Scale
- Largest real historical dataset processed: **171,293 real AAPL IEX quote events** (L1, quote-only).
- Real securities: **1** (AAPL); real sessions: **1** (AAPL 2024-01-03 09:30-10:30 America/New_York (== 14:30-15:30 UTC)).
  - reproduce: `PYTHONPATH=build python3 benchmarks/dataset_inventory.py`
- Synthetic scaling workload processed by the real engine: up to **10,000,000 market events** in a single run.
  - reproduce: `PYTHONPATH=build python3 benchmarks/engine_throughput.py`
- Strategy experiments executed through the real engine: **32**.
  - reproduce: `PYTHONPATH=build python3 benchmarks/strategy_study.py`

### Performance
- Peak full-execution throughput (real engine, replay + ExecutionSession): **957,801 events/second**.
- Real-data throughput (171,293 AAPL IEX events): **927,766 events/s** full execution, **1,007,592 events/s** replay, **1.078 µs/event**.
  - reproduce: `PYTHONPATH=build python3 benchmarks/engine_throughput.py`

### Execution Research
- **32** strategy comparisons across **4** algorithms (TWAP, VWAP, POV, Adaptive) under identical historical conditions.
- **32** implementation-shortfall observations recorded (median per strategy reported; no universal-winner claim).
  - reproduce: `PYTHONPATH=build python3 benchmarks/strategy_study.py`

### Reliability
- **4,400/4,400** repeated executions produced byte-identical results (fills, quantities, prices, analytics).
  - reproduce: `PYTHONPATH=build python3 benchmarks/determinism.py`
- **172/172** automated tests pass (C++ GoogleTest + Python backend + React frontend).
  - reproduce: `PYTHONPATH=build python3 benchmarks/test_inventory.py`
- **53/53** order-book / matching correctness scenarios pass (market/limit orders, partial + multi-level fills, price-time priority, cancellations, insufficient liquidity, stressed conditions).
  - reproduce: `PYTHONPATH=build python3 benchmarks/orderbook_correctness.py`
- No-lookahead / data-integrity validated: **True** (C++ replay tests + real-data truncation-invariance).
  - reproduce: `PYTHONPATH=build python3 benchmarks/no_lookahead.py`

---
_Every figure above is backed by a JSON file in `benchmarks/results/` containing the raw measurement, environment, and reproduce command. No value here is hand-entered._
