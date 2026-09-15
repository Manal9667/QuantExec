"""
Tests for backend/dataset_utils.py.

Uses only stdlib `unittest` and `tempfile` - no pytest, no pydantic, no
pybind11 - specifically so these tests can run in any environment that
merely has Python 3, including one where the C++ extension hasn't been
built yet and no Python packages have been pip-installed. This directly
targets a gap the project's own assessment named: "no automated tests
covering ... missing datasets ... malformed configurations ... path
validation."

Run with:
    python3 -m unittest backend.tests.test_dataset_utils -v
or, from backend/:
    python3 -m unittest tests.test_dataset_utils -v
"""

from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dataset_utils import (
    DatasetError,
    compute_dataset_stats,
    list_dataset_files,
    resolve_dataset_path,
    resolve_prices,
)


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


class ResolveDatasetPathTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.tmp.name)
        (self.repo_root / "datasets").mkdir()
        self.dataset_file = self.repo_root / "datasets" / "sample.csv"
        self.dataset_file.write_text("timestamp_ms,bid,ask\n1,99.0,101.0\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_resolves_a_valid_relative_path(self):
        resolved = resolve_dataset_path(self.repo_root, "datasets/sample.csv")
        self.assertEqual(resolved, self.dataset_file.resolve())

    def test_missing_dataset_raises_dataset_error(self):
        with self.assertRaises(DatasetError):
            resolve_dataset_path(self.repo_root, "datasets/does_not_exist.csv")

    def test_empty_dataset_string_raises_dataset_error(self):
        with self.assertRaises(DatasetError):
            resolve_dataset_path(self.repo_root, "")

    def test_path_traversal_outside_repo_root_is_rejected(self):
        outside = self.repo_root.parent / "outside_secret.csv"
        outside.write_text("secret\n")
        try:
            with self.assertRaises(DatasetError):
                resolve_dataset_path(self.repo_root, "../outside_secret.csv")
        finally:
            outside.unlink()

    def test_absolute_path_traversal_is_also_rejected(self):
        outside = self.repo_root.parent / "outside_secret2.csv"
        outside.write_text("secret\n")
        try:
            with self.assertRaises(DatasetError):
                resolve_dataset_path(self.repo_root, str(outside))
        finally:
            outside.unlink()

    def test_directory_path_is_rejected(self):
        with self.assertRaises(DatasetError):
            resolve_dataset_path(self.repo_root, "datasets")


class ResolvePricesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "data.csv"

    def tearDown(self):
        self.tmp.cleanup()

    def test_explicit_prices_are_returned_unchanged(self):
        _write_csv(self.path, [{"bid": "10", "ask": "11"}], ["bid", "ask"])
        limit, arrival = resolve_prices(self.path, 50.0, 25.0)
        self.assertEqual((limit, arrival), (50.0, 25.0))

    def test_defaults_are_derived_from_first_row_when_unset(self):
        _write_csv(self.path, [{"bid": "100.0", "ask": "100.2"}, {"bid": "999", "ask": "999"}],
                   ["bid", "ask"])
        limit, arrival = resolve_prices(self.path, None, None)
        self.assertAlmostEqual(arrival, 100.1)  # mid of first row only, not later rows
        self.assertAlmostEqual(limit, 100.2 * 1.02)

    def test_only_missing_field_is_defaulted(self):
        _write_csv(self.path, [{"bid": "10.0", "ask": "10.4"}], ["bid", "ask"])
        limit, arrival = resolve_prices(self.path, 500.0, None)
        self.assertEqual(limit, 500.0)  # explicit value untouched
        self.assertAlmostEqual(arrival, 10.2)  # only arrival_price defaulted

    def test_empty_dataset_raises_dataset_error(self):
        _write_csv(self.path, [], ["bid", "ask"])
        with self.assertRaises(DatasetError):
            resolve_prices(self.path, None, None)

    def test_missing_required_column_raises_dataset_error(self):
        _write_csv(self.path, [{"bid": "10.0"}], ["bid"])  # no 'ask' column at all
        with self.assertRaises(DatasetError):
            resolve_prices(self.path, None, None)

    def test_non_numeric_price_raises_dataset_error(self):
        _write_csv(self.path, [{"bid": "not-a-number", "ask": "10.0"}], ["bid", "ask"])
        with self.assertRaises(DatasetError):
            resolve_prices(self.path, None, None)


class ComputeDatasetStatsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "data.csv"

    def tearDown(self):
        self.tmp.cleanup()

    def test_total_bar_volume_is_summed_across_rows(self):
        _write_csv(
            self.path,
            [
                {"bid": "100.0", "ask": "100.1", "bar_volume": "10"},
                {"bid": "100.0", "ask": "100.1", "bar_volume": "20"},
                {"bid": "100.0", "ask": "100.1", "bar_volume": "30"},
            ],
            ["bid", "ask", "bar_volume"],
        )
        stats = compute_dataset_stats(self.path)
        self.assertEqual(stats.total_bar_volume, 60)
        self.assertEqual(stats.row_count, 3)

    def test_falls_back_to_volume_column_when_bar_volume_absent(self):
        _write_csv(
            self.path,
            [{"bid": "100.0", "ask": "100.1", "volume": "500"}],
            ["bid", "ask", "volume"],
        )
        stats = compute_dataset_stats(self.path)
        self.assertEqual(stats.total_bar_volume, 500)

    def test_constant_mid_price_has_zero_volatility(self):
        rows = [{"bid": "100.0", "ask": "100.0", "bar_volume": "1"} for _ in range(5)]
        _write_csv(self.path, rows, ["bid", "ask", "bar_volume"])
        stats = compute_dataset_stats(self.path)
        self.assertEqual(stats.mid_price_volatility, 0.0)

    def test_volatility_is_positive_when_mid_price_moves(self):
        rows = [
            {"bid": "99.0", "ask": "101.0", "bar_volume": "1"},
            {"bid": "104.0", "ask": "106.0", "bar_volume": "1"},
            {"bid": "94.0", "ask": "96.0", "bar_volume": "1"},
        ]
        _write_csv(self.path, rows, ["bid", "ask", "bar_volume"])
        stats = compute_dataset_stats(self.path)
        self.assertGreater(stats.mid_price_volatility, 0.0)

    def test_single_row_has_zero_volatility_not_an_error(self):
        _write_csv(self.path, [{"bid": "100.0", "ask": "100.2", "bar_volume": "5"}],
                   ["bid", "ask", "bar_volume"])
        stats = compute_dataset_stats(self.path)
        self.assertEqual(stats.mid_price_volatility, 0.0)

    def test_empty_dataset_raises_dataset_error(self):
        _write_csv(self.path, [], ["bid", "ask", "bar_volume"])
        with self.assertRaises(DatasetError):
            compute_dataset_stats(self.path)

    def test_malformed_row_is_skipped_not_fatal(self):
        rows = [
            {"bid": "100.0", "ask": "100.2", "bar_volume": "10"},
            {"bid": "garbage", "ask": "100.2", "bar_volume": "not-a-number"},
            {"bid": "100.1", "ask": "100.3", "bar_volume": "20"},
        ]
        _write_csv(self.path, rows, ["bid", "ask", "bar_volume"])
        stats = compute_dataset_stats(self.path)
        # The malformed row contributes nothing; the two good rows still count.
        self.assertEqual(stats.total_bar_volume, 30)
        self.assertEqual(stats.row_count, 3)


class ListDatasetFilesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.tmp.name)
        (self.repo_root / "datasets").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_lists_csv_files_relative_to_repo_root(self):
        (self.repo_root / "datasets" / "a.csv").write_text("x\n")
        (self.repo_root / "datasets" / "b.csv").write_text("x\n")
        (self.repo_root / "datasets" / "notes.txt").write_text("not a csv\n")
        found = list_dataset_files(self.repo_root)
        self.assertEqual(found, ["datasets/a.csv", "datasets/b.csv"])

    def test_missing_datasets_directory_returns_empty_list(self):
        empty_root = Path(tempfile.mkdtemp())
        try:
            self.assertEqual(list_dataset_files(empty_root), [])
        finally:
            import shutil
            shutil.rmtree(empty_root)


if __name__ == "__main__":
    unittest.main()