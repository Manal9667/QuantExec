"""
Offline tests for python/alpaca_ingest.py (real historical-quote ingestion).

NO NETWORK. Alpaca's HTTP layer is replaced by a FakeSession that returns
canned JSON pages, exactly mirroring Alpaca's documented quotes-endpoint
response shape ({"quotes": [...], "next_page_token": ...}). The final
serialized dataset is round-tripped through the REAL C++ CsvMarketSource (via
pybind11) so we prove the CSV this module writes is valid engine input, not
just internally consistent.

These tests must NEVER hit the live Alpaca API - that is what the separate,
explicitly-marked live smoke test (test_alpaca_live_smoke.py) is for.

Run with:  python -m pytest python/test_alpaca_ingest.py -v
       or:  python python/test_alpaca_ingest.py   (plain-assert fallback, no pytest)
"""

import json
import os
import sys
import tempfile
from pathlib import Path

# Allow running both as `pytest python/test_alpaca_ingest.py` (cwd = repo root,
# package import) and as a bare script from inside python/.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_THIS_DIR)
for _p in (_REPO_ROOT, _THIS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)
# Make the compiled executor importable regardless of how pytest is launched.
for _b in (os.path.join(_REPO_ROOT, "build", "Release"), os.path.join(_REPO_ROOT, "build")):
    if os.path.exists(_b) and _b not in sys.path:
        sys.path.insert(0, _b)

try:
    from python.alpaca_ingest import (
        AlpacaCredentials,
        AlpacaHTTPError,
        HistoricalQuoteDownloader,
        NormalizedQuote,
        ValidationStats,
        normalize_quotes,
        validate_quotes,
        normalized_quotes_to_alpaca_shape,
        build_metadata,
        ingest,
        _ms_to_rfc3339,
    )
except ImportError:
    from alpaca_ingest import (  # type: ignore
        AlpacaCredentials,
        AlpacaHTTPError,
        HistoricalQuoteDownloader,
        NormalizedQuote,
        ValidationStats,
        normalize_quotes,
        validate_quotes,
        normalized_quotes_to_alpaca_shape,
        build_metadata,
        ingest,
        _ms_to_rfc3339,
    )

from executor import CsvMarketSource, ExecutionSession, OrderSide, TWAPAlgorithm, VWAPAlgorithm


CREDS = AlpacaCredentials(key_id="TEST_KEY", secret_key="TEST_SECRET")


# ---------------------------------------------------------------------------
# Fake HTTP layer
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, status_code, json_body=None, text="", headers=None, method="GET", url=""):
        self.status_code = status_code
        self._json = json_body if json_body is not None else {}
        self.text = text
        self.headers = headers or {}

        class _Req:
            pass

        self.request = _Req()
        self.request.method = method

    @property
    def ok(self):
        return 200 <= self.status_code < 300

    def json(self):
        return self._json


class FakeSession:
    """
    Stand-in for requests.Session. Returns queued responses in order (one per
    GET). Records the params of every call so tests can assert feed=iex,
    pagination tokens, etc.
    """

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        self.headers = {}

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": dict(params or {}), "timeout": timeout})
        if not self._responses:
            raise AssertionError("FakeSession ran out of queued responses")
        return self._responses.pop(0)


def _quote(t, bp, bs, ap, as_, bx="V", ax="V", c=("R",)):
    return {"t": t, "ax": ax, "ap": ap, "as": as_, "bx": bx, "bp": bp, "bs": bs, "c": list(c)}


# ---------------------------------------------------------------------------
# 1. Pagination
# ---------------------------------------------------------------------------

def test_pagination_follows_next_page_token_and_concatenates():
    page1 = _FakeResponse(200, {
        "quotes": [_quote("2024-01-03T14:30:00.100Z", 100.0, 1, 100.1, 1),
                   _quote("2024-01-03T14:30:00.200Z", 100.0, 2, 100.1, 2)],
        "next_page_token": "TOKEN_A",
    })
    page2 = _FakeResponse(200, {
        "quotes": [_quote("2024-01-03T14:30:00.300Z", 100.0, 3, 100.1, 3)],
        "next_page_token": None,
    })
    session = FakeSession([page1, page2])
    dl = HistoricalQuoteDownloader(CREDS, feed="iex", session=session)
    quotes = dl.download_quotes("AAPL", "2024-01-03T14:30:00Z", "2024-01-03T14:31:00Z")

    assert len(quotes) == 3
    # Two GETs: first without token, second carrying next_page_token.
    assert len(session.calls) == 2
    assert "page_token" not in session.calls[0]["params"]
    assert session.calls[1]["params"]["page_token"] == "TOKEN_A"
    # Feed is explicit on every call.
    assert all(c["params"]["feed"] == "iex" for c in session.calls)
    print("test_pagination_follows_next_page_token_and_concatenates passed")


