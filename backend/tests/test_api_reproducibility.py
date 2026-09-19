"""
API-level tests for Step 6 (backend reproducibility): structured
validation errors, dataset checksums, and duplicate-submission handling.

Unlike test_dataset_utils.py / test_dataset_manifest.py, this module does
need the full stack (the compiled `executor` extension, pydantic,
FastAPI, httpx), because it's testing main.py's actual request handling,
not pure logic. If the native extension hasn't been built yet, these
tests skip themselves with a clear reason instead of failing the whole
suite - consistent with this project's existing practice of keeping
pure-logic tests (test_dataset_utils.py) independent of the C++ build.

Run with:
    pip install -r backend/requirements.txt -r backend/requirements-dev.txt
    PYTHONPATH=build python3 -m unittest discover -s backend/tests -v
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

try:
    import executor  # noqa: F401  (just probing importability)
    from fastapi.testclient import TestClient

    _IMPORT_ERROR = None
except Exception as exc:  # noqa: BLE001
    _IMPORT_ERROR = exc


def _make_client_and_reset_db():
    """Fresh FastAPI app + a throwaway SQLite file per test, so tests don't
    see each other's experiments (in particular, the duplicate-submission
    test would be meaningless against a database other tests already
    populated)."""
    import db as db_module
    import main as main_module

    tmp_db = Path(tempfile.mkdtemp()) / "test_experiments.db"
    db_module.DEFAULT_DB_PATH = tmp_db
    # Force a fresh per-thread connection against the new path.
    db_module._local.conn = None
    return TestClient(main_module.app)


@unittest.skipIf(_IMPORT_ERROR is not None, f"Full stack not available: {_IMPORT_ERROR}")
class ExperimentApiTests(unittest.TestCase):
    def setUp(self):
        self.client = _make_client_and_reset_db()
        self.base_request = {
            "symbol": "SYN",
            "dataset": "datasets/sample_synthetic.csv",
            "side": "BUY",
            "quantity": 200,
            "strategy": "TWAP",
            "slices": 3,
        }

    def test_valid_experiment_returns_dataset_checksum(self):
        resp = self.client.post("/experiments", json=self.base_request)
        self.assertEqual(resp.status_code, 201, resp.text)
        body = resp.json()
        self.assertEqual(body["status"], "completed")
        self.assertIsNotNone(body["dataset_checksum"])
        self.assertEqual(len(body["dataset_checksum"]), 64)
        self.assertIsNotNone(body["config_hash"])
        self.assertIsNone(body["duplicate_of"])

    def test_missing_dataset_returns_structured_error(self):
        req = dict(self.base_request, dataset="datasets/does_not_exist.csv")
        resp = self.client.post("/experiments", json=req)
        self.assertEqual(resp.status_code, 400)
        body = resp.json()
        self.assertEqual(body["error_type"], "dataset_not_found")
        self.assertIn("does_not_exist.csv", body["detail"])

    def test_path_traversal_returns_403_structured_error(self):
        req = dict(self.base_request, dataset="../../etc/passwd")
        resp = self.client.post("/experiments", json=req)
        self.assertEqual(resp.status_code, 403)
        body = resp.json()
        self.assertEqual(body["error_type"], "dataset_path_unsafe")

    def test_invalid_config_returns_422_from_pydantic(self):
        # Missing 'slices', required for TWAP - caught by ExperimentRequest's
        # own validator before anything touches the engine.
        req = dict(self.base_request)
        del req["slices"]
        resp = self.client.post("/experiments", json=req)
        self.assertEqual(resp.status_code, 422)

    def test_duplicate_submission_reuses_existing_result(self):
        first = self.client.post("/experiments", json=self.base_request)
        self.assertEqual(first.status_code, 201)
        first_id = first.json()["id"]

        second = self.client.post("/experiments", json=self.base_request)
        self.assertEqual(second.status_code, 201)
        second_body = second.json()

        self.assertEqual(second_body["duplicate_of"], first_id)
        self.assertEqual(second_body["id"], first_id)
        # Same underlying experiment - metrics must be identical, not just
        # "close" (BASELINE.md already proved the engine is deterministic;
        # this proves the API layer doesn't quietly re-run and diverge).
        self.assertEqual(second_body["metrics"], first.json()["metrics"])

    def test_allow_duplicate_forces_a_fresh_run(self):
        first = self.client.post("/experiments", json=self.base_request)
        first_id = first.json()["id"]

        second = self.client.post("/experiments?allow_duplicate=true", json=self.base_request)
        self.assertEqual(second.status_code, 201)
        self.assertIsNone(second.json()["duplicate_of"])
        self.assertNotEqual(second.json()["id"], first_id)
        # Still deterministic - a fresh run of an identical config produces
        # identical metrics, just under a new experiment id.
        self.assertEqual(second.json()["metrics"], first.json()["metrics"])

    def test_different_quantity_is_not_treated_as_duplicate(self):
        first = self.client.post("/experiments", json=self.base_request)
        different = dict(self.base_request, quantity=999)
        second = self.client.post("/experiments", json=different)
        self.assertIsNone(second.json()["duplicate_of"])
        self.assertNotEqual(first.json()["id"], second.json()["id"])

    def test_cancel_nonexistent_experiment_returns_404(self):
        resp = self.client.delete("/experiments/999999")
        self.assertEqual(resp.status_code, 404)

    def test_cancel_completed_experiment_returns_409(self):
        first = self.client.post("/experiments", json=self.base_request)
        exp_id = first.json()["id"]
        resp = self.client.delete(f"/experiments/{exp_id}")
        self.assertEqual(resp.status_code, 409)

    def test_directory_as_dataset_returns_structured_error_not_500(self):
        resp = self.client.post("/experiments", json=dict(self.base_request, dataset="datasets"))
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error_type"], "dataset_not_found")

    def test_empty_dataset_returns_structured_error_and_row_is_not_left_running(self):
        import experiment_service

        empty = Path(tempfile.mkdtemp()) / "empty.csv"
        empty.write_text("timestamp_ms,last,bid,ask,bid_size,ask_size,volume\n")
        # resolve_dataset_path only accepts paths inside the repo, so point
        # the service's REPO_ROOT at the temp dir for this one request.
        original_root = experiment_service.REPO_ROOT
        experiment_service.REPO_ROOT = empty.parent
        try:
            resp = self.client.post("/experiments", json=dict(self.base_request, dataset="empty.csv"))
        finally:
            experiment_service.REPO_ROOT = original_root
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error_type"], "dataset_unloadable")
        statuses = {row["status"] for row in self.client.get("/experiments").json()}
        self.assertNotIn("running", statuses)
        self.assertNotIn("queued", statuses)

    def test_unexpected_engine_failure_marks_experiment_failed(self):
        import main as main_module

        original = main_module.run_experiment
        main_module.run_experiment = lambda req: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            resp = self.client.post("/experiments", json=self.base_request)
        finally:
            main_module.run_experiment = original
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.json()["error_type"], "engine_error")
        rows = self.client.get("/experiments").json()
        self.assertEqual([r["status"] for r in rows], ["failed"])

    def test_list_limit_is_bounded(self):
        self.assertEqual(self.client.get("/experiments?limit=0").status_code, 422)
        self.assertEqual(self.client.get("/experiments?limit=100000").status_code, 422)

    def test_experiment_list_includes_dataset_checksum(self):
        self.client.post("/experiments", json=self.base_request)
        resp = self.client.get("/experiments")
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()
        self.assertTrue(len(rows) >= 1)
        self.assertIsNotNone(rows[0]["dataset_checksum"])


if __name__ == "__main__":
    unittest.main()
