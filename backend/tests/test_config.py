"""
Tests for the backend configuration layer (spec section 41).

These are pure-logic tests - they only exercise backend/config.py and the
CostConfig defaults in schemas.py, so they do NOT require the compiled
`executor` extension (unlike test_api_reproducibility.py).

Run with:
    PYTHONPATH=backend python3 -m unittest discover -s backend/tests -v
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import config  # noqa: E402


class ConfigTests(unittest.TestCase):
    # Environment variables this suite may set; saved/restored around each
    # test so tests never leak configuration into one another.
    MANAGED = [
        "QUANTEXEC_DB_PATH",
        "QUANTEXEC_CORS_ORIGINS",
        "QUANTEXEC_API_HOST",
        "QUANTEXEC_API_PORT",
        "QUANTEXEC_LOG_LEVEL",
        "QUANTEXEC_COMMISSION_BPS",
        "QUANTEXEC_EXCHANGE_FEE_BPS",
        "QUANTEXEC_FIXED_FEE_PER_FILL",
        "QUANTEXEC_ENV_FILE",
    ]

    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in self.MANAGED}
        for k in self.MANAGED:
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        # Leave the module singleton back at the real default configuration.
        config.settings = config.load_settings()

    def test_defaults_match_previous_hardcoded_values(self):
        s = config.load_settings()
        self.assertEqual(s.cors_origins, ["*"])
        self.assertEqual(s.api_host, "127.0.0.1")
        self.assertEqual(s.api_port, 8000)
        self.assertEqual(s.log_level, "INFO")
        self.assertEqual(s.default_commission_bps, 0.0)
        self.assertEqual(s.default_exchange_fee_bps, 0.0)
        self.assertEqual(s.default_fixed_fee_per_fill, 0.0)
        self.assertEqual(s.db_path.name, "experiments.db")

    def test_env_overrides_are_parsed(self):
        os.environ["QUANTEXEC_DB_PATH"] = "/tmp/quantexec_test.db"
        os.environ["QUANTEXEC_CORS_ORIGINS"] = "http://localhost:5173, https://app.example.com"
        os.environ["QUANTEXEC_API_PORT"] = "9000"
        os.environ["QUANTEXEC_LOG_LEVEL"] = "debug"
        os.environ["QUANTEXEC_COMMISSION_BPS"] = "1.5"
        s = config.load_settings()
        self.assertEqual(s.db_path, Path("/tmp/quantexec_test.db"))
        self.assertEqual(s.cors_origins, ["http://localhost:5173", "https://app.example.com"])
        self.assertEqual(s.api_port, 9000)
        self.assertEqual(s.log_level, "DEBUG")  # normalised to upper-case
        self.assertEqual(s.default_commission_bps, 1.5)

    def test_invalid_numbers_fall_back_to_default(self):
        os.environ["QUANTEXEC_API_PORT"] = "not-a-number"
        os.environ["QUANTEXEC_COMMISSION_BPS"] = ""
        s = config.load_settings()
        self.assertEqual(s.api_port, 8000)
        self.assertEqual(s.default_commission_bps, 0.0)

    def test_empty_cors_falls_back_to_wildcard(self):
        os.environ["QUANTEXEC_CORS_ORIGINS"] = " , , "
        self.assertEqual(config.load_settings().cors_origins, ["*"])

    def test_dotenv_file_is_loaded_but_real_env_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text(
                "# a comment\n"
                "QUANTEXEC_API_PORT=7777\n"
                'QUANTEXEC_LOG_LEVEL="warning"\n'
                "export QUANTEXEC_EXCHANGE_FEE_BPS=0.3\n"
                "malformed line without equals\n"
            )
            os.environ["QUANTEXEC_ENV_FILE"] = str(env_file)
            # A real environment variable must beat the .env file value.
            os.environ["QUANTEXEC_API_PORT"] = "8123"
            s = config.load_settings()
            self.assertEqual(s.api_port, 8123)  # real env wins
            self.assertEqual(s.log_level, "WARNING")  # from .env, quotes stripped
            self.assertEqual(s.default_exchange_fee_bps, 0.3)  # 'export ' prefix handled

    def test_cost_config_defaults_follow_settings(self):
        os.environ["QUANTEXEC_COMMISSION_BPS"] = "2.5"
        os.environ["QUANTEXEC_FIXED_FEE_PER_FILL"] = "0.75"
        config.settings = config.load_settings()
        import schemas

        cost = schemas.CostConfig()
        self.assertEqual(cost.commission_bps, 2.5)
        self.assertEqual(cost.fixed_fee_per_fill, 0.75)
        # An explicit value in the request still overrides the configured default.
        self.assertEqual(schemas.CostConfig(commission_bps=0.1).commission_bps, 0.1)


if __name__ == "__main__":
    unittest.main()