def test_pagination_repeated_token_is_not_infinite_loop():
    # Same token twice would loop forever if not guarded.
    r1 = _FakeResponse(200, {"quotes": [_quote("2024-01-03T14:30:00.1Z", 100, 1, 100.1, 1)],
                             "next_page_token": "SAME"})
    r2 = _FakeResponse(200, {"quotes": [_quote("2024-01-03T14:30:00.2Z", 100, 1, 100.1, 1)],
                             "next_page_token": "SAME"})
    session = FakeSession([r1, r2, r2, r2])
    dl = HistoricalQuoteDownloader(CREDS, session=session)
    try:
        dl.download_quotes("AAPL", "s", "e")
    except AlpacaHTTPError as exc:
        assert "infinite pagination loop" in str(exc)
        print("test_pagination_repeated_token_is_not_infinite_loop passed")
        return
    raise AssertionError("expected AlpacaHTTPError on repeated page token")


# ---------------------------------------------------------------------------
# 2. Ordering + de-duplication (determinism)
# ---------------------------------------------------------------------------

def test_download_orders_and_dedupes():
    q_a = _quote("2024-01-03T14:30:00.300Z", 100.0, 3, 100.1, 3)
    q_b = _quote("2024-01-03T14:30:00.100Z", 100.0, 1, 100.1, 1)
    q_dup = _quote("2024-01-03T14:30:00.100Z", 100.0, 1, 100.1, 1)  # exact dup of q_b
    session = FakeSession([_FakeResponse(200, {"quotes": [q_a, q_b, q_dup], "next_page_token": None})])
    dl = HistoricalQuoteDownloader(CREDS, session=session)
    quotes = dl.download_quotes("AAPL", "s", "e")

    assert len(quotes) == 2  # duplicate removed
    # Sorted ascending by timestamp.
    assert quotes[0]["t"] == "2024-01-03T14:30:00.100Z"
    assert quotes[1]["t"] == "2024-01-03T14:30:00.300Z"
    print("test_download_orders_and_dedupes passed")


# ---------------------------------------------------------------------------
# 3. HTTP error handling (mocked)
# ---------------------------------------------------------------------------

def test_non_transient_http_error_is_clear_and_no_credentials_leak():
    session = FakeSession([_FakeResponse(401, text="unauthorized", method="GET")])
    dl = HistoricalQuoteDownloader(CREDS, session=session, max_retries=2)
    try:
        dl.download_quotes("AAPL", "2024-01-03T14:30:00Z", "2024-01-03T14:31:00Z")
    except AlpacaHTTPError as exc:
        msg = str(exc)
        assert "401" in msg
        assert "TEST_SECRET" not in msg and "TEST_KEY" not in msg
        print("test_non_transient_http_error_is_clear_and_no_credentials_leak passed")
        return
    raise AssertionError("expected AlpacaHTTPError on HTTP 401")


def test_retryable_status_then_success():
    ok = _FakeResponse(200, {"quotes": [_quote("2024-01-03T14:30:00.1Z", 100, 1, 100.1, 1)],
                             "next_page_token": None})
    # 503 then 200: downloader should retry and succeed.
    session = FakeSession([_FakeResponse(503, text="busy"), ok])
    dl = HistoricalQuoteDownloader(CREDS, session=session, max_retries=3, backoff_base_s=0.0)
    quotes = dl.download_quotes("AAPL", "s", "e")
    assert len(quotes) == 1
    assert len(session.calls) == 2
    print("test_retryable_status_then_success passed")


# ---------------------------------------------------------------------------
# 4. Normalization
# ---------------------------------------------------------------------------

