#!/usr/bin/env python3
"""
Performance-regression check (spec section 35: "add performance regression
thresholds").

benchmarks/benchmark_v2.cpp measures per-stage timings but deliberately does
not hardcode pass/fail thresholds, because absolute timings are
machine-specific and would silently become meaningless on any other machine.
This script closes that loop *without* being flaky on variable CI hardware:

  1. It generates a deterministic synthetic workload (reusing
     datasets/generate_sample.py, so the schema always matches the engine).
  2. It runs `benchmark_v2 --json` against it and parses the machine-readable
     line it emits.
  3. It compares the measured numbers against a committed baseline
     (docs/benchmarks/thresholds.json) using a *generous multiplier*, so only
     large regressions - the kind that signal an algorithmic problem, e.g. an
     accidental O(n^2) - fail the build. Sub-millisecond stages, where timing
     noise dominates, are not gated on their own; the whole-pipeline
     throughput floor is the primary signal.

Usage:
    # Check against the committed baseline (exit non-zero on regression):
    python scripts/check_perf_regression.py --build-dir build

    # Record a fresh baseline on THIS machine (run on a quiet machine):
    python scripts/check_perf_regression.py --build-dir build --update-baseline
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_THRESHOLDS = REPO_ROOT / "docs" / "benchmarks" / "thresholds.json"
SENTINEL = "QUANTEXEC_JSON "

# Stages faster than this (in the baseline) are not gated individually - at
# sub-100-microsecond scale, run-to-run timing noise on a shared CI runner
# swamps any real signal. They are still recorded in the baseline for context.
MIN_GATED_STAGE_MS = 0.05


def _generate_workload(num_rows: int, seed: int, path: Path) -> None:
    """Write a deterministic synthetic dataset using the project's own
    generator, so the columns/validation always match CsvMarketSource."""
    sys.path.insert(0, str(REPO_ROOT / "datasets"))
    import generate_sample  # noqa: WPS433 (local import by design)

    generate_sample.generate(path=str(path), num_rows=num_rows, seed=seed)


def _run_benchmark(build_dir: Path, dataset: Path) -> dict:
    """Run benchmark_v2 --json and return the parsed measurement dict."""
    exe = build_dir / "benchmark_v2"
    if not exe.exists():
        exe_alt = build_dir / "Release" / "benchmark_v2.exe"  # Windows multi-config
        if exe_alt.exists():
            exe = exe_alt
        else:
            raise SystemExit(
                f"benchmark_v2 not found in {build_dir} - build it first "
                f"(cmake --build {build_dir} --target benchmark_v2)."
            )
    proc = subprocess.run(
        [str(exe), "--json", str(dataset)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout + proc.stderr)
        raise SystemExit(f"benchmark_v2 exited with {proc.returncode}")
    for line in proc.stdout.splitlines():
        if line.startswith(SENTINEL):
            return json.loads(line[len(SENTINEL):])
    raise SystemExit("benchmark_v2 did not emit a QUANTEXEC_JSON line")


def _events_per_second(measure: dict) -> float:
    full_ms = measure["stage_median_ms"]["full_execution"]
    if full_ms <= 0:
        return float("inf")
    return measure["events"] / (full_ms / 1000.0)


def _write_baseline(path: Path, workload: dict, measure: dict, multiplier: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "note": (
            "Performance baseline for scripts/check_perf_regression.py. Numbers "
            "are machine-specific; regenerate on your own reference machine with "
            "`--update-baseline`. The check applies tolerance_multiplier so only "
            "large (algorithmic) regressions fail. See docs/BENCHMARKING.md."
        ),
        "workload": workload,
        "tolerance_multiplier": multiplier,
        "baseline": {
            "events_per_second": round(_events_per_second(measure), 2),
            "stage_median_ms": measure["stage_median_ms"],
        },
    }
    path.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"Wrote baseline -> {path.relative_to(REPO_ROOT)}")
    print(f"  throughput: {payload['baseline']['events_per_second']:.0f} events/s "
          f"(full_execution stage), multiplier x{multiplier}")


def _check(thresholds: dict, measure: dict) -> int:
    mult = thresholds["tolerance_multiplier"]
    base = thresholds["baseline"]
    failures = []

    # 1. Whole-pipeline throughput floor (primary, noise-robust signal).
    measured_eps = _events_per_second(measure)
    min_eps = base["events_per_second"] / mult
    status = "OK" if measured_eps >= min_eps else "REGRESSION"
    if measured_eps < min_eps:
        failures.append(
            f"throughput {measured_eps:.0f} ev/s < floor {min_eps:.0f} ev/s "
            f"(baseline {base['events_per_second']:.0f} / x{mult})"
        )
    print(f"[{status:^11}] throughput: {measured_eps:>12.0f} ev/s  "
          f"(floor {min_eps:.0f})")

    # 2. Per-stage ceilings for stages large enough to measure reliably.
    for stage, base_ms in base["stage_median_ms"].items():
        measured_ms = measure["stage_median_ms"].get(stage)
        if measured_ms is None:
            continue
        if base_ms < MIN_GATED_STAGE_MS:
            print(f"[  skipped  ] {stage:<16} {measured_ms:.6f} ms "
                  f"(baseline {base_ms:.6f} ms below {MIN_GATED_STAGE_MS} ms gate)")
            continue
        ceiling = base_ms * mult
        ok = measured_ms <= ceiling
        if not ok:
            failures.append(
                f"stage '{stage}' {measured_ms:.4f} ms > ceiling {ceiling:.4f} ms "
                f"(baseline {base_ms:.4f} x{mult})"
            )
        print(f"[{('OK' if ok else 'REGRESSION'):^11}] {stage:<16} "
              f"{measured_ms:>10.4f} ms  (ceiling {ceiling:.4f})")

    if failures:
        print("\nPERFORMANCE REGRESSION DETECTED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nNo performance regression: all gated metrics within tolerance.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", default="build", type=Path)
    parser.add_argument("--thresholds", default=DEFAULT_THRESHOLDS, type=Path)
    parser.add_argument("--events", type=int, default=None,
                        help="Override workload size (else taken from thresholds/default).")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--tolerance", type=float, default=None,
                        help="Override tolerance multiplier when updating a baseline.")
    parser.add_argument("--update-baseline", action="store_true")
    args = parser.parse_args()

    # Resolve workload parameters (thresholds file wins, then defaults).
    existing = None
    if args.thresholds.is_file():
        existing = json.loads(args.thresholds.read_text())
    default_workload = {"events": 20000, "seed": 42}
    workload = (existing or {}).get("workload", default_workload) if existing else default_workload
    events = args.events or workload.get("events", 20000)
    seed = args.seed or workload.get("seed", 42)
    workload = {"events": events, "seed": seed, "generator": "datasets/generate_sample.py"}

    with tempfile.TemporaryDirectory() as tmp:
        dataset = Path(tmp) / "perf_workload.csv"
        _generate_workload(events, seed, dataset)
        measure = _run_benchmark(args.build_dir, dataset)

    print(f"Workload: {measure['events']} events, seed {seed}, "
          f"{measure['measured_iters']} measured iters\n")

    if args.update_baseline:
        multiplier = args.tolerance or (existing or {}).get("tolerance_multiplier", 4.0)
        _write_baseline(args.thresholds, workload, measure, multiplier)
        return 0

    if existing is None:
        raise SystemExit(
            f"No thresholds file at {args.thresholds}. Create one first with "
            f"--update-baseline (on a quiet reference machine)."
        )
    return _check(existing, measure)


if __name__ == "__main__":
    raise SystemExit(main())
