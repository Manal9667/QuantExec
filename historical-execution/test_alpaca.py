import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockQuotesRequest
from alpaca.data.enums import DataFeed

load_dotenv()

client = StockHistoricalDataClient(
    api_key=os.getenv("ALPACA_API_KEY"),
    secret_key=os.getenv("ALPACA_SECRET_KEY"),
)

request = StockQuotesRequest(
    symbol_or_symbols=["AAPL"],
    start=datetime(2024, 1, 3, 14, 30, tzinfo=timezone.utc),
    end=datetime(2024, 1, 3, 14, 35, tzinfo=timezone.utc),
    limit=10,
    feed=DataFeed.IEX,
)

quotes = client.get_stock_quotes(request)

print("Type:", type(quotes))
print("\n--- RAW RESULT ---")
print(quotes)

print("\n--- DATAFRAME ---")
print(quotes.df)

print("\n--- COLUMNS ---")
print(quotes.df.columns.tolist())

print("\n--- SHAPE ---")
print(quotes.df.shape)