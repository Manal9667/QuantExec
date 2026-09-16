import pandas as pd

path = "data/raw/alpaca/AAPL_2024-01-03_1430-1530_quotes.csv"

df = pd.read_csv(path)

print("=== BASIC INFO ===")
print(f"Rows: {len(df):,}")
print(f"Columns: {list(df.columns)}")

print("\n=== SYMBOLS ===")
print(df["symbol"].value_counts())

print("\n=== TIME RANGE ===")
print("Start:", df["timestamp"].min())
print("End:  ", df["timestamp"].max())

print("\n=== MISSING VALUES ===")
print(df.isna().sum())

print("\n=== ZERO BID/ASK ===")
zero_bid = (df["bid_price"] <= 0).sum()
zero_ask = (df["ask_price"] <= 0).sum()

print(f"Zero/invalid bid: {zero_bid:,}")
print(f"Zero/invalid ask: {zero_ask:,}")

print("\n=== INVALID SPREADS ===")
valid = df[
    (df["bid_price"] > 0) &
    (df["ask_price"] > 0)
]

crossed = (valid["bid_price"] > valid["ask_price"]).sum()

print(f"Valid quotes: {len(valid):,}")
print(f"Crossed quotes: {crossed:,}")

print("\n=== SPREAD ===")
valid = valid.copy()
valid["spread"] = valid["ask_price"] - valid["bid_price"]

print(valid["spread"].describe())

print("\n=== PRICES ===")
print(valid[["bid_price", "ask_price"]].describe())

print("\n=== SIZES ===")
print(valid[["bid_size", "ask_size"]].describe())