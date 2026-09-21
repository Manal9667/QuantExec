"""
Engine throughput benchmark.

Measures how fast the REAL C++ execution engine processes market events at
several workload sizes. It does NOT reimplement any timing loop: it drives
the existing, evidence-based `benchmark_v2` binary (benchmarks/benchmark_v2.cpp,
CMake target `benchmark_v2`) which runs 3 warm-up + 10 measured iterations of
each pipeline stage on a real dataset via CsvMarketSource -> ExecutionSession.
We parse its machine-readable `QUANTEXEC_JSON` line and derive throughput.

Two kinds of workload are reported and clearly distinguished:

  * SYNTHETIC SCALING (10k .. 10M rows): deterministic mean-reverting input
    from harness.generate_throughput_csv, used ONLY to characterise raw
    engine throughput/scaling where no real dataset of that size exists.
  * REAL DATA: the largest real historical dataset present
    (data/raw/alpaca/AAPL/... , ~171k IEX quote events), so at least one
    throughput number is measured on genuine market data.

Headline throughput uses the `full_execution` stage = replay + a real
ExecutionSession.run() (TWAP, 5 slices). We also report the pure `replay`
stage. peak_rss_kb is a whole-process peak from getrusage (a documented
benchmark_v2 limitation - not per-stage).

Reproduce:
    PYTHONPATH=build python3 benchmarks/engine_throughput.py
Options:
    --sizes 10000 100000 1000000 10000000   (synthetic scaling sizes)
    --seed 42
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

import harness as H

# Per-size subprocess timeout (seconds). Larger workloads get more budget;
# if a size exceeds it (e.g. 10M runs out of time/memory on a small sandbox)
# it is recorded as skipped with a reason rather than faked or omitted.
TIMEOUTS = {10_000: 120, 100_000: 240, 1_000_000: 600, 10_000_000: 1200}
DEFAULT_SIZES = [10_000, 100_000, 1_000_000, 10_000_000]

REAL_DATASET = "data/raw/alpaca/AAPL/AAPL_2024-01-03_1430-1530_quotes.csv"


def run_benchmark_v2(dataset: Path, timeout: int) -> dict:
    """Run benchmark_v2 --json on `dataset`; return the parsed QUANTEXEC_JSON
    dict, or {'error': ...} on failure/timeout."""
    exe = H.benchmark_v2_path()
    if exe is None:
        return {"error": "benchmark_v2 binary not found - build with CMake first"}
    try:
        proc = subprocess.run(
            [str(exe), str(dataset), "--json"],
            cwd=H.REPO_ROOT, capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"error": f"timeout after {timeout}s"}
    if proc.returncode != 0:
        return {"error": f"benchmark_v2 exited {proc.returncode}: {proc.stderr.strip()[:300]}"}
    for line in proc.stdout.splitlines():
        if line.startswith("QUANTEXEC_JSON "):
            return json.loads(line[len("QUANTEXEC_JSON "):])
    return {"error": "no QUANTEXEC_JSON line in benchmark_v2 output"}


def derive_throughput(raw: dict) -> dict:
    """Turn a benchmark_v2 JSON blob into throughput metrics."""
    events = raw["events"]
    stages = raw["stage_median_ms"]
    full_ms = stages.get("full_execution")
    replay_ms = stages.get("replay")
    matching_ms = stages.get("matching")
    out = {
        "events": events,
        "peak_rss_kb": raw.get("peak_rss_kb"),
        "measured_iterations": raw.get("measured_iters"),
        "warmup_iterations": raw.get("warmup_iters"),
        "stage_median_ms": stages,
    }
    if full_ms and full_ms > 0:
        out["full_execution_events_per_second"] = round(events / (full_ms / 1000.0), 2)
        out["full_execution_us_per_event"] = round((full_ms * 1000.0) / events, 6)
    if replay_ms and replay_ms > 0:
        out["replay_events_per_second"] = round(events / (replay_ms / 1000.0), 2)
        out["replay_us_per_event"] = round((replay_ms * 1000.0) / events, 6)
    if matching_ms and matching_ms > 0:
        out["matching_events_per_second"] = round(events / (matching_ms / 1000.0), 2)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="QuantExec engine throughput benchmark")
    ap.add_argument("--sizes", nargs="*", type=int, default=DEFAULT_SIZES)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    synthetic_runs = []
    with tempfile.TemporaryDirectory(prefix="quantexec_throughput_") as td:
        tmp = Path(td)
        for size in args.sizes:
            csv_path = tmp / f"synthetic_{size}.csv"
            print(f"[synthetic] generating {H.human_int(size)} rows ...", flush=True)
            H.generate_throughput_csv(csv_path, size, seed=args.seed)
            timeout = TIMEOUTS.get(size, 1200)
            print(f"[synthetic] benchmark_v2 on {H.human_int(size)} rows (timeout {timeout}s) ...", flush=True)
            raw = run_benchmark_v2(csv_path, timeout)
            if "error" in raw:
                synthetic_runs.append({
                    "requested_rows": size, "status": "skipped", "reason": raw["error"],
                })
                print(f"[synthetic] {H.human_int(size)}: SKIPPED - {raw['error']}", flush=True)
            else:
                rec = {"requested_rows": size, "status": "ok", **derive_throughput(raw)}
                synthetic_runs.append(rec)
                print(f"[synthetic] {H.human_int(size)}: "
                      f"{rec.get('full_execution_events_per_second')} events/s "
                      f"(full_execution), peak_rss={rec.get('peak_rss_kb')}KB", flush=True)
            # Free disk immediately before generating the next (bigger) file.
            try:
                csv_path.unlink()
            except OSError:
                pass

    # Real-data throughput (genuine market data, not synthetic).
    real_runs = []
    real_path = H.REPO_ROOT / REAL_DATASET
    if real_path.exists():
        print(f"[real] benchmark_v2 on {REAL_DATASET} ...", flush=True)
        raw = run_benchmark_v2(real_path, 900)
        if "error" in raw:
            real_runs.append({"dataset": REAL_DATASET, "status": "skipped", "reason": raw["error"]})
        else:
            rec = {
                "dataset": REAL_DATASET,
                "dataset_sha256": H.sha256_file(real_path),
                "data_rows": H.count_data_rows(real_path),
                "status": "ok",
                "provenance": "Real AAPL top-of-book quotes, Alpaca IEX feed (see .metadata.json)",
                **derive_throughput(raw),
            }
            real_runs.append(rec)
            print(f"[real] {REAL_DATASET}: {rec.get('full_execution_events_per_second')} events/s", flush=True)
    else:
        real_runs.append({"dataset": REAL_DATASET, "status": "missing", "reason": "file not present"})

    ok_synth = [r for r in synthetic_runs if r.get("status") == "ok"]
    payload = {
        "_meta": H.new_meta(
            "engine_throughput",
            "PYTHONPATH=build python3 benchmarks/engine_throughput.py",
            extra={
                "engine": "real C++ ExecutionSession via benchmark_v2 (benchmarks/benchmark_v2.cpp)",
                "headline_stage": "full_execution = CsvMarketSource replay + ExecutionSession.run (TWAP, 5 slices)",
                "category": "CALCULATED (throughput derived from OBSERVED wall-clock timings of the real engine)",
                "synthetic_workload_note": (
                    "Synthetic scaling rows are deterministic mean-reverting input "
                    "(harness.generate_throughput_csv); used ONLY for raw throughput "
                    "scaling, never for execution-quality metrics."
                ),
            },
        ),
        "synthetic_scaling": synthetic_runs,
        "real_data": real_runs,
        "peak_full_execution_events_per_second": (
            max((r["full_execution_events_per_second"] for r in ok_synth
                 if "full_execution_events_per_second" in r), default=None)
        ),
    }
    out = H.write_json("engine_throughput.json", payload)
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
