"""
Download historical TRADE data (not OHLC bars) for AAPL over the same
window as download_quotes.py, using the Alpaca Python SDK.

*** NOT EXECUTED as part of this Phase 2 pass. ***
This environment has no ALPACA_API_KEY / ALPACA_SECRET_KEY and its network
egress allowlist does not include Alpaca's API host, so this script could
not actually be run here. It is written, reviewed, and ready to run
wherever both of those are available - run it exactly the way
download_quotes.py was previously run to produce the quotes CSV:

    export ALPACA_API_KEY=...      # never commit these; see .gitignore
    export ALPACA_SECRET_KEY=...
    python3 historical-execution/download_trades.py

Credentials are read from environment variables only (never hard-coded,
never printed). After running this for real, feed both the quotes and
trades raw CSVs into historical-execution/normalize.py (extend it to merge
trade prices into the `last`/`volume` columns instead of falling back to
the quote midpoint / zero, exactly as dataset.md's schema intends) before
re-running scripts/build_dataset_manifest.py.
"""
import os
from pathlib import Path
from datetime import datetime, timezone

from dotenv import load_dotenv
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockTradesRequest
from alpaca.data.enums import DataFeed

load_dotenv()

api_key = os.getenv("ALPACA_API_KEY")
secret_key = os.getenv("ALPACA_SECRET_KEY")

if not api_key or not secret_key:
    raise RuntimeError(
        "Alpaca credentials not found. Set ALPACA_API_KEY and ALPACA_SECRET_KEY "
        "as environment variables (e.g. in a local .env file, which is git-ignored "
        "- see historical-execution/.gitignore). Never hard-code credentials here."
    )

client = StockHistoricalDataClient(
    api_key=api_key,
    secret_key=secret_key,
)

# Same symbol, same date, same window as download_quotes.py so quotes and
# trades line up: 2024-01-03 14:30-15:30 UTC == 09:30-10:30 America/New_York.
request = StockTradesRequest(
    symbol_or_symbols=["AAPL"],
    start=datetime(2024, 1, 3, 14, 30, tzinfo=timezone.utc),
    end=datetime(2024, 1, 3, 15, 30, tzinfo=timezone.utc),
    feed=DataFeed.IEX,  # same feed as the quotes capture - keep both single-venue
)

trades = client.get_stock_trades(request)

df = trades.df.reset_index()

output_dir = Path("data/raw/alpaca")
output_dir.mkdir(parents=True, exist_ok=True)

output_path = output_dir / "AAPL_2024-01-03_1430-1530_trades.csv"

df.to_csv(output_path, index=False)

retrieval_ts = datetime.now(timezone.utc).isoformat()

print(f"Saved {len(df):,} trade records.")
print(f"Output: {output_path}")
print(f"Columns: {list(df.columns)}")
print(f"Retrieval timestamp (UTC): {retrieval_ts}")
print(
    "Reminder: record this retrieval timestamp, the feed (IEX), and the "
    "request window in a metadata file next to the output, matching the "
    "pattern in AAPL_2024-01-03_1430-1530_quotes.metadata.json."
)