def test_normalize_maps_all_fields():
    raw = [_quote("2024-01-03T14:30:00.500Z", 100.40, 5, 100.50, 4, bx="P", ax="Q", c=("R", "F"))]
    norm = normalize_quotes(raw, "AAPL")
    assert len(norm) == 1
    n = norm[0]
    assert n.symbol == "AAPL"
    assert n.bid == 100.40 and n.ask == 100.50
    assert n.bid_size == 5 * 100 and n.ask_size == 4 * 100  # round lots -> shares
    assert n.bid_exchange == "P" and n.ask_exchange == "Q"
    assert n.conditions == ("R", "F")
    assert n.timestamp_ms == 1704292200500
    print("test_normalize_maps_all_fields passed")


# ---------------------------------------------------------------------------
# 5. Invalid-quote detection / validation statistics
# ---------------------------------------------------------------------------

def _nq(ts, bid, ask, bid_size=100, ask_size=100):
    return NormalizedQuote(timestamp_ms=ts, bid=bid, bid_size=bid_size, bid_exchange="V",
                           ask=ask, ask_size=ask_size, ask_exchange="V",
                           conditions=("R",), symbol="AAPL")


def test_validation_classifies_every_defect():
    quotes = [
        _nq(1, 100.0, 100.1),                 # valid
        _nq(2, 0.0, 100.1),                    # one-sided (missing bid)
        _nq(3, 100.2, 100.1),                  # crossed (bid > ask)
        _nq(4, 100.1, 100.1),                  # locked (bid == ask)
        _nq(5, 100.0, 100.1, bid_size=0),      # zero size
        _nq(6, 100.0, 100.1),                  # valid
        _nq(6, 100.0, 100.1),                  # duplicate timestamp
        _nq(2, 100.0, 100.1),                  # out of order (ts < last kept=6)
    ]
    kept, stats = validate_quotes(quotes)

    assert stats.records_downloaded == 8
    assert stats.records_valid == 2
    assert stats.one_sided_quotes == 1
    assert stats.crossed_quotes == 1
    assert stats.locked_quotes == 1
    assert stats.zero_size_quotes == 1
    assert stats.duplicate_quotes == 1
    assert stats.out_of_order_quotes == 1
    # Accounting invariant: every downloaded record has exactly one disposition.
    rejected = (stats.one_sided_quotes + stats.crossed_quotes + stats.locked_quotes
                + stats.zero_size_quotes + stats.duplicate_quotes + stats.out_of_order_quotes
                + stats.non_positive_price_quotes)
    assert stats.records_valid + rejected == stats.records_downloaded
    assert len(kept) == 2
    print("test_validation_classifies_every_defect passed")


def test_wide_spread_is_flagged_but_kept():
    quotes = [_nq(1, 100.0, 110.0)]  # 10% spread > 5% threshold
    kept, stats = validate_quotes(quotes)
    assert len(kept) == 1                # still kept
    assert stats.records_valid == 1
    assert stats.wide_spread_quotes == 1  # but flagged
    print("test_wide_spread_is_flagged_but_kept passed")


# ---------------------------------------------------------------------------
# 6. Deterministic serialization + C++ CsvMarketSource round-trip
# ---------------------------------------------------------------------------

def _fixture_bars():
    return [
        {"t": "2024-01-03T14:30:00Z", "o": 100.0, "h": 100.6, "l": 100.0, "c": 100.5,
         "v": 5000, "n": 10, "vw": 100.3},
        {"t": "2024-01-03T14:31:00Z", "o": 100.5, "h": 100.9, "l": 100.4, "c": 100.7,
         "v": 3000, "n": 8, "vw": 100.6},
    ]


class _StubDownloader:
    """Implements the surface ingest() uses, returning canned quotes + bars."""

    def __init__(self, quotes):
        self._quotes = quotes
        self.feed = "iex"
        self._page_limit = 10000

    def download_quotes(self, symbol, start, end):
        return list(self._quotes)


