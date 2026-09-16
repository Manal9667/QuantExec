#!/usr/bin/env python3
"""
Dataset validation + manifest generator (Step 2).

This is the gate between "a file someone gave us" and "a dataset the engine
is allowed to load". It is intentionally independent of the C++ CsvMarketSource
loader (src/market_data.cpp): that loader already refuses obviously-bad files,
but it fails *silently* (an empty/unloaded source) so a bad file just looks
like "no data" three layers away from where the problem actually is. This
script's job is to fail loudly, in one place, with a specific reason, before
a file is ever treated as a usable dataset - and to produce a manifest that
records exactly what the file is and where it came from.

Usage:
    python3 scripts/build_dataset_manifest.py <csv_path> \
        --provider "Example Data Co" \
        --source-url "https://example.com/downloads/AAPL_2024-01-05.csv" \
        --license "Redistribution not permitted; single-seat internal research use" \
        --timezone "America/New_York" \
        --symbol AAPL --venue XNAS \
        --resolution "trade+quote, top-of-book only (no L2 depth)" \
        --data-type historical \
        --notes "Every row here is exactly as delivered by the provider; no field was invented."

Run with no --provider/--source-url/--license for the bundled synthetic
fixture; the script will refuse to label a dataset "historical" without
those three fields (see _require_provenance below).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

REQUIRED_COLUMNS = ["timestamp_ms", "last", "bid", "ask", "bid_size", "ask_size", "volume"]
OPTIONAL_COLUMNS = ["bar_volume", "bid_depth", "ask_depth"]
SCHEMA_VERSION = "1.0"


class DatasetValidationError(ValueError):
    """Raised for any row- or file-level problem. Carries every problem
    found, not just the first, so a reviewer gets the whole picture in one
    run instead of playing whack-a-mole."""


@dataclass
class ValidationIssue:
    row: Optional[int]  # None = file-level issue
    kind: str
    detail: str


@dataclass
class ValidationReport:
    issues: list[ValidationIssue] = field(default_factory=list)
    row_count: int = 0
    valid_row_count: int = 0

    @property
    def ok(self) -> bool:
        return not self.issues

    def add(self, kind: str, detail: str, row: Optional[int] = None) -> None:
        self.issues.append(ValidationIssue(row=row, kind=kind, detail=detail))


def _is_finite_number(value: str) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def validate_csv(path: Path) -> ValidationReport:
    """Runs every check listed in the Step 2 spec:
    missing columns, malformed rows, duplicate timestamps, non-monotonic
    timestamps, invalid bid/ask relationships, negative prices/quantities,
    non-finite values. Does not stop at the first error - a dataset with 40
    bad rows should report 40 problems, not 1.
    """
    report = ValidationReport()

    with open(path, newline="") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            report.add("empty_file", "File has no header row at all")
            return report

        missing = [c for c in REQUIRED_COLUMNS if c not in header]
        if missing:
            report.add("missing_columns", f"Missing required column(s): {missing}")
            return report  # Can't meaningfully validate rows without columns

        col_index = {name: i for i, name in enumerate(header)}
        seen_timestamps: set[int] = set()
        last_timestamp: Optional[int] = None

        for row_number, row in enumerate(reader, start=2):  # header is row 1
            report.row_count += 1
            if not row or all(cell.strip() == "" for cell in row):
                continue  # blank line, not a malformed row

            def field(name: str) -> str:
                idx = col_index[name]
                return row[idx] if idx < len(row) else ""

            row_ok = True

            if len(row) < len(header) - len(OPTIONAL_COLUMNS):
                report.add("malformed_row", f"Row has {len(row)} fields, header has {len(header)}", row_number)
                continue

            try:
                timestamp = int(field("timestamp_ms"))
            except ValueError:
                report.add("malformed_row", f"timestamp_ms '{field('timestamp_ms')}' is not an integer", row_number)
                row_ok = False
                timestamp = None

            numeric_fields = {}
            for col in ("last", "bid", "ask"):
                val = _is_finite_number(field(col))
                if val is None:
                    report.add("non_finite_value", f"Column '{col}' is not a finite number: '{field(col)}'", row_number)
                    row_ok = False
                else:
                    numeric_fields[col] = val

            for col in ("bid_size", "ask_size", "volume"):
                raw = field(col)
                try:
                    val = int(raw)
                except ValueError:
                    report.add("malformed_row", f"Column '{col}' is not an integer: '{raw}'", row_number)
                    row_ok = False
                    continue
                if val < 0:
                    report.add("negative_quantity", f"Column '{col}' is negative: {val}", row_number)
                    row_ok = False

            for col in ("last", "bid", "ask"):
                if col in numeric_fields and numeric_fields[col] < 0:
                    report.add("negative_price", f"Column '{col}' is negative: {numeric_fields[col]}", row_number)
                    row_ok = False

            if "bid" in numeric_fields and "ask" in numeric_fields:
                if numeric_fields["bid"] > numeric_fields["ask"]:
                    report.add(
                        "invalid_bid_ask",
                        f"bid ({numeric_fields['bid']}) > ask ({numeric_fields['ask']})",
                        row_number,
                    )
                    row_ok = False

            if timestamp is not None:
                if timestamp in seen_timestamps:
                    report.add("duplicate_timestamp", f"timestamp_ms {timestamp} appears more than once", row_number)
                    row_ok = False
                seen_timestamps.add(timestamp)
                if last_timestamp is not None and timestamp <= last_timestamp:
                    report.add(
                        "non_monotonic_timestamp",
                        f"timestamp_ms {timestamp} is not strictly greater than previous {last_timestamp}",
                        row_number,
                    )
                    row_ok = False
                last_timestamp = timestamp

            if row_ok:
                report.valid_row_count += 1

    return report


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _require_provenance(args: argparse.Namespace) -> None:
    """A dataset cannot be labeled 'historical' without saying where it came
    from. This is the single biggest failure mode Step 2 is trying to
    prevent: a file quietly treated as real-market evidence when nobody can
    actually say where it came from."""
    if args.data_type == "historical":
        missing = [
            name
            for name, val in (
                ("--provider", args.provider),
                ("--source-url", args.source_url),
                ("--license", args.license),
                ("--timezone", args.timezone),
            )
            if not val
        ]
        if missing:
            raise DatasetValidationError(
                "Refusing to manifest this as historical data without provenance. "
                f"Missing: {', '.join(missing)}. Use --data-type synthetic for "
                "generated/fixture data instead."
            )


def build_manifest(path: Path, args: argparse.Namespace) -> dict:
    _require_provenance(args)
    report = validate_csv(path)
    if not report.ok:
        lines = [f"  row {i.row if i.row else '-'}: [{i.kind}] {i.detail}" for i in report.issues]
        raise DatasetValidationError(
            f"{len(report.issues)} validation issue(s) found in {path}:\n" + "\n".join(lines)
        )

    checksum = sha256_of(path)
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    start_ts = int(rows[0]["timestamp_ms"])
    end_ts = int(rows[-1]["timestamp_ms"])

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "file": str(path.as_posix()),
        "sha256": checksum,
        "row_count": len(rows),
        "columns": list(rows[0].keys()),
        "start_timestamp_ms": start_ts,
        "end_timestamp_ms": end_ts,
        "data_type": args.data_type,          # "synthetic" | "historical"
        "provider": args.provider,
        "source_url": args.source_url,
        "license": args.license,
        "timezone": args.timezone,
        "symbol": args.symbol,
        "venue": args.venue,
        "resolution": args.resolution,
        "notes": args.notes,
    }
    return manifest


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--data-type", choices=["synthetic", "historical"], default="synthetic")
    parser.add_argument("--provider", default=None, help="Who supplied the data, e.g. 'Databento', 'IEX Cloud'")
    parser.add_argument("--source-url", default=None, help="Exact URL or acquisition method")
    parser.add_argument("--license", default=None, help="Usage/redistribution restrictions")
    parser.add_argument("--timezone", default=None, help="Timezone of the source timestamps before conversion")
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--venue", default=None)
    parser.add_argument("--resolution", default=None, help="e.g. 'trade+quote', 'L2 snapshot every 100ms'")
    parser.add_argument("--notes", default=None)
    parser.add_argument("-o", "--output", type=Path, default=None, help="Where to write the manifest JSON")
    args = parser.parse_args(argv)

    try:
        manifest = build_manifest(args.csv_path, args)
    except DatasetValidationError as exc:
        print(f"REJECTED: {exc}", file=sys.stderr)
        return 1

    output_path = args.output or args.csv_path.with_suffix(".manifest.json")
    output_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"OK: wrote manifest to {output_path}")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
