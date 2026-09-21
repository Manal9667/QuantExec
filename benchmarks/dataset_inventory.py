"""
Historical dataset inventory + provenance / validation study.

Enumerates the REAL historical market datasets available in the repo, reads
their provenance manifests, and validates each engine-schema CSV by actually
loading it through the real CsvMarketSource (the same loader the engine uses).
Synthetic fixtures are listed separately and clearly labelled - never counted
as real market data.

For each dataset it records: symbol, date, time range, quote count, trade
count (if any), source/feed, a content identifier (SHA-256), provenance
(manifest reference), and validation status.

Honesty note baked into the output: the two engine-ready real files
(datasets/historical/...0930-1030ET and data/raw/alpaca/AAPL/...1430-1530)
are TWO RESOLUTIONS OF THE SAME real trading hour (AAPL 2024-01-03,
09:30-10:30 America/New_York == 14:30-15:30 UTC), derived from ONE raw
capture. So the honest distinct-session count is 1 symbol / 1 session /
1 day - reported as such, not inflated.

Reproduce:
    PYTHONPATH=build python3 benchmarks/dataset_inventory.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import harness as H

# (relative_csv_path, companion_manifest_or_metadata, kind)
REAL_DATASETS = [
    ("datasets/historical/AAPL_2024-01-03_0930-1030ET.csv",
     "datasets/historical/AAPL_2024-01-03_0930-1030ET.manifest.json", "engine_schema"),
    ("data/raw/alpaca/AAPL/AAPL_2024-01-03_1430-1530_quotes.csv",
     "data/raw/alpaca/AAPL/AAPL_2024-01-03_1430-1530_quotes.metadata.json", "engine_schema"),
    ("historical-execution/data/raw/alpaca/AAPL_2024-01-03_1430-1530_quotes.csv",
     "historical-execution/data/raw/alpaca/AAPL_2024-01-03_1430-1530_quotes.metadata.json", "raw_alpaca_schema"),
]

SYNTHETIC_DATASETS = [
    "datasets/sample_synthetic.csv",
    "datasets/stress/incomplete_depth.csv",
    "datasets/stress/price_gap.csv",
    "datasets/stress/rapid_price_change.csv",
    "datasets/stress/thin_liquidity.csv",
    "datasets/stress/wide_spread.csv",
    "datasets/stress/zero_volume.csv",
]


def _load_manifest(path: Path) -> dict | None:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            return None
    return None


def _timestamp_range(csv_path: Path) -> tuple[int | None, int | None]:
    first = last = None
    try:
        with open(csv_path, newline="") as f:
            reader = csv.DictReader(f)
            if "timestamp_ms" not in (reader.fieldnames or []):
                return None, None
            for row in reader:
                try:
                    ts = int(row["timestamp_ms"])
                except (ValueError, KeyError, TypeError):
                    continue
                if first is None:
                    first = ts
                last = ts
    except Exception:
        return None, None
    return first, last


def _validate_engine_schema(ex, csv_path: Path) -> dict:
    src = ex.CsvMarketSource(str(csv_path))
    return {"csv_market_source_ok": bool(src.ok())}


def inventory_real(ex) -> list[dict]:
    out = []
    for rel, manifest_rel, kind in REAL_DATASETS:
        cpath = H.REPO_ROOT / rel
        if not cpath.exists():
            out.append({"dataset": rel, "status": "missing"})
            continue
        manifest = _load_manifest(H.REPO_ROOT / manifest_rel)
        rows = H.count_data_rows(cpath)
        rec = {
            "dataset": rel,
            "kind": kind,
            "data_type": "historical",
            "status": "present",
            "identifier_sha256": H.sha256_file(cpath),
            "data_rows": rows,
            "manifest_file": manifest_rel if manifest else None,
        }
        # Pull provenance fields from whichever manifest style is present.
        if manifest:
            rec["symbol"] = manifest.get("symbol", "AAPL")
            rec["source"] = manifest.get("source") or manifest.get("provider") or manifest.get("source_url")
            rec["feed"] = manifest.get("feed") or manifest.get("venue")
            rec["data_level"] = manifest.get("data_level") or ("L1" if "quote" in rel.lower() else None)
            rec["provider"] = manifest.get("provider")
            rec["license"] = manifest.get("license")
            rec["timezone"] = manifest.get("timezone")
            rec["start"] = manifest.get("start") or manifest.get("start_timestamp_ms")
            rec["end"] = manifest.get("end") or manifest.get("end_timestamp_ms")
            # quote / trade counts from manifest where available
            rec["records_downloaded"] = manifest.get("records_downloaded") or manifest.get("row_count_raw")
            rec["records_valid"] = manifest.get("records_valid") or manifest.get("row_count_valid_quotes")
            rec["manifest_validation"] = manifest.get("validation")
            rec["manifest_notes"] = manifest.get("notes") or manifest.get("resolution")

        # OBSERVED facts derived directly from the CSV.
        first_ts, last_ts = _timestamp_range(cpath) if kind == "engine_schema" else (None, None)
        rec["first_timestamp_ms"] = first_ts
        rec["last_timestamp_ms"] = last_ts
        # quote count = data rows for quote datasets; trade count = 0 (quote-only).
        rec["quote_count"] = rows
        rec["trade_count"] = 0
        rec["trade_data_available"] = False
        rec["quote_only_note"] = (
            "Quote-only capture: no trade prints were acquired; 'last' is the "
            "quote midpoint and traded 'volume' may be 0 or bar-approximated. "
            "This is disclosed in the manifest and LIMITATIONS.md."
        )
        if kind == "engine_schema":
            rec["validation"] = _validate_engine_schema(ex, cpath)
        else:
            rec["validation"] = {
                "csv_market_source_ok": False,
                "reason": "raw Alpaca quote schema (symbol,timestamp,bid_price,...); "
                          "must be normalized to engine schema before CsvMarketSource can load it",
            }
        out.append(rec)
    return out


def inventory_synthetic() -> list[dict]:
    out = []
    for rel in SYNTHETIC_DATASETS:
        cpath = H.REPO_ROOT / rel
        if not cpath.exists():
            continue
        out.append({
            "dataset": rel,
            "data_type": "synthetic",
            "data_rows": H.count_data_rows(cpath),
            "identifier_sha256": H.sha256_file(cpath),
            "note": "Deterministic synthetic fixture - NOT real market data; used for tests/demos only.",
        })
    return out


def main() -> int:
    ex = H.import_executor()
    real = inventory_real(ex)
    synthetic = inventory_synthetic()

    present_real = [d for d in real if d.get("status") == "present"]
    engine_ready = [d for d in present_real if d.get("kind") == "engine_schema"]

    # Honest distinct-session accounting: all real files are AAPL 2024-01-03,
    # 09:30-10:30 ET (== 14:30-15:30 UTC) - ONE real session at two resolutions.
    distinct_symbols = sorted({d.get("symbol", "AAPL") for d in present_real})
    distinct_sessions = ["AAPL 2024-01-03 09:30-10:30 America/New_York (== 14:30-15:30 UTC)"]

    total_real_quote_events = sum(d.get("quote_count", 0) for d in engine_ready)
    largest = max((d.get("data_rows", 0) for d in engine_ready), default=0)

    payload = {
        "_meta": H.new_meta(
            "dataset_inventory",
            "PYTHONPATH=build python3 benchmarks/dataset_inventory.py",
            extra={
                "category": "OBSERVED (real historical data) with provenance; validation via real CsvMarketSource",
                "scale_honesty": (
                    "All real data is ONE symbol / ONE trading hour / ONE day, from ONE raw "
                    "Alpaca IEX capture, at two normalization resolutions. Do not report as "
                    "multiple independent sessions."
                ),
            },
        ),
        "scale_summary": {
            "distinct_real_symbols": len(distinct_symbols),
            "symbols": distinct_symbols,
            "distinct_real_sessions": len(distinct_sessions),
            "sessions": distinct_sessions,
            "engine_ready_real_files": len(engine_ready),
            "largest_engine_ready_rows": largest,
            "total_engine_ready_quote_events": total_real_quote_events,
            "trade_data_available": False,
            "limitation": (
                "Real historical coverage is intentionally small (free Alpaca IEX, quote-only, "
                "one AAPL session). The benchmark infrastructure accepts additional datasets "
                "with no redesign - add engine-schema CSVs (+ manifests) via "
                "scripts/build_dataset_manifest.py / python/alpaca_ingest.py and re-run."
            ),
        },
        "real_datasets": real,
        "synthetic_datasets": synthetic,
    }
    out = H.write_json("dataset_inventory.json", payload)
    print(f"real engine-ready files: {len(engine_ready)}, largest {H.human_int(largest)} rows, "
          f"symbols={distinct_symbols}, sessions={len(distinct_sessions)}")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
