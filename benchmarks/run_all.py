"""
Run the entire QuantExec benchmark suite end-to-end and regenerate the
reports. Each stage writes its own JSON to benchmarks/results/; the final
step aggregates them into BENCHMARK_REPORT.md and RESUME_METRICS.md.

Reproduce (from a clean, built checkout - see benchmarks/README.md for
prerequisites):
    PYTHONPATH=build python3 benchmarks/run_all.py

Options:
    --quick   Use smaller workloads (skip the 1M/10M throughput sizes and use
              fewer determinism reps) for a fast smoke run.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

import harness as H

BENCH = H.BENCH_DIR


def run_stage(title: str, argv: list[str]) -> dict:
    print(f"\n{'='*70}\n{title}\n{'='*70}", flush=True)
    t0 = time.perf_counter()
    proc = subprocess.run([sys.executable, *argv], cwd=H.REPO_ROOT)
    dt = time.perf_counter() - t0
    ok = proc.returncode == 0
    print(f"[{'OK' if ok else 'FAIL'}] {title} ({dt:.1f}s)", flush=True)
    return {"title": title, "ok": ok, "seconds": round(dt, 1)}


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the full QuantExec benchmark suite")
    ap.add_argument("--quick", action="store_true", help="fast smoke run with smaller workloads")
    args = ap.parse_args()

    thr_args = ["benchmarks/engine_throughput.py"]
    det_args = ["benchmarks/determinism.py"]
    if args.quick:
        thr_args += ["--sizes", "10000", "100000"]
        det_args += ["--small-reps", "100", "--large-reps", "20"]

    stages = [
        ("Dataset inventory", ["benchmarks/dataset_inventory.py"]),
        ("Engine throughput", thr_args),
        ("Strategy study", ["benchmarks/strategy_study.py"]),
        ("Determinism", det_args),
        ("Order-book correctness", ["benchmarks/orderbook_correctness.py"]),
        ("Automated test inventory", ["benchmarks/test_inventory.py"]),
        ("No-lookahead validation", ["benchmarks/no_lookahead.py"]),
    ]
    results = [run_stage(t, a) for t, a in stages]

    # Reports last, after all result JSONs exist.
    results.append(run_stage("Generate reports", ["benchmarks/generate_report.py"]))

    print(f"\n{'='*70}\nSUMMARY\n{'='*70}")
    for r in results:
        print(f"  [{'OK' if r['ok'] else 'FAIL'}] {r['title']:<28} {r['seconds']:>7.1f}s")
    n_ok = sum(1 for r in results if r["ok"])
    print(f"\n{n_ok}/{len(results)} stages OK")
    return 0 if n_ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
