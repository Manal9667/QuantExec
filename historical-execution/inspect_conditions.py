import pandas as pd

path = "data/raw/alpaca/AAPL_2024-01-03_1430-1530_quotes.csv"

df = pd.read_csv(path)

df["timestamp"] = pd.to_datetime(
    df["timestamp"],
    utc=True,
    format="mixed"
)

df["spread"] = df["ask_price"] - df["bid_price"]

valid = df[
    (df["bid_price"] > 0) &
    (df["ask_price"] > 0) &
    (df["bid_price"] <= df["ask_price"])
].copy()

valid["minute"] = valid["timestamp"].dt.floor("min")

summary = (
    valid.groupby("minute")
    .agg(
        quotes=("spread", "size"),
        median_spread=("spread", "median"),
        large_spread=("spread", lambda x: (x > 1.0).sum()),
        huge_spread=("spread", lambda x: (x > 5.0).sum()),
    )
)

summary["large_pct"] = (
    summary["large_spread"] / summary["quotes"] * 100
)

print("=== SPREAD BY MINUTE ===")
print(summary.to_string())

print("\n=== FIRST 50 LARGE-SPREAD QUOTES ===")

large = valid[valid["spread"] > 1.0]

print(
    large[
        [
            "timestamp",
            "bid_price",
            "ask_price",
            "bid_size",
            "ask_size",
            "spread",
        ]
    ].head(50).to_string(index=False)
)

print("\n=== LAST 50 LARGE-SPREAD QUOTES ===")

print(
    large[
        [
            "timestamp",
            "bid_price",
            "ask_price",
            "bid_size",
            "ask_size",
            "spread",
        ]
    ].tail(50).to_string(index=False)
)