def test_ingest_end_to_end_offline_and_cpp_loads_it():
    raw_quotes = [
        _quote("2024-01-03T14:30:05.000Z", 100.40, 5, 100.50, 5),
        _quote("2024-01-03T14:30:45.000Z", 100.45, 6, 100.55, 4),
        _quote("2024-01-03T14:31:10.000Z", 100.50, 5, 100.60, 3),
        # A crossed quote that MUST be dropped so the C++ source accepts the file.
        _quote("2024-01-03T14:31:20.000Z", 100.90, 5, 100.60, 3),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        result = ingest(
            "AAPL", "2024-01-03T14:30:00Z", "2024-01-03T14:32:00Z",
            feed="iex",
            data_root=Path(tmp),
            downloader=_StubDownloader(raw_quotes),
            bars=_fixture_bars(),
        )
        assert result.stats.records_downloaded == 4
        assert result.stats.crossed_quotes == 1
        assert result.stats.records_valid == 3
        assert result.rows_written == 3

        # CSV lives under data/raw/alpaca/AAPL/ with the deterministic stem.
        assert os.path.exists(result.csv_path)
        assert result.csv_path.endswith(
            os.path.join("raw", "alpaca", "AAPL", "AAPL_2024-01-03_1430-1432_quotes.csv"))

        # Metadata has no credentials and records L1 + validation.
        with open(result.metadata_path) as f:
            meta = json.load(f)
        assert meta["feed"] == "iex"
        assert meta["data_level"] == "L1"
        assert meta["records_valid"] == 3
        assert "TEST_SECRET" not in json.dumps(meta)
        assert "validation" in meta and meta["validation"]["crossed_quotes"] == 1

        # The REAL C++ CsvMarketSource must accept the generated CSV.
        source = CsvMarketSource(result.csv_path)
        assert source.ok(), "C++ CsvMarketSource rejected the generated dataset"

        # And ExecutionSession must run TWAP + VWAP against it.
        twap = TWAPAlgorithm()
        twap_orders = twap.generate_orders(1, OrderSide.Buy, 90, 200.0, 3)
        twap_result = ExecutionSession().run(CsvMarketSource(result.csv_path), twap_orders, 100.45)
        assert twap_result.filled_quantity > 0

        vwap = VWAPAlgorithm()
        vwap.set_volume_profile([0.5, 0.3, 0.2])
        vwap_orders = vwap.generate_orders(2, OrderSide.Buy, 90, 200.0, 3)
        vwap_result = ExecutionSession().run(CsvMarketSource(result.csv_path), vwap_orders, 100.45)
        assert vwap_result.filled_quantity > 0
    print("test_ingest_end_to_end_offline_and_cpp_loads_it passed")


def test_ingest_is_deterministic_byte_for_byte():
    raw_quotes = [
        _quote("2024-01-03T14:30:05.000Z", 100.40, 5, 100.50, 5),
        _quote("2024-01-03T14:30:45.000Z", 100.45, 6, 100.55, 4),
    ]
    csvs = []
    for _ in range(2):
        with tempfile.TemporaryDirectory() as tmp:
            result = ingest("AAPL", "2024-01-03T14:30:00Z", "2024-01-03T14:32:00Z",
                            data_root=Path(tmp), downloader=_StubDownloader(raw_quotes),
                            bars=_fixture_bars())
            with open(result.csv_path, "rb") as f:
                csvs.append(f.read())
    assert csvs[0] == csvs[1], "CSV serialization is not deterministic across runs"
    print("test_ingest_is_deterministic_byte_for_byte passed")


def test_ms_to_rfc3339_round_trips():
    from python.alpaca_ingest import _parse_rfc3339_to_ms  # re-exported import
    ts = 1704292205500
    assert _parse_rfc3339_to_ms(_ms_to_rfc3339(ts)) == ts
    print("test_ms_to_rfc3339_round_trips passed")


def test_metadata_never_contains_credentials():
    stats = ValidationStats(records_downloaded=1, records_valid=1)
    meta = build_metadata("AAPL", "iex", "s", "e", stats, 1, "raw/alpaca/AAPL/x.csv")
    blob = json.dumps(meta)
    assert "APCA" not in blob
    assert "secret" not in blob.lower()
    assert meta["source"] == "alpaca"
    print("test_metadata_never_contains_credentials passed")


_TESTS = [
    test_pagination_follows_next_page_token_and_concatenates,
    test_pagination_repeated_token_is_not_infinite_loop,
    test_download_orders_and_dedupes,
    test_non_transient_http_error_is_clear_and_no_credentials_leak,
    test_retryable_status_then_success,
    test_normalize_maps_all_fields,
    test_validation_classifies_every_defect,
    test_wide_spread_is_flagged_but_kept,
    test_ingest_end_to_end_offline_and_cpp_loads_it,
    test_ingest_is_deterministic_byte_for_byte,
    test_ms_to_rfc3339_round_trips,
    test_metadata_never_contains_credentials,
]


if __name__ == "__main__":
    for t in _TESTS:
        t()
    print(f"\nAll {len(_TESTS)} alpaca_ingest offline tests passed (no network calls)")
    sys.exit(0)
