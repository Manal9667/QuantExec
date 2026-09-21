import truststore
truststore.inject_into_ssl()

import os
import requests
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("ALPACA_API_KEY")
secret_key = os.getenv("ALPACA_SECRET_KEY")

if not api_key or not secret_key:
    raise RuntimeError("Alpaca credentials not found in .env")

url = "https://data.alpaca.markets/v2/stocks/AAPL/quotes"

params = {
    "start": "2024-01-03T14:30:00Z",
    "end": "2024-01-03T14:31:00Z",
    "feed": "iex",
    "limit": 10,
}

response = requests.get(
    url,
    headers={
        "APCA-API-KEY-ID": api_key,
        "APCA-API-SECRET-KEY": secret_key,
    },
    params=params,
)

print("Status:", response.status_code)

if response.ok:
    data = response.json()
    print("Quotes returned:", len(data.get("quotes", [])))
    print(data.get("quotes", [])[:2])
else:
    print(response.text)