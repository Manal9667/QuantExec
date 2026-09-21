"""
Real historical-quote ingestion for QuantExec (Phase 3, real-data path).

    Alpaca Historical API  (GET /v2/stocks/{symbol}/quotes, IEX feed)
            |
    HistoricalQuoteDownloader        <-- pagination, retry, timeout, loop guard
            |
    normalize_quotes()               <-- Alpaca {t,ax,ap,as,bx,bp,bs,c} -> NormalizedQuote
            |
    validate_quotes()                <-- data-quality classification + statistics
            |
    (drop C++-incompatible records)  <-- crossed / non-positive / duplicate / out-of-order
            |
    merge_into_rows() + write_historical_csv()   (reused from alpaca_historical.py)
            |
    the SAME CSV schema CsvMarketSource has consumed since Phase 1
            |
    ExecutionSession -> TWAP / VWAP / POV -> execution analytics

WHAT THIS DATASET ACTUALLY IS
-----------------------------
Alpaca's free tier exposes the IEX feed only. The /quotes endpoint returns
Level 1 (top-of-book) NBBO quotes from IEX: one bid level and one ask level
per tick. This is *historical L1 quote replay*. It is NOT a reconstruction of
a full historical exchange order book, and this module never fabricates depth,
trades, or additional levels. See docs/HISTORICAL_INGESTION.md and the
module docstring in alpaca_historical.py for the full accounting of what is
real vs. approximated (bar volume / last price are joined from the coarser
bars endpoint by merge_into_rows()).

SECURITY
--------
* Credentials load from the repo-root .env (ALPACA_API_KEY / ALPACA_SECRET_KEY)
  via python-dotenv. They are sent as the APCA-API-KEY-ID / APCA-API-SECRET-KEY
  headers Alpaca expects. Credentials are never printed, logged, or written to
  dataset metadata.
* TLS certificate verification stays ON. `verify=False` is never used. The
  local Windows certificate environment needs the OS trust store, so this
  module injects `truststore` at import time (same as the repo's test_alpaca.py).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# --- Secure TLS: use the OS trust store (needed on this Windows setup). -------
# Done before `requests`/urllib3 create any SSL context. Verification stays on;
# this only teaches Python where to find the system's trusted roots.
try:
    import truststore  # type: ignore
    truststore.inject_into_ssl()
except Exception:  # noqa: BLE001 - truststore is best-effort; verification stays ON regardless
    pass

import requests

try:
    from dotenv import load_dotenv
except Exception:  # noqa: BLE001
    load_dotenv = None  # type: ignore

# Reuse the project's single Alpaca field-mapping + timestamp helpers instead of
# re-parsing bp/ap/bs/as here (the whole point of quote_to_top_of_book).
try:
    from .alpaca_adapter import _parse_rfc3339_to_ms, QUOTE_SIZE_LOT_MULTIPLIER
    from .alpaca_historical import merge_into_rows, write_historical_csv, HistoricalRow, CSV_COLUMNS
except ImportError:  # running as a plain script, not a package module
    from alpaca_adapter import _parse_rfc3339_to_ms, QUOTE_SIZE_LOT_MULTIPLIER
    from alpaca_historical import merge_into_rows, write_historical_csv, HistoricalRow, CSV_COLUMNS


LOGGER = logging.getLogger("quantexec.alpaca_ingest")

ALPACA_DATA_BASE_URL = "https://data.alpaca.markets/v2"
DEFAULT_FEED = "iex"

# --- Documented validation thresholds ----------------------------------------
# A quote is flagged "wide spread" when (ask - bid) / mid exceeds this fraction.
# 5% is deliberately loose: it is a data-quality *warning* for auditing, not a
# rejection reason. Real IEX top-of-book can legitimately show wide spreads for
# thin names or around the open, so we count them but still keep the record if
# it is otherwise a valid, uncrossed two-sided quote.
WIDE_SPREAD_FRACTION = 0.05

# Hard cap on pages fetched in a single download, so a malformed/looping
# next_page_token can never spin forever. 10k quotes/page * 5000 pages = 50M
# quotes, far beyond any single free-tier interval we would request.
MAX_PAGES = 5000

# Per-request row cap Alpaca honors on the free tier.
DEFAULT_PAGE_LIMIT = 10000


class AlpacaAuthError(RuntimeError):
    """Credentials are missing from the environment."""


class AlpacaHTTPError(RuntimeError):
    """A non-transient HTTP error from Alpaca, with a clear message."""


@dataclass(frozen=True)
class AlpacaCredentials:
    """Alpaca API credentials, loaded from the environment only."""

    key_id: str
    secret_key: str

    @staticmethod
    def from_env(load_env_file: bool = True) -> "AlpacaCredentials":
        """
        Read ALPACA_API_KEY / ALPACA_SECRET_KEY from the environment.

        These are the names used in the repo-root .env (which stays gitignored).
        The values are sent as Alpaca's APCA-API-KEY-ID / APCA-API-SECRET-KEY
        headers. This never returns or logs the secret itself.
        """
        if load_env_file and load_dotenv is not None:
            # Loads the repo-root .env if present; does not override already-set
            # process env vars, so CI can inject credentials without a file.
            load_dotenv()
        key_id = os.environ.get("ALPACA_API_KEY")
        secret_key = os.environ.get("ALPACA_SECRET_KEY")
        if not key_id or not secret_key:
            raise AlpacaAuthError(
                "Alpaca credentials not found. Set ALPACA_API_KEY and "
                "ALPACA_SECRET_KEY in the repo-root .env (kept gitignored) or "
                "in the environment before downloading historical data."
            )
        return AlpacaCredentials(key_id=key_id, secret_key=secret_key)


class HistoricalQuoteDownloader:
    """
    Reusable client for Alpaca's historical quotes endpoint.

    Owns exactly one concern: turning (symbol, start, end, feed) into a
    complete, chronologically-ordered, de-duplicated list of raw Alpaca quote
    dicts - correctly following next_page_token, retrying transient failures,
    and never silently truncating the result.
    """

    # Status codes worth retrying: 429 (rate limit) and 5xx (transient server).
    _RETRYABLE_STATUS = {429, 500, 502, 503, 504}

    def __init__(
        self,
        credentials: AlpacaCredentials,
        feed: str = DEFAULT_FEED,
        session: Optional[requests.Session] = None,
        timeout_s: float = 30.0,
        max_retries: int = 4,
        backoff_base_s: float = 0.5,
        page_limit: int = DEFAULT_PAGE_LIMIT,
    ):
        self._feed = feed
        self._timeout_s = timeout_s
        self._max_retries = max_retries
        self._backoff_base_s = backoff_base_s
        self._page_limit = page_limit
        self._session = session or requests.Session()
        # Auth headers set once on the session; never logged.
        self._session.headers.update({
            "APCA-API-KEY-ID": credentials.key_id,
            "APCA-API-SECRET-KEY": credentials.secret_key,
        })

    @property
    def feed(self) -> str:
        return self._feed

    def _get_page(self, url: str, params: dict) -> dict:
        """One GET with retry/backoff for transient failures. Returns JSON."""
        last_exc: Optional[Exception] = None
        for attempt in range(1, self._max_retries + 1):
            try:
                response = self._session.get(url, params=params, timeout=self._timeout_s)
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
                wait = self._backoff_base_s * (2 ** (attempt - 1))
                LOGGER.warning("transient network error (attempt %d/%d): %s; retrying in %.1fs",
                               attempt, self._max_retries, exc, wait)
                time.sleep(wait)
                continue

            if response.status_code in self._RETRYABLE_STATUS and attempt < self._max_retries:
                wait = self._backoff_base_s * (2 ** (attempt - 1))
                # Honor Retry-After if Alpaca sends one (common on 429).
                retry_after = response.headers.get("Retry-After")
                if retry_after:
                    try:
                        wait = max(wait, float(retry_after))
                    except ValueError:
                        pass
                LOGGER.warning("retryable HTTP %d (attempt %d/%d); retrying in %.1fs",
                               response.status_code, attempt, self._max_retries, wait)
                time.sleep(wait)
                continue

            if not response.ok:
                # Non-transient (e.g. 401 bad creds, 403 feed not allowed,
                # 422 bad params). Surface a clear message; do NOT leak headers.
                raise AlpacaHTTPError(
                    f"Alpaca returned HTTP {response.status_code} for "
                    f"{response.request.method} {url} "
                    f"(feed={params.get('feed')}, start={params.get('start')}, "
                    f"end={params.get('end')}): {response.text[:500]}"
                )
            return response.json()

        raise AlpacaHTTPError(
            f"Alpaca request to {url} failed after {self._max_retries} attempts: {last_exc}"
        )

    def download_quotes(self, symbol: str, start: str, end: str) -> List[dict]:
        """
        Return every raw quote in [start, end) for `symbol`, chronologically
        ordered and de-duplicated on the full record.

        `start`/`end` are RFC-3339 UTC strings, e.g. '2024-01-03T14:30:00Z'.
        Follows next_page_token to completion; raises on a hard HTTP error or
        if the page cap is hit (rather than returning a truncated dataset).
        """
        url = f"{ALPACA_DATA_BASE_URL}/stocks/{symbol}/quotes"
        page_token: Optional[str] = None
        collected: List[dict] = []
        seen_tokens: set[str] = set()
        pages = 0

        LOGGER.info("downloading %s quotes [%s .. %s) feed=%s", symbol, start, end, self._feed)
        while True:
            pages += 1
            if pages > MAX_PAGES:
                raise AlpacaHTTPError(
                    f"Pagination exceeded {MAX_PAGES} pages for {symbol} "
                    f"[{start}..{end}); aborting to avoid an infinite loop rather "
                    f"than returning a possibly-truncated dataset."
                )
            params = {"start": start, "end": end, "limit": self._page_limit, "feed": self._feed}
            if page_token:
                params["page_token"] = page_token
            payload = self._get_page(url, params)
            page_quotes = payload.get("quotes") or []
            collected.extend(page_quotes)
            next_token = payload.get("next_page_token")
            LOGGER.info("page %d: +%d quotes (total %d)%s",
                        pages, len(page_quotes), len(collected),
                        " [more]" if next_token else " [final]")
            if not next_token:
                break
            # Loop guard: Alpaca must always advance the token. A repeat means a
            # broken response; stop rather than spin.
            if next_token in seen_tokens:
                raise AlpacaHTTPError(
                    f"next_page_token repeated for {symbol}; aborting to avoid an "
                    f"infinite pagination loop."
                )
            seen_tokens.add(next_token)
            page_token = next_token

        # Deterministic: sort by timestamp, then drop exact-duplicate records.
        # Alpaca returns quotes in ascending time already, but we do not rely on
        # that - explicit ordering makes the dataset reproducible.
        ordered = sorted(collected, key=_quote_sort_key)
        deduped = _dedupe_quotes(ordered)
        LOGGER.info("downloaded %d quotes (%d after de-duplication) across %d page(s)",
                    len(collected), len(deduped), pages)
        return deduped


def _quote_sort_key(quote: dict) -> Tuple[int, float, float]:
    """Stable ordering key: (timestamp_ms, bid, ask). Robust to missing time."""
    t = quote.get("t")
    ts = _parse_rfc3339_to_ms(t) if t else 0
    return (ts, float(quote.get("bp", 0.0) or 0.0), float(quote.get("ap", 0.0) or 0.0))


def _quote_identity(quote: dict) -> Tuple:
    """Full-record identity for de-duplication (timestamp + all L1 fields)."""
    return (
        quote.get("t"),
        quote.get("bp"), quote.get("bs"), quote.get("bx"),
        quote.get("ap"), quote.get("as"), quote.get("ax"),
        tuple(quote.get("c") or ()),
    )


def _dedupe_quotes(quotes: List[dict]) -> List[dict]:
    """Drop exact-duplicate records, preserving first occurrence / order."""
    seen: set = set()
    out: List[dict] = []
    for q in quotes:
        identity = _quote_identity(q)
        if identity in seen:
            continue
        seen.add(identity)
        out.append(q)
    return out


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class NormalizedQuote:
    """
    QuantExec's normalized representation of one Alpaca L1 quote.

    Sizes are kept in *shares* (Alpaca reports quote sizes in round lots, so we
    multiply by QUOTE_SIZE_LOT_MULTIPLIER exactly like the real-time adapter).
    Prices/sizes are preserved as-is; validity is judged separately by
    validate_quotes() - normalization never discards or fabricates fields.
    """

    timestamp_ms: int
    bid: float
    bid_size: int
    bid_exchange: str
    ask: float
    ask_size: int
    ask_exchange: str
    conditions: Tuple[str, ...]
    symbol: str


def normalize_quotes(
    quotes: List[dict],
    symbol: str,
    lot_multiplier: int = QUOTE_SIZE_LOT_MULTIPLIER,
) -> List[NormalizedQuote]:
    """
    Map raw Alpaca quote dicts ({t,ax,ap,as,bx,bp,bs,c}) to NormalizedQuote.

    This preserves timestamp, bid/ask price+size+exchange, conditions, and
    symbol. It does not judge validity (a zero or crossed quote still produces
    a NormalizedQuote) - that is validate_quotes()'s job, so the two concerns
    stay separable and independently testable.
    """
    out: List[NormalizedQuote] = []
    for q in quotes:
        t = q.get("t")
        out.append(NormalizedQuote(
            timestamp_ms=_parse_rfc3339_to_ms(t) if t else 0,
            bid=float(q.get("bp", 0.0) or 0.0),
            bid_size=int(q.get("bs", 0) or 0) * lot_multiplier,
            bid_exchange=str(q.get("bx", "") or ""),
            ask=float(q.get("ap", 0.0) or 0.0),
            ask_size=int(q.get("as", 0) or 0) * lot_multiplier,
            ask_exchange=str(q.get("ax", "") or ""),
            conditions=tuple(q.get("c") or ()),
            symbol=symbol,
        ))
    return out


# ---------------------------------------------------------------------------
# Data-quality validation
# ---------------------------------------------------------------------------

@dataclass
class ValidationStats:
    """
    Counts produced while classifying normalized quotes. Every downloaded
    record is accounted for: records_valid + the mutually-exclusive rejection
    buckets + records that were only *flagged* (wide spread) but still kept.

    A record can trip more than one *flag* (e.g. wide spread) but is assigned
    exactly one disposition (kept-valid or one rejection reason), so
    records_downloaded == records_valid + sum(rejection buckets).
    """

    records_downloaded: int = 0
    records_valid: int = 0
    # Mutually-exclusive rejection buckets (a record lands in the first that applies).
    non_positive_price_quotes: int = 0
    zero_size_quotes: int = 0
    one_sided_quotes: int = 0
    crossed_quotes: int = 0
    locked_quotes: int = 0
    duplicate_quotes: int = 0
    out_of_order_quotes: int = 0
    # Non-rejecting flags (counted on records that were still kept as valid).
    wide_spread_quotes: int = 0

    def to_dict(self) -> Dict[str, int]:
        return asdict(self)


def validate_quotes(
    quotes: List[NormalizedQuote],
    wide_spread_fraction: float = WIDE_SPREAD_FRACTION,
) -> Tuple[List[NormalizedQuote], ValidationStats]:
    """
    Classify normalized quotes and return (kept_valid_quotes, stats).

    Disposition rules, applied in this order per record:
      1. non-positive price   - bid <= 0 or ask <= 0 but not *both* zero  -> reject
         (both-zero / one-missing is treated as one-sided below first)
      2. one-sided             - exactly one of bid/ask is <= 0            -> reject
      3. zero size             - bid_size <= 0 or ask_size <= 0            -> reject
      4. crossed               - bid > ask                                -> reject
      5. locked                - bid == ask                               -> reject
      6. duplicate timestamp   - same timestamp_ms as a kept record       -> reject
      7. out of order          - timestamp_ms < last kept timestamp        -> reject
    A kept record may additionally be *flagged* wide-spread (still kept).

    Rationale for rejecting locked/crossed/duplicate/out-of-order: the C++
    CsvMarketSource requires strictly-monotonic timestamps and bid <= ask, and
    rejects the *entire file* if any row violates that. Cleaning here (and
    counting what was dropped) is what lets a real IEX dataset load at all,
    without weakening the engine's validation. Locked quotes (bid == ask, zero
    spread) are dropped because they imply a zero/there's-no-spread book that
    distorts spread-cost analytics; they are reported so nothing is hidden.
    """
    kept: List[NormalizedQuote] = []
    stats = ValidationStats(records_downloaded=len(quotes))
    last_kept_ts: Optional[int] = None
    seen_ts: set[int] = set()

    for q in quotes:
        both_zero = q.bid <= 0.0 and q.ask <= 0.0
        one_missing = (q.bid <= 0.0) ^ (q.ask <= 0.0)

        if one_missing or both_zero:
            # Treat any missing side as one-sided (covers both-zero too).
            stats.one_sided_quotes += 1
            continue
        if q.bid <= 0.0 or q.ask <= 0.0:
            stats.non_positive_price_quotes += 1
            continue
        if q.bid_size <= 0 or q.ask_size <= 0:
            stats.zero_size_quotes += 1
            continue
        if q.bid > q.ask:
            stats.crossed_quotes += 1
            continue
        if q.bid == q.ask:
            stats.locked_quotes += 1
            continue
        if q.timestamp_ms in seen_ts:
            stats.duplicate_quotes += 1
            continue
        if last_kept_ts is not None and q.timestamp_ms < last_kept_ts:
            stats.out_of_order_quotes += 1
            continue

        # Kept as valid. Flag (but keep) unusually wide spreads.
        mid = (q.bid + q.ask) / 2.0
        if mid > 0.0 and (q.ask - q.bid) / mid > wide_spread_fraction:
            stats.wide_spread_quotes += 1

        kept.append(q)
        seen_ts.add(q.timestamp_ms)
        last_kept_ts = q.timestamp_ms
        stats.records_valid += 1

    return kept, stats


# ---------------------------------------------------------------------------
# Bridge to the existing CSV writer
# ---------------------------------------------------------------------------

def normalized_quotes_to_alpaca_shape(quotes: List[NormalizedQuote],
                                      lot_multiplier: int = QUOTE_SIZE_LOT_MULTIPLIER) -> List[dict]:
    """
    Re-emit kept NormalizedQuotes in the raw Alpaca {t,ap,as,bp,bs,...} shape
    that merge_into_rows()/quote_to_top_of_book() consume. This lets the real
    pipeline reuse the exact same merge + CSV-writing code the offline tests
    already exercise, instead of duplicating it. Sizes are converted back to
    round lots so quote_to_top_of_book re-applies the multiplier consistently.
    """
    out: List[dict] = []
    for q in quotes:
        out.append({
            "t": _ms_to_rfc3339(q.timestamp_ms),
            "ax": q.ask_exchange,
            "ap": q.ask,
            "as": q.ask_size // lot_multiplier if lot_multiplier else q.ask_size,
            "bx": q.bid_exchange,
            "bp": q.bid,
            "bs": q.bid_size // lot_multiplier if lot_multiplier else q.bid_size,
            "c": list(q.conditions),
        })
    return out


def _ms_to_rfc3339(timestamp_ms: int) -> str:
    """Inverse of _parse_rfc3339_to_ms for millisecond timestamps (UTC, 'Z')."""
    dt = datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# ---------------------------------------------------------------------------
# Dataset + metadata output
# ---------------------------------------------------------------------------

@dataclass
class IngestionResult:
    symbol: str
    feed: str
    start: str
    end: str
    csv_path: str
    metadata_path: str
    rows_written: int
    stats: ValidationStats


def _default_data_root() -> Path:
    """data/ under the repo root (parent of this python/ package)."""
    return Path(__file__).resolve().parent.parent / "data"


def _dataset_basename(symbol: str, start: str, end: str) -> str:
    """
    Deterministic file stem: SYMBOL_YYYY-MM-DD_HHMM-HHMM_quotes.
    Uses the requested interval, so the same request maps to the same filename.
    """
    s = _parse_rfc3339_to_ms(start)
    e = _parse_rfc3339_to_ms(end)
    sd = datetime.fromtimestamp(s / 1000.0, tz=timezone.utc)
    ed = datetime.fromtimestamp(e / 1000.0, tz=timezone.utc)
    day = sd.strftime("%Y-%m-%d")
    return f"{symbol}_{day}_{sd.strftime('%H%M')}-{ed.strftime('%H%M')}_quotes"


def build_metadata(symbol: str, feed: str, start: str, end: str,
                   stats: ValidationStats, rows_written: int,
                   csv_relpath: str) -> dict:
    """
    Reproducible, auditable dataset metadata. Contains NO credentials - only
    the request parameters, timestamps, row counts, and validation statistics.
    """
    return {
        "source": "alpaca",
        "endpoint": "/v2/stocks/{symbol}/quotes",
        "feed": feed,
        "data_level": "L1",  # top-of-book NBBO from IEX; NOT full-depth / L2
        "symbol": symbol,
        "start": start,
        "end": end,
        "downloaded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "csv_path": csv_relpath,
        "csv_columns": CSV_COLUMNS,
        "records_downloaded": stats.records_downloaded,
        "records_valid": stats.records_valid,
        "rows_written": rows_written,
        "validation": stats.to_dict(),
        "limitations": (
            "Historical L1 quote replay from Alpaca's free IEX feed: one bid "
            "and one ask level per tick. Not a full-depth (L2) order book. Bar "
            "volume and last price are approximated from the coarser bars "
            "endpoint by merge_into_rows(); see alpaca_historical.py."
        ),
    }


def ingest(
    symbol: str,
    start: str,
    end: str,
    feed: str = DEFAULT_FEED,
    timeframe: str = "1Min",
    data_root: Optional[Path] = None,
    downloader: Optional[HistoricalQuoteDownloader] = None,
    bars: Optional[List[dict]] = None,
) -> IngestionResult:
    """
    End-to-end real ingestion: download -> normalize -> validate -> merge with
    bars -> deterministic CSV + metadata. Returns an IngestionResult.

    `downloader` and `bars` are injectable for testing; in production they are
    created from live credentials. Bar volume is best-effort (see module docs);
    if the bars request fails or returns nothing, quotes still produce a valid
    CSV with zero volume.
    """
    if downloader is None:
        credentials = AlpacaCredentials.from_env()
        downloader = HistoricalQuoteDownloader(credentials, feed=feed)

    raw_quotes = downloader.download_quotes(symbol, start, end)
    normalized = normalize_quotes(raw_quotes, symbol)
    kept, stats = validate_quotes(normalized)

    if bars is None:
        bars = _download_bars_best_effort(downloader, symbol, start, end, timeframe)

    alpaca_shaped = normalized_quotes_to_alpaca_shape(kept)
    rows: List[HistoricalRow] = merge_into_rows(alpaca_shaped, bars)

    root = data_root or _default_data_root()
    out_dir = root / "raw" / "alpaca" / symbol
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = _dataset_basename(symbol, start, end)
    csv_path = out_dir / f"{stem}.csv"
    meta_path = out_dir / f"{stem}.metadata.json"

    write_historical_csv(rows, str(csv_path))

    csv_relpath = os.path.relpath(csv_path, root)
    metadata = build_metadata(symbol, feed, start, end, stats, len(rows), csv_relpath)
    with open(meta_path, "w", newline="") as f:
        json.dump(metadata, f, indent=2, sort_keys=True)
        f.write("\n")

    return IngestionResult(
        symbol=symbol, feed=feed, start=start, end=end,
        csv_path=str(csv_path), metadata_path=str(meta_path),
        rows_written=len(rows), stats=stats,
    )


def _download_bars_best_effort(downloader: HistoricalQuoteDownloader, symbol: str,
                               start: str, end: str, timeframe: str) -> List[dict]:
    """
    Fetch bars for volume/last-price attribution. Best-effort: a failure here
    degrades to zero-volume rows rather than failing the whole quote ingest,
    since bars are an approximation layer, not the core L1 data.
    """
    url = f"{ALPACA_DATA_BASE_URL}/stocks/{symbol}/bars"
    page_token: Optional[str] = None
    bars: List[dict] = []
    pages = 0
    try:
        while True:
            pages += 1
            if pages > MAX_PAGES:
                LOGGER.warning("bar pagination hit page cap; using %d bars collected so far", len(bars))
                break
            params = {"start": start, "end": end, "timeframe": timeframe,
                      "limit": downloader._page_limit, "feed": downloader.feed}
            if page_token:
                params["page_token"] = page_token
            payload = downloader._get_page(url, params)
            bars.extend(payload.get("bars") or [])
            page_token = payload.get("next_page_token")
            if not page_token:
                break
        LOGGER.info("downloaded %d bar(s) for volume attribution", len(bars))
    except AlpacaHTTPError as exc:
        LOGGER.warning("bar download failed (%s); proceeding with zero-volume rows", exc)
        return []
    return bars


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_report(result: IngestionResult) -> None:
    s = result.stats
    print(f"Requested interval : {result.symbol} [{result.start} .. {result.end}) feed={result.feed}")
    print(f"Records downloaded : {s.records_downloaded}")
    print(f"Records retained   : {s.records_valid}")
    print(f"Rows written (CSV) : {result.rows_written}")
    print("Validation statistics:")
    for key, value in s.to_dict().items():
        if key in ("records_downloaded", "records_valid"):
            continue
        print(f"    {key:<28}: {value}")
    print(f"Output CSV         : {result.csv_path}")
    print(f"Metadata           : {result.metadata_path}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m python.alpaca_ingest",
        description="Download real Alpaca historical L1 quotes into a deterministic "
                    "CsvMarketSource-compatible dataset.",
    )
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--start", required=True, help="RFC-3339 UTC, e.g. 2024-01-03T14:30:00Z")
    parser.add_argument("--end", required=True, help="RFC-3339 UTC, e.g. 2024-01-03T15:30:00Z")
    parser.add_argument("--feed", default=DEFAULT_FEED,
                        help="Alpaca data feed (default: iex). Free tier is IEX; "
                             "do not switch to sip unless you have a paid plan.")
    parser.add_argument("--timeframe", default="1Min", help="Bar timeframe for volume attribution")
    parser.add_argument("--data-root", default=None, help="Override dataset root (default: <repo>/data)")
    parser.add_argument("--verbose", action="store_true", help="Log pagination/progress detail")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        result = ingest(
            symbol=args.symbol,
            start=args.start,
            end=args.end,
            feed=args.feed,
            timeframe=args.timeframe,
            data_root=Path(args.data_root) if args.data_root else None,
        )
    except (AlpacaAuthError, AlpacaHTTPError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    _print_report(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
