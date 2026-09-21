# Historical Market-Data Ingestion (Alpaca -> CsvMarketSource)

QuantExec can download **real historical market data** from Alpaca, normalize
and validate it, save it as a deterministic dataset, and feed that dataset
directly into the existing C++ `CsvMarketSource` / `ExecutionSession` pipeline.
The C++ execution engine remains the source of truth for execution; this is a
data-ingestion layer, not a new simulator.

```
Alpaca Historical API  (GET /v2/stocks/{symbol}/quotes, IEX feed)
        |
HistoricalQuoteDownloader     pagination, retry, timeout, loop guard
        |
normalize_quotes()            Alpaca {t,ax,ap,as,bx,bp,bs,c} -> NormalizedQuote
        |
validate_quotes()             data-quality classification + statistics
        |
merge_into_rows()             join coarse bar volume onto quote ticks
write_historical_csv()        the Phase-1 CSV schema, unchanged
        |
CsvMarketSource -> ExecutionSession -> TWAP / VWAP / POV -> analytics
```

Implementation: [`python/alpaca_ingest.py`](../python/alpaca_ingest.py). It
reuses the project's single Alpaca field-mapping helper (`quote_to_top_of_book`
via `_parse_rfc3339_to_ms`), the `HistoricalRow` dataclass, `merge_into_rows()`
and `write_historical_csv()` from
[`python/alpaca_historical.py`](../python/alpaca_historical.py) rather than
duplicating them.

## What this data actually is (L1 limitation)

Alpaca's **free tier** exposes the **IEX feed** only. The `/quotes` endpoint
returns **Level 1 (top-of-book) NBBO quotes** from IEX: exactly one bid level
and one ask level per tick.

- This is **historical L1 quote replay**.
- It is **NOT** a reconstruction of a full historical exchange order book.
- No market depth is fabricated. Every row has a single bid level and a single
  ask level, the same as the real-time adapter.
- `volume` and `last` are **approximated** from the coarser 1-minute bars
  endpoint and joined onto quote ticks by `merge_into_rows()` (a bar's volume
  is attributed to the first quote after that bar closes; `last` is that bar's
  close). Quotes carry no trade/volume data on their own.

Do not describe the resulting dataset as L2 or full-depth. If genuine depth
data is added later, this document should be updated.

## Credentials & security

- Credentials load from the repo-root `.env` (kept **gitignored**):

  ```
  ALPACA_API_KEY=...
  ALPACA_SECRET_KEY=...
  ```

  Loaded via `python-dotenv`; sent as Alpaca's `APCA-API-KEY-ID` /
  `APCA-API-SECRET-KEY` headers. Credentials are **never** printed, logged, or
  written into dataset metadata.
