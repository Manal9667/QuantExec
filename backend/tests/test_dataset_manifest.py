"""Tests for scripts/build_dataset_manifest.py (Step 2).

Run with: python3 -m unittest discover -s backend/tests -v
(Same discovery root as the rest of the backend suite; this module reaches
into scripts/ via sys.path rather than moving the tool, since it's a
repo-wide CLI tool, not backend-specific code.)
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from build_dataset_manifest import (  # noqa: E402
    DatasetValidationError,
    build_manifest,
    validate_csv,
)


class _Args:
    """Minimal stand-in for argparse.Namespace in tests."""

    def __init__(self, **kwargs):
        defaults = dict(
            data_type="synthetic",
            provider=None,
            source_url=None,
            license=None,
            timezone=None,
            symbol=None,
            venue=None,
            resolution=None,
            notes=None,
        )
        defaults.update(kwargs)
        self.__dict__.update(defaults)


def _write(tmpdir: str, name: str, content: str) -> Path:
    path = Path(tmpdir) / name
    path.write_text(content)
    return path


VALID_CSV = (
    "timestamp_ms,last,bid,ask,bid_size,ask_size,volume\n"
    "1000,100.0,99.9,100.1,500,500,1000\n"
    "2000,100.2,100.0,100.3,500,500,1200\n"
    "3000,100.4,100.2,100.5,500,500,1300\n"
)


class ValidateCsvTests(unittest.TestCase):
    def test_valid_file_has_no_issues(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write(d, "good.csv", VALID_CSV)
            report = validate_csv(path)
            self.assertTrue(report.ok)
            self.assertEqual(report.valid_row_count, 3)

    def test_missing_column_is_file_level_issue(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write(d, "bad.csv", "timestamp_ms,last,bid,ask\n1000,100,99.9,100.1\n")
            report = validate_csv(path)
            self.assertFalse(report.ok)
            self.assertEqual(report.issues[0].kind, "missing_columns")

    def test_duplicate_timestamp_detected(self):
        csv_text = (
            "timestamp_ms,last,bid,ask,bid_size,ask_size,volume\n"
            "1000,100.0,99.9,100.1,500,500,1000\n"
            "1000,100.1,99.9,100.1,500,500,1000\n"
        )
        with tempfile.TemporaryDirectory() as d:
            path = _write(d, "dup.csv", csv_text)
            report = validate_csv(path)
            kinds = {i.kind for i in report.issues}
            self.assertIn("duplicate_timestamp", kinds)

    def test_non_monotonic_timestamp_detected(self):
        csv_text = (
            "timestamp_ms,last,bid,ask,bid_size,ask_size,volume\n"
            "2000,100.0,99.9,100.1,500,500,1000\n"
            "1000,100.1,99.9,100.1,500,500,1000\n"
        )
        with tempfile.TemporaryDirectory() as d:
            path = _write(d, "nonmono.csv", csv_text)
            report = validate_csv(path)
            kinds = {i.kind for i in report.issues}
            self.assertIn("non_monotonic_timestamp", kinds)

    def test_invalid_bid_ask_detected(self):
        csv_text = (
            "timestamp_ms,last,bid,ask,bid_size,ask_size,volume\n"
            "1000,100.0,100.5,100.1,500,500,1000\n"
        )
        with tempfile.TemporaryDirectory() as d:
            path = _write(d, "crossed.csv", csv_text)
            report = validate_csv(path)
            kinds = {i.kind for i in report.issues}
            self.assertIn("invalid_bid_ask", kinds)

    def test_negative_quantity_detected(self):
        csv_text = (
            "timestamp_ms,last,bid,ask,bid_size,ask_size,volume\n"
            "1000,100.0,99.9,100.1,-500,500,1000\n"
        )
        with tempfile.TemporaryDirectory() as d:
            path = _write(d, "negqty.csv", csv_text)
            report = validate_csv(path)
            kinds = {i.kind for i in report.issues}
            self.assertIn("negative_quantity", kinds)

    def test_non_finite_value_detected(self):
        csv_text = (
            "timestamp_ms,last,bid,ask,bid_size,ask_size,volume\n"
            "1000,NaN,99.9,100.1,500,500,1000\n"
        )
        with tempfile.TemporaryDirectory() as d:
            path = _write(d, "nan.csv", csv_text)
            report = validate_csv(path)
            kinds = {i.kind for i in report.issues}
            self.assertIn("non_finite_value", kinds)

    def test_multiple_issues_all_reported_not_just_first(self):
        csv_text = (
            "timestamp_ms,last,bid,ask,bid_size,ask_size,volume\n"
            "1000,100.0,99.9,100.1,500,500,1000\n"
            "1000,100.1,99.9,100.1,-1,500,1000\n"
        )
        with tempfile.TemporaryDirectory() as d:
            path = _write(d, "multi.csv", csv_text)
            report = validate_csv(path)
            kinds = {i.kind for i in report.issues}
            self.assertIn("duplicate_timestamp", kinds)
            self.assertIn("negative_quantity", kinds)
            self.assertGreaterEqual(len(report.issues), 2)


class BuildManifestTests(unittest.TestCase):
    def test_valid_synthetic_dataset_produces_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write(d, "good.csv", VALID_CSV)
            manifest = build_manifest(path, _Args(data_type="synthetic", symbol="SYN"))
            self.assertEqual(manifest["row_count"], 3)
            self.assertEqual(manifest["data_type"], "synthetic")
            self.assertEqual(len(manifest["sha256"]), 64)
            self.assertEqual(manifest["start_timestamp_ms"], 1000)
            self.assertEqual(manifest["end_timestamp_ms"], 3000)

    def test_invalid_dataset_raises(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write(
                d,
                "bad.csv",
                "timestamp_ms,last,bid,ask,bid_size,ask_size,volume\n"
                "1000,100.0,100.5,100.1,500,500,1000\n",
            )
            with self.assertRaises(DatasetValidationError):
                build_manifest(path, _Args(data_type="synthetic"))

    def test_historical_without_provenance_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write(d, "good.csv", VALID_CSV)
            with self.assertRaises(DatasetValidationError):
                build_manifest(path, _Args(data_type="historical"))

    def test_historical_with_full_provenance_is_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write(d, "good.csv", VALID_CSV)
            manifest = build_manifest(
                path,
                _Args(
                    data_type="historical",
                    provider="Example Data Co",
                    source_url="https://example.com/data.csv",
                    license="internal research use only",
                    timezone="America/New_York",
                    symbol="AAPL",
                    venue="XNAS",
                ),
            )
            self.assertEqual(manifest["data_type"], "historical")
            self.assertEqual(manifest["provider"], "Example Data Co")

    def test_checksum_is_stable_across_calls(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write(d, "good.csv", VALID_CSV)
            m1 = build_manifest(path, _Args(data_type="synthetic"))
            m2 = build_manifest(path, _Args(data_type="synthetic"))
            self.assertEqual(m1["sha256"], m2["sha256"])


if __name__ == "__main__":
    unittest.main()
