import os
from pathlib import Path
from datetime import datetime, timezone

from dotenv import load_dotenv
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockQuotesRequest
from alpaca.data.enums import DataFeed

load_dotenv()

api_key = os.getenv("ALPACA_API_KEY")
secret_key = os.getenv("ALPACA_SECRET_KEY")

if not api_key or not secret_key:
    raise RuntimeError("Alpaca credentials not found in .env")

client = StockHistoricalDataClient(
    api_key=api_key,
    secret_key=secret_key,
)

request = StockQuotesRequest(
    symbol_or_symbols=["AAPL"],
    start=datetime(2024, 1, 3, 14, 30, tzinfo=timezone.utc),
    end=datetime(2024, 1, 3, 15, 30, tzinfo=timezone.utc),
    feed=DataFeed.IEX,
)

quotes = client.get_stock_quotes(request)

df = quotes.df.reset_index()

output_dir = Path("data/raw/alpaca")
output_dir.mkdir(parents=True, exist_ok=True)

output_path = output_dir / "AAPL_2024-01-03_1430-1530_quotes.csv"

df.to_csv(output_path, index=False)

print(f"Saved {len(df):,} quote records.")
print(f"Output: {output_path}")
print(f"Columns: {list(df.columns)}")