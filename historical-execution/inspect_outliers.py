import pandas as pd

path = "data/raw/alpaca/AAPL_2024-01-03_1430-1530_quotes.csv"

df = pd.read_csv(path)

# Only quotes with both sides populated
valid = df[
    (df["bid_price"] > 0) &
    (df["ask_price"] > 0)
].copy()

# Flag quotes that are far away from the main price region
outliers = valid[
    (valid["bid_price"] < 180) |
    (valid["ask_price"] > 190) |
    (valid["bid_price"] > 190) |
    (valid["ask_price"] < 180)
]

print(f"Total valid quotes: {len(valid):,}")
print(f"Potential outliers: {len(outliers):,}")

print("\n=== OUTLIER SAMPLE ===")
print(
    outliers[
        [
            "timestamp",
            "bid_price",
            "bid_size",
            "ask_price",
            "ask_size",
            "bid_exchange",
            "ask_exchange",
            "conditions",
        ]
    ].head(30).to_string(index=False)
)

print("\n=== MOST EXTREME BID QUOTES ===")
print(
    valid.nsmallest(10, "bid_price")[
        ["timestamp", "bid_price", "bid_size", "ask_price", "ask_size"]
    ].to_string(index=False)
)

print("\n=== MOST EXTREME ASK QUOTES ===")
print(
    valid.nlargest(10, "ask_price")[
        ["timestamp", "bid_price", "bid_size", "ask_price", "ask_size"]
    ].to_string(index=False)
)