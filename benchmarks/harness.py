"""
Shared harness for the QuantExec benchmark suite.

This module contains ONLY plumbing that every benchmark reuses:
locating the compiled C++ engine, importing the real `executor` pybind11
module, hashing datasets, capturing the environment for provenance, and
writing machine-readable JSON results with a reproducible `_meta` block.

Design rules (see benchmarks/README.md):
  * Nothing here fabricates a measurement. Every number a benchmark reports
    comes from actually running the real engine / real tests.
  * The only synthetic data produced here is throughput scaling input
    (generate_throughput_csv). It is explicitly labelled synthetic and is
    NEVER used for execution-quality ("headline") metrics - those come from
    real historical datasets only.
  * No third-party dependencies: standard library only, plus the project's
    own compiled `executor` module and stdlib-only backend/dataset_utils.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BENCH_DIR = REPO_ROOT / "benchmarks"
RESULTS_DIR = BENCH_DIR / "results"

# Engine CSV schema required by CsvMarketSource (header-aware, order-independent).
ENGINE_COLUMNS = ["timestamp_ms", "last", "bid", "ask", "bid_size", "ask_size", "volume", "bar_volume"]


# ---------------------------------------------------------------------------
# Build / module discovery
# ---------------------------------------------------------------------------

def find_build_dir() -> Path:
    """Locate the CMake build directory that holds the compiled artifacts.

    Honours QUANTEXEC_BUILD_DIR, else tries build/ then build/Release
    (Windows/multi-config). Raises if neither contains the executor module.
    """
    candidates = []
    env = os.environ.get("QUANTEXEC_BUILD_DIR")
    if env:
        candidates.append(Path(env))
    candidates += [REPO_ROOT / "build", REPO_ROOT / "build" / "Release"]
    for c in candidates:
        if c.is_dir() and (list(c.glob("executor*.so")) or list(c.glob("executor*.pyd"))):
            return c
    # Fall back to build/ even if module not found yet, so callers get a
    # clear import error rather than a confusing path error.
    return REPO_ROOT / "build"


def build_dir() -> Path:
    return find_build_dir()


def import_executor():
    """Import and return the real compiled `executor` pybind11 module."""
    bd = find_build_dir()
    if str(bd) not in sys.path:
        sys.path.insert(0, str(bd))
    import executor  # noqa: E402  (path set up above)
    return executor


def import_dataset_utils():
    """Import the project's stdlib-only dataset helpers (resolve_prices,
    compute_dataset_stats). These are reused rather than reimplemented so the
    benchmark uses exactly the same price/volatility conventions as the
    backend and CLI."""
    backend = REPO_ROOT / "backend"
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    import dataset_utils  # noqa: E402
    return dataset_utils


def benchmark_v2_path() -> Path | None:
    bd = find_build_dir()
    for name in ("benchmark_v2", "benchmark_v2.exe", "Release/benchmark_v2.exe"):
        p = bd / name
        if p.exists():
            return p
    return None


# ---------------------------------------------------------------------------
# Provenance helpers
# ---------------------------------------------------------------------------

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def count_data_rows(path: Path) -> int:
    """Number of CSV data rows (excludes the header line)."""
    n = 0
    with open(path, "r", newline="") as f:
        for _ in f:
            n += 1
    return max(0, n - 1)


def git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return None


def capture_environment() -> dict:
    """Machine/software context so a number can be interpreted and reproduced.

    Absolute performance numbers are machine-specific; this block is what lets
    a reader know which machine produced them.
    """
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or "unknown",
        "cpu_count": os.cpu_count(),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "git_commit": git_commit(),
        "build_dir": str(find_build_dir()),
    }


def new_meta(benchmark: str, reproduce: str, extra: dict | None = None) -> dict:
    meta = {
        "schema_version": "1.0",
        "benchmark": benchmark,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "reproduce_command": reproduce,
        "environment": capture_environment(),
        "honesty_note": (
            "Every value in this file was produced by actually running the "
            "real QuantExec C++ engine, tests, or a real historical-data "
            "experiment. No values are hardcoded, estimated, or hand-entered "
            "except those explicitly tagged category=ESTIMATED (model output) "
            "or category=ASSUMED (user/config parameters)."
        ),
    }
    if extra:
        meta.update(extra)
    return meta


def write_json(name: str, payload: dict) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / name
    with open(out, "w") as f:
        json.dump(payload, f, indent=2, sort_keys=False)
        f.write("\n")
    return out


# ---------------------------------------------------------------------------
# Deterministic synthetic throughput workload
# ---------------------------------------------------------------------------

def generate_throughput_csv(path: Path, num_rows: int, seed: int = 42) -> None:
    """Write a deterministic, engine-schema CSV of `num_rows` rows for pure
    THROUGHPUT scaling measurements.

    This is SYNTHETIC data and is only ever used to measure how fast the
    engine processes events at scale (there is no real dataset with 10M rows).
    It is never used for execution-quality metrics.

    Unlike datasets/generate_sample.py (an unbounded random walk that can
    wander to a non-positive price over millions of rows and be rejected by
    CsvMarketSource), this generator is mean-reverting around a base price and
    is guaranteed to stay strictly positive with bid < ask and strictly
    increasing timestamps, so it stays valid for arbitrarily large num_rows.
    Fully deterministic given (num_rows, seed).
    """
    import random

    rng = random.Random(seed)
    base = 100.0
    price = base
    cum_vol = 0
    ts = 0
    with open(path, "w", newline="") as f:
        f.write(",".join(ENGINE_COLUMNS) + "\n")
        for _ in range(num_rows):
            ts += 1
            # Ornstein-Uhlenbeck-style mean reversion keeps price bounded/positive.
            price += 0.05 * (base - price) + rng.uniform(-0.05, 0.05)
            if price < 1.0:
                price = 1.0
            last = round(price, 2)
            bid = round(price - 0.01, 2)
            ask = round(price + 0.01, 2)
            if bid <= 0:
                bid = 0.01
            if ask <= bid:
                ask = round(bid + 0.01, 2)
            bid_size = rng.randint(100, 500)
            ask_size = rng.randint(100, 500)
            bar_volume = rng.randint(50, 300)
            cum_vol += bar_volume
            f.write(f"{ts},{last},{bid},{ask},{bid_size},{ask_size},{cum_vol},{bar_volume}\n")


def human_int(n: int) -> str:
    return f"{n:,}"


if __name__ == "__main__":
    # Smoke self-check: prove discovery + import work on this checkout.
    ex = import_executor()
    du = import_dataset_utils()
    print("executor module:", ex.__file__)
    print("run_adaptive bound:", hasattr(ex.ExecutionSession, "run_adaptive"))
    print("build dir:", find_build_dir())
    print("benchmark_v2:", benchmark_v2_path())
    print("environment:", json.dumps(capture_environment(), indent=2))
