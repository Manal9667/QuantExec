"""
Generates datasets/sample_synthetic.csv.

This is a small, fully synthetic, deterministic (seed=42) top-of-book +
2-level-depth fixture used for local development, demos, and the example
experiment config. It is NOT real market data - see docs/DATASET.md for
where the real historical data pipeline lives (python/alpaca_historical.py)
and why no real dataset is committed to this repository.

Re-running this script produces byte-identical output every time.
"""

import random


def generate(path: str = "sample_synthetic.csv", num_rows: int = 15, seed: int = 42) -> None:
    random.seed(seed)

    rows = []
    price = 100.00
    ts = 0
    cum_vol = 0
    for _ in range(num_rows):
        ts += 1000  # 1 second per row
        price = round(price + random.uniform(-0.03, 0.03), 2)
        spread = 0.02
        bid = round(price - spread / 2, 2)
        ask = round(price + spread / 2, 2)
        bid_size = random.randint(200, 600)
        ask_size = random.randint(200, 600)
        bar_volume = random.randint(50, 300)
        cum_vol += bar_volume

        # Second depth level: slightly worse price, larger size - a
        # plausible (not real) shape for a lightly-liquid top few levels.
        bid2 = round(bid - 0.01, 2)
        ask2 = round(ask + 0.01, 2)
        bid2_size = random.randint(300, 800)
        ask2_size = random.randint(300, 800)

        rows.append([
            ts, price, bid, ask, bid_size, ask_size, cum_vol, bar_volume,
            f"{bid}:{bid_size}|{bid2}:{bid2_size}",
            f"{ask}:{ask_size}|{ask2}:{ask2_size}",
        ])

    header = "timestamp_ms,last,bid,ask,bid_size,ask_size,volume,bar_volume,bid_depth,ask_depth"
    with open(path, "w") as f:
        f.write(header + "\n")
        for row in rows:
            f.write(",".join(str(v) for v in row) + "\n")


if __name__ == "__main__":
    generate()
    print("Wrote sample_synthetic.csv")