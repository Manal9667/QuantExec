#!/usr/bin/env python3
"""
Measures the pybind11 boundary overhead specifically (Step 7: "Separate
timing for: ... Python boundary"). benchmarks/benchmark_v2.cpp measures
every other stage from pure C++, where there is no boundary to cross;
this script is the only way to see what calling the engine *from Python*
actually costs on top of that.

Method: run the exact same ExecutionSession.run() call `n` times from
Python and compare against benchmark_v2's "full_execution (TWAP)" C++-only
number for the same dataset. The difference is what going through
pybind11 (argument marshalling, GIL, Python object construction for the
returned ExecutionResult) adds per call - it is not "how fast is Python",
it is specifically the crossing cost.

Usage:
    PYTHONPATH=build python3 python/benchmark_python_boundary.py [dataset.csv]
"""
from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

from executor import CsvMarketSource, ExecutionSession, OrderSide, TWAPAlgorithm

WARMUP = 3
MEASURED = 10


def main() -> int:
    dataset = sys.argv[1] if len(sys.argv) > 1 else "datasets/sample_synthetic.csv"
    if not Path(dataset).exists():
        print(f"Dataset not found: {dataset}", file=sys.stderr)
        return 1

    def one_run():
        source = CsvMarketSource(dataset)
        twap = TWAPAlgorithm()
        orders = twap.generate_orders(1, OrderSide.Buy, 1000, 1e9, 5)
        session = ExecutionSession()
        return session.run(source, orders, 100.0)

    for _ in range(WARMUP):
        one_run()

    samples_ms = []
    for _ in range(MEASURED):
        start = time.perf_counter()
        one_run()
        samples_ms.append((time.perf_counter() - start) * 1000.0)

    samples_ms.sort()
    median = statistics.median(samples_ms)
    p95 = samples_ms[max(0, int(0.95 * (len(samples_ms) - 1)))]

    print(f"Dataset: {dataset}")
    print(f"Python-side full_execution (TWAP), n={MEASURED}:")
    print(f"  median={median:.4f} ms   p95={p95:.4f} ms   "
          f"min={samples_ms[0]:.4f} ms   max={samples_ms[-1]:.4f} ms")
    print()
    print("Compare against benchmarks/benchmark_v2's 'full_execution (TWAP)' line for")
    print("the SAME dataset (pure C++, no Python) - the difference between the two")
    print("medians is the pybind11 boundary cost for one ExecutionSession.run() call,")
    print("not a measurement of Python's general speed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
