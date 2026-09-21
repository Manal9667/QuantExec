"""
LIVE smoke test for Alpaca historical ingestion. HITS THE REAL API.

This is intentionally SEPARATE from the offline suite. It is skipped unless
Alpaca credentials are present AND it is explicitly opted into, so the normal
test suite stays fully offline and never depends on Alpaca being reachable.

Enable it with BOTH:
    * ALPACA_API_KEY / ALPACA_SECRET_KEY available (repo-root .env or env vars)
    * QUANTEXEC_LIVE=1

Run:
    # PowerShell
    $env:QUANTEXEC_LIVE="1"; $env:PYTHONPATH="build/Release"
    python -m pytest python/test_alpaca_live_smoke.py -v -s

    # or as a plain script
    python python/test_alpaca_live_smoke.py

It makes ONE tiny request (AAPL, a one-minute window, IEX) and asserts the
pipeline produces a CsvMarketSource-loadable dataset. It never prints
credentials.
"""

import os
import sys
import tempfile
from pathlib import Path

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_THIS_DIR)
for _p in (_REPO_ROOT, _THIS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)
for _b in (os.path.join(_REPO_ROOT, "build", "Release"), os.path.join(_REPO_ROOT, "build")):
    if os.path.exists(_b) and _b not in sys.path:
        sys.path.insert(0, _b)

try:
    from python.alpaca_ingest import ingest, AlpacaCredentials, AlpacaAuthError
except ImportError:
    from alpaca_ingest import ingest, AlpacaCredentials, AlpacaAuthError  # type: ignore


def _live_enabled() -> bool:
    if os.environ.get("QUANTEXEC_LIVE") != "1":
        return False
    try:
        AlpacaCredentials.from_env()
    except AlpacaAuthError:
        return False
    return True


def run_live_smoke() -> None:
    from executor import CsvMarketSource

    with tempfile.TemporaryDirectory() as tmp:
        result = ingest(
            "AAPL",
            "2024-01-03T14:30:00Z",
            "2024-01-03T14:31:00Z",
            feed="iex",
            data_root=Path(tmp),
        )
        assert result.stats.records_downloaded > 0, "live request returned no quotes"
        assert os.path.exists(result.csv_path)
        source = CsvMarketSource(result.csv_path)
        assert source.ok(), "C++ CsvMarketSource rejected the live dataset"
        print(f"live smoke OK: downloaded={result.stats.records_downloaded} "
              f"valid={result.stats.records_valid} rows={result.rows_written}")


# --- pytest entry point (auto-skips) ----------------------------------------
try:
    import pytest

    @pytest.mark.skipif(not _live_enabled(),
                        reason="live test: set QUANTEXEC_LIVE=1 and provide Alpaca credentials")
    def test_live_smoke_download_aapl_one_minute():
        run_live_smoke()
except ImportError:
    pass


if __name__ == "__main__":
    if not _live_enabled():
        print("live smoke test skipped: set QUANTEXEC_LIVE=1 and provide "
              "ALPACA_API_KEY / ALPACA_SECRET_KEY to enable.")
        sys.exit(0)
    run_live_smoke()
    sys.exit(0)
