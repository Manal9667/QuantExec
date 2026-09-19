"""
Dataset path resolution, price defaulting, and dataset statistics.

Deliberately has ZERO third-party dependencies (stdlib only: csv,
statistics, pathlib) and does NOT import `executor` (the compiled C++
extension) or `schemas` (which needs pydantic). This is what makes it
possible to unit-test this logic - the thing the project's own honest
assessment flagged as missing ("no automated tests covering ... missing
datasets ... malformed configurations ... path validation") - without a
working C++ build or a pydantic install. See backend/tests/test_dataset_utils.py,
which does exactly that and actually runs in this repo's CI/dev
environment regardless of whether the native extension is built yet.

experiment_service.py imports this module for the pieces that don't need
the engine; it's the only consumer today, but nothing here depends on it.
"""

from __future__ import annotations

import csv
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


class DatasetError(ValueError):
    """A dataset path or dataset content problem - distinct from
    ExperimentError so callers that only care about datasets (e.g. the
    /datasets endpoint) don't need to import the full experiment service."""


@dataclass
class DatasetStats:
    """Aggregate stats read once from the raw CSV, used only for the
    optional market-impact estimate (spec section 31) - the core
    execution path never needs these."""

    total_bar_volume: int = 0
    mid_price_volatility: float = 0.0  # population stdev of tick-to-tick mid-price returns
    row_count: int = 0


def resolve_dataset_path(repo_root: Path, dataset: str) -> Path:
    """Resolve a dataset path relative to repo_root, refusing to escape it.

    Raises DatasetError (not a generic exception) so callers can turn this
    into a 400, not a 500 - a missing/invalid dataset is a client error,
    not a server bug.
    """
    if not dataset or not dataset.strip():
        raise DatasetError("Dataset path must not be empty")

    candidate = (repo_root / dataset).resolve()
    repo_root_resolved = repo_root.resolve()

    # Path-traversal guard: candidate must be repo_root itself or a
    # descendant of it. Using resolve() (which follows symlinks and
    # collapses "..") on both sides means "../../etc/passwd" and similar
    # are caught even if the string itself looks locally scoped.
    if candidate != repo_root_resolved and repo_root_resolved not in candidate.parents:
        raise DatasetError("Dataset path must stay inside the project directory")

    if not candidate.exists():
        raise DatasetError(f"Dataset not found: {dataset}")
    if not candidate.is_file():
        raise DatasetError(f"Dataset path is not a file: {dataset}")

    return candidate


def resolve_prices(
    dataset_path: Path,
    limit_price: Optional[float],
    arrival_price: Optional[float],
) -> tuple[float, float]:
    """Derive limit_price / arrival_price from the dataset's first row when
    the caller leaves them unset (same default rule python/run_experiment.py
    uses, so both entry points agree without importing one another)."""
    if limit_price is not None and arrival_price is not None:
        return float(limit_price), float(arrival_price)

    with open(dataset_path, newline="") as f:
        reader = csv.DictReader(f)
        try:
            first = next(reader)
        except StopIteration:
            raise DatasetError(f"Dataset is empty (no data rows): {dataset_path}")

    for required in ("bid", "ask"):
        if required not in first:
            raise DatasetError(
                f"Dataset is missing required column '{required}': {dataset_path}"
            )
        try:
            float(first[required])
        except (TypeError, ValueError):
            raise DatasetError(
                f"Dataset column '{required}' is not numeric in its first row: {dataset_path}"
            )

    bid, ask = float(first["bid"]), float(first["ask"])
    mid = (bid + ask) / 2.0
    if limit_price is None:
        limit_price = ask * 1.02
    if arrival_price is None:
        arrival_price = mid
    return float(limit_price), float(arrival_price)


def list_dataset_files(repo_root: Path, subdir: str = "datasets") -> list[str]:
    """List CSV files under repo_root/subdir, as paths relative to
    repo_root (e.g. "datasets/sample_synthetic.csv"). Used by the
    /datasets endpoint to show every dataset on disk - including ones that
    haven't been registered in dataset_metadata yet, so a forgotten
    metadata entry is visible as "undocumented" rather than invisible.
    """
    directory = repo_root / subdir
    if not directory.is_dir():
        return []
    return sorted(
        str(p.relative_to(repo_root)).replace("\\", "/")
        for p in directory.glob("*.csv")
        if p.is_file()
    )


# Honest, checked-in metadata for the dataset that actually ships in this
# repo (spec section 5 requires: source, instrument, exchange, date range,
# resolution, fields, L1/L2 classification, licensing, limitations).
# This is data ABOUT the dataset, not the dataset itself - keeping it here
# (rather than only in a doc) means the same facts back both dataset.md
# and the /datasets API response instead of the two silently drifting apart.
DEFAULT_DATASET_METADATA: dict[str, dict] = {
    "datasets/sample_synthetic.csv": {
        "symbol": "SYN",
        "date_range": "N/A - synthetic, no real calendar dates or trading session",
        "resolution": "irregular event ticks (generated, not clock-based bars)",
        "fields": "timestamp_ms,last,bid,ask,bid_size,ask_size,volume,bar_volume,bid_depth,ask_depth",
        "data_type": "synthetic L1 top-of-book + synthetic multi-level depth (NOT reconstructed real L2)",
        "notes": (
            "Generated by datasets/generate_sample.py for deterministic testing. "
            "Not genuine historical market data - see dataset.md for the full "
            "provenance statement and for what real-data ingestion (Alpaca) does and "
            "does not provide."
        ),
    },
}


def compute_dataset_stats(dataset_path: Path) -> DatasetStats:
    """Single pass over the CSV for total traded volume and mid-price
    volatility. Only computed when an impact estimate is requested -
    the core execution path never needs this."""
    volumes: list[int] = []
    mids: list[float] = []
    row_count = 0

    with open(dataset_path, newline="") as f:
        reader = csv.DictReader(f)
        # `bar_volume` is per-row (incremental) volume and can be summed as-is.
        # `volume` is CUMULATIVE session volume (see dataset.md), so when only
        # that column exists we must sum its per-row increments, not the raw
        # values - summing a running total would count early volume many times
        # over and understate participation in the impact estimate.
        has_bar_volume = "bar_volume" in (reader.fieldnames or [])
        prev_cumulative = 0
        for row in reader:
            row_count += 1
            try:
                if has_bar_volume:
                    volumes.append(int(float(row.get("bar_volume") or "0")))
                else:
                    cumulative = int(float(row.get("volume") or "0"))
                    # A drop means the session counter reset; treat the new
                    # value as fresh volume rather than a negative increment.
                    volumes.append(cumulative - prev_cumulative if cumulative >= prev_cumulative else cumulative)
                    prev_cumulative = cumulative
            except ValueError:
                continue  # malformed row: skip rather than crash the whole estimate
            try:
                bid, ask = float(row["bid"]), float(row["ask"])
            except (KeyError, ValueError):
                continue
            if bid > 0 and ask > 0:
                mids.append((bid + ask) / 2.0)

    if row_count == 0:
        raise DatasetError(f"Dataset is empty (no data rows): {dataset_path}")

    returns = [
        (mids[i] - mids[i - 1]) / mids[i - 1]
        for i in range(1, len(mids))
        if mids[i - 1] > 0
    ]
    volatility = statistics.pstdev(returns) if len(returns) > 1 else 0.0
    return DatasetStats(
        total_bar_volume=sum(volumes),
        mid_price_volatility=volatility,
        row_count=row_count,
    )