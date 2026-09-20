"""
Generates a small, diverse suite of SYNTHETIC market datasets under
datasets/synthetic/.

Why this exists: the only *real* dataset bundled with the project is one
hour of AAPL quotes (datasets/historical/), which is quote-only (volume=0)
and therefore cannot exercise the POV strategy or multi-symbol/regime
behaviour. This script produces several deterministic, clearly-labelled
synthetic datasets spanning different market regimes (calm/liquid,
volatile, wide-spread/illiquid, trending, mean-reverting) so the engine,
dashboard, and strategy-comparison view can be demonstrated across varied
conditions - WITH non-zero traded volume, so POV produces fills.

These are NOT real market data. Every file gets a manifest with
data_type="synthetic" (see scripts/build_dataset_manifest.py). Re-running
this script produces byte-identical output every time (fixed per-regime
seeds), preserving the project's determinism guarantees.

Usage:
    python datasets/generate_synthetic_suite.py
    # then build manifests (the script prints the exact commands), or:
    python datasets/generate_synthetic_suite.py --with-manifests
"""

from __future__ import annotations

import argparse
import random
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "synthetic"
REPO_ROOT = HERE.parent
MANIFEST_TOOL = REPO_ROOT / "scripts" / "build_dataset_manifest.py"


@dataclass
class Regime:
    filename: str
    symbol: str
    start_price: float
    drift_per_step: float          # deterministic per-step price drift
    volatility: float              # +/- uniform random step, added to drift
    spread: float                  # absolute bid/ask spread
    size_range: tuple[int, int]    # displayed bid/ask size range
    bar_volume_range: tuple[int, int]  # per-row traded volume range (>0 -> POV fills)
    num_rows: int
    seed: int
    notes: str


# fields: filename, symbol, start_price, drift_per_step, volatility, spread,
#         size_range, bar_volume_range, num_rows, seed, notes
REGIMES = [
    Regime("lowvol_liquid.csv", "SYNLQ", 250.00, 0.0, 0.03, 0.02, (800, 1500),
           (400, 900), 90, 101,
           "Calm, liquid large-cap-like name: tight spread, deep size, steady volume."),
    Regime("highvol_active.csv", "SYNHV", 120.00, 0.0, 0.20, 0.06, (200, 600),
           (300, 1200), 90, 202,
           "High-volatility active name: wider swings, medium depth, heavy volume."),
    Regime("wide_illiquid.csv", "SYNWD", 32.50, 0.0, 0.08, 0.20, (30, 120),
           (10, 90), 90, 303,
           "Wide-spread, thin small-cap-like name: shallow displayed size, light volume."),
    Regime("trending_up.csv", "SYNTR", 80.00, 0.015, 0.04, 0.02, (300, 800),
           (200, 700), 90, 404,
           "Steady upward intraday trend: positive drift with moderate noise."),
    Regime("mean_reverting.csv", "SYNMR", 100.00, 0.0, 0.10, 0.03, (400, 900),
           (250, 800), 90, 505,
           "Mean-reverting oscillation around a stable fair value."),
]


def _round2(x: float) -> float:
    return round(x + 1e-9, 2)


def generate_regime(regime: Regime, out_dir: Path = OUT_DIR) -> Path:
    """Write one deterministic synthetic dataset for the given regime."""
    rng = random.Random(regime.seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / regime.filename

    rows = []
    price = regime.start_price
    ts = 0
    cum_vol = 0
    anchor = regime.start_price  # for mean reversion
    for i in range(regime.num_rows):
        ts += 60_000  # one minute per row (ms)

        noise = rng.uniform(-regime.volatility, regime.volatility)
        if regime.filename == "mean_reverting.csv":
            # Pull back toward the anchor plus noise.
            price = price + 0.15 * (anchor - price) + noise
        else:
            price = price + regime.drift_per_step + noise
        price = max(0.5, _round2(price))

        half = regime.spread / 2.0
        bid = _round2(price - half)
        ask = _round2(price + half)
        if bid >= ask:  # guard against zero/inverted spread after rounding
            ask = _round2(bid + 0.01)

        bid_size = rng.randint(*regime.size_range)
        ask_size = rng.randint(*regime.size_range)
        bar_volume = rng.randint(*regime.bar_volume_range)
        cum_vol += bar_volume

        # A plausible (not real) second depth level, one cent worse, larger.
        bid2 = _round2(bid - 0.01)
        ask2 = _round2(ask + 0.01)
        bid2_size = bid_size + rng.randint(50, 300)
        ask2_size = ask_size + rng.randint(50, 300)

        rows.append([
            ts, _round2(price), bid, ask, bid_size, ask_size, cum_vol, bar_volume,
            f"{bid}:{bid_size}|{bid2}:{bid2_size}",
            f"{ask}:{ask_size}|{ask2}:{ask2_size}",
        ])

    header = ("timestamp_ms,last,bid,ask,bid_size,ask_size,volume,bar_volume,"
              "bid_depth,ask_depth")
    with open(path, "w") as f:
        f.write(header + "\n")
        for row in rows:
            f.write(",".join(str(v) for v in row) + "\n")
    return path


def build_manifest(regime: Regime, csv_path: Path) -> None:
    manifest_path = csv_path.with_suffix("").with_suffix(".manifest.json")
    # Reuse the project's own provenance tool so the checksum/columns match
    # exactly what an experiment records.
    subprocess.run(
        [
            sys.executable, str(MANIFEST_TOOL), str(csv_path),
            "--data-type", "synthetic",
            "--symbol", regime.symbol,
            "--resolution", "synthetic 1-minute top-of-book (+1 depth level)",
            "--notes", regime.notes,
            "-o", str(manifest_path),
        ],
        check=True,
        cwd=str(REPO_ROOT),
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--with-manifests", action="store_true",
                        help="Also build a manifest for each dataset via scripts/build_dataset_manifest.py")
    args = parser.parse_args(argv)

    print(f"Writing {len(REGIMES)} synthetic datasets to {OUT_DIR.relative_to(REPO_ROOT)}/ ...")
    for regime in REGIMES:
        csv_path = generate_regime(regime)
        rel = csv_path.relative_to(REPO_ROOT)
        print(f"  {rel}  ({regime.symbol}: {regime.notes})")
        if args.with_manifests:
            build_manifest(regime, csv_path)
            print(f"    -> manifest written")
    if not args.with_manifests:
        print("\nRe-run with --with-manifests to also generate provenance manifests.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
