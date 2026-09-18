from pathlib import Path
import pandas as pd

PATH = Path(
    "data/raw/alpaca/AAPL_2024-01-03_1430-1530_quotes.csv"
)

df = pd.read_csv(PATH)

print("=" * 70)
print("QUANTEXEC MARKET DATA AUDIT")
print("=" * 70)

print(f"\nFile: {PATH}")
print(f"Raw records: {len(df):,}")
print(f"Columns: {list(df.columns)}")

# ---------------------------------------------------------
# Timestamp
# ---------------------------------------------------------

df["timestamp"] = pd.to_datetime(
    df["timestamp"],
    utc=True,
    format="mixed"
)

print("\nTIME")
print("-" * 70)
print(f"Start: {df['timestamp'].min()}")
print(f"End:   {df['timestamp'].max()}")
print(
    f"Duration: "
    f"{df['timestamp'].max() - df['timestamp'].min()}"
)

# ---------------------------------------------------------
# Basic validity
# ---------------------------------------------------------

has_bid = df["bid_price"] > 0
has_ask = df["ask_price"] > 0

two_sided = has_bid & has_ask
one_sided_or_empty = ~two_sided

crossed = (
    two_sided &
    (df["bid_price"] > df["ask_price"])
)

valid_two_sided = two_sided & ~crossed

invalid_size = (
    (df["bid_size"] <= 0) |
    (df["ask_size"] <= 0)
)

print("\nQUOTE VALIDATION")
print("-" * 70)

print(f"Two-sided quotes:       {two_sided.sum():,}")
print(f"One-sided/empty:        {one_sided_or_empty.sum():,}")
print(f"Crossed quotes:         {crossed.sum():,}")
print(f"Invalid sizes:          {invalid_size.sum():,}")
print(f"Valid two-sided:        {valid_two_sided.sum():,}")

# ---------------------------------------------------------
# Percentages
# ---------------------------------------------------------

total = len(df)

print("\nPERCENTAGES")
print("-" * 70)

print(
    f"Two-sided:              "
    f"{two_sided.mean() * 100:.4f}%"
)

print(
    f"One-sided/empty:        "
    f"{one_sided_or_empty.mean() * 100:.4f}%"
)

print(
    f"Crossed:                "
    f"{crossed.sum() / total * 100:.4f}%"
)

# ---------------------------------------------------------
# Valid quote statistics
# ---------------------------------------------------------

valid = df.loc[valid_two_sided].copy()

valid["spread"] = (
    valid["ask_price"] -
    valid["bid_price"]
)

valid["mid_price"] = (
    valid["ask_price"] +
    valid["bid_price"]
) / 2

print("\nVALID QUOTE STATISTICS")
print("-" * 70)

print(
    f"Median spread:          "
    f"${valid['spread'].median():.4f}"
)

print(
    f"Mean spread:            "
    f"${valid['spread'].mean():.4f}"
)

print(
    f"Maximum spread:         "
    f"${valid['spread'].max():.4f}"
)

print(
    f"Median bid size:        "
    f"{valid['bid_size'].median():.2f}"
)

print(
    f"Median ask size:        "
    f"{valid['ask_size'].median():.2f}"
)

print(
    f"Maximum bid size:       "
    f"{valid['bid_size'].max():.0f}"
)

print(
    f"Maximum ask size:       "
    f"{valid['ask_size'].max():.0f}"
)

# ---------------------------------------------------------
# Symbols
# ---------------------------------------------------------

print("\nSYMBOLS")
print("-" * 70)

print(df["symbol"].value_counts().to_string())

# ---------------------------------------------------------
# Spread buckets
# ---------------------------------------------------------

print("\nSPREAD DISTRIBUTION")
print("-" * 70)

for threshold in [0.01, 0.05, 0.10, 0.25, 0.50, 1.00, 5.00]:
    count = (valid["spread"] > threshold).sum()
    pct = count / len(valid) * 100

    print(
        f"Spread > ${threshold:>4.2f}: "
        f"{count:>8,} ({pct:>6.2f}%)"
    )

print("\n" + "=" * 70)
print("AUDIT COMPLETE")
print("=" * 70)