- **TLS verification stays ON.** `verify=False` is never used. The module
  injects [`truststore`](https://pypi.org/project/truststore/) at import so
  Python uses the OS trust store (required on this Windows setup) while keeping
  certificate verification enabled.
- The IEX feed is passed **explicitly** on every request. The pipeline never
  silently switches to SIP (a paid feed).

## CSV schema

The generated CSV uses the exact schema `CsvMarketSource` (`src/market_data.cpp`)
has consumed since Phase 1:

| column         | meaning                                              |
| -------------- | ---------------------------------------------------- |
| `timestamp_ms` | quote time, epoch milliseconds (strictly increasing) |
| `last`         | last price (approx: covering bar's close)            |
| `bid`          | top-of-book bid price                                |
| `ask`          | top-of-book ask price                                |
| `bid_size`     | bid size in **shares** (round lots x 100)            |
| `ask_size`     | ask size in **shares**                               |
| `volume`       | cumulative volume as of this row (approx, from bars) |
| `bar_volume`   | volume attributed to this row only (approx)          |

`CsvMarketSource` requires `timestamp_ms, last, bid, ask, bid_size, ask_size,
volume` and treats `bar_volume` (and `bid_depth` / `ask_depth`) as optional.

## Data-quality validation

Real IEX quotes contain records the C++ engine will not accept. `CsvMarketSource`
**rejects the entire file** if any row has a non-finite or non-positive price,
`bid > ask` (crossed), or a non-monotonic timestamp (duplicate / out-of-order).
So `validate_quotes()` cleans the stream before writing and reports exactly what
it dropped. Each downloaded record gets exactly one disposition (kept-valid or a
single rejection reason), so:

```
records_downloaded == records_valid + sum(rejection buckets)
```

Rejection buckets (checked in this order): `one_sided_quotes`,
`non_positive_price_quotes`, `zero_size_quotes`, `crossed_quotes`,
`locked_quotes` (bid == ask), `duplicate_quotes`, `out_of_order_quotes`.
`wide_spread_quotes` is a non-rejecting **flag**: a quote whose
`(ask - bid) / mid` exceeds **5%** (`WIDE_SPREAD_FRACTION`) is counted but still
kept, because wide spreads are legitimate for thin names or around the open.

Pagination is bounded by `MAX_PAGES = 5000` and a repeated-`next_page_token`
guard, so a broken response can never cause an infinite loop or a silently
truncated dataset (both raise a clear error instead).

### Timestamp resolution note

IEX quotes have sub-millisecond timestamps, but the CSV schema and
`CsvMarketSource` operate at **millisecond** resolution and require strictly
increasing timestamps. Multiple distinct sub-ms quotes that fall in the same
millisecond therefore collapse to one, and the extras are reported as
`duplicate_quotes`. This is expected: it is the cost of the ms-resolution replay
schema, not lost/corrupt data. For the sample AAPL hour below, 325,196 raw
quotes reduce to 171,293 one-per-ms rows.

## Output layout & metadata

```
data/
  raw/
    alpaca/
      AAPL/
        AAPL_2024-01-03_1430-1530_quotes.csv
        AAPL_2024-01-03_1430-1530_quotes.metadata.json
```

The filename stem is derived deterministically from the requested interval, so
the same request maps to the same path. Metadata is credential-free and records
`source`, `feed`, `data_level: "L1"`, symbol, start/end, `downloaded_at`, row
counts, the full `validation` statistics, and a plain-language `limitations`
note. It makes each dataset reproducible and auditable.

## CLI — reproducing a dataset

Run from the repo root with the compiled `executor` on the path:

```powershell
# PowerShell (Windows)
$env:PYTHONPATH = "build/Release;."
python -m python.alpaca_ingest `
    --symbol AAPL `
    --start 2024-01-03T14:30:00Z `
    --end   2024-01-03T15:30:00Z `
    --feed  iex `
    --verbose
```

```bash
# bash (Linux/macOS)
PYTHONPATH=build:. python -m python.alpaca_ingest \
    --symbol AAPL \
    --start 2024-01-03T14:30:00Z \
    --end   2024-01-03T15:30:00Z \
    --feed  iex --verbose
```

The command prints the requested interval, records downloaded, records
retained, rows written, the full validation statistics, and the output CSV +
metadata paths.

Once a dataset exists, run a controlled TWAP-vs-VWAP comparison over it with the
existing entry point:

```powershell
python -m python.run_phase3_backtest data/raw/alpaca/AAPL/AAPL_2024-01-03_1430-1530_quotes.csv --qty 5000 --slices 6
```

## Testing

- **Offline suite (default, never touches the network):**
  - [`python/test_alpaca_historical.py`](../python/test_alpaca_historical.py) —
    existing merge/CSV/TWAP-vs-VWAP/reproducibility tests (unchanged).
  - [`python/test_alpaca_ingest.py`](../python/test_alpaca_ingest.py) — new:
    pagination + loop guard, ordering/de-dup, mocked HTTP errors (no credential
    leak), retryable-then-success, normalization, validation of every defect
    class, deterministic byte-for-byte serialization, metadata has no
    credentials, and an end-to-end ingest round-tripped through the **real** C++
    `CsvMarketSource` + `ExecutionSession`.

  ```powershell
  $env:PYTHONPATH = "build/Release;."
  python -m pytest python/test_alpaca_ingest.py -v
  python -m python.test_alpaca_historical
  ```

- **Live smoke test (opt-in, hits the real API):**
  [`python/test_alpaca_live_smoke.py`](../python/test_alpaca_live_smoke.py).
  Skipped unless `QUANTEXEC_LIVE=1` **and** credentials are present, so the
  normal suite stays offline.

  ```powershell
  $env:QUANTEXEC_LIVE = "1"; $env:PYTHONPATH = "build/Release;."
  python -m pytest python/test_alpaca_live_smoke.py -v -s
  ```

## Reference dataset (verified)

Downloaded and verified with the CLI command above:

| field                | value                                             |
| -------------------- | ------------------------------------------------- |
| symbol / interval    | AAPL, 2024-01-03 14:30–15:30 UTC, IEX             |
| pages fetched        | 33                                                |
| records downloaded   | 325,196                                           |
| records retained     | 171,293                                           |
| one-sided quotes     | 126                                               |
| duplicate (same ms)  | 153,777                                           |
| wide-spread (flagged, kept) | 24,402                                     |
| crossed / locked / zero-size / out-of-order | 0                         |
| CSV size             | ~8.6 MB (9,029,317 bytes)                         |

`CsvMarketSource` loaded all 171,293 states (first bid/ask 184.29 / 184.32, last
183.95 / 183.96). TWAP and VWAP both executed against it and produced fills;
`market_price_drift` was identical (-0.1899%) across both strategies on the
identical dataset, and results were byte-identical across repeated runs.
