from pathlib import Path
import json

ROOT = Path(".")

print("=" * 70)
print("QUANTEXEC EXPERIMENT INVENTORY")
print("=" * 70)

# Search common experiment/output locations.
search_dirs = [
    Path("experiments"),
    Path("results"),
    Path("data/results"),
    Path("outputs"),
]

files = []

for directory in search_dirs:
    if directory.exists():
        files.extend(
            p for p in directory.rglob("*")
            if p.is_file()
        )

print(f"\nExperiment/result files found: {len(files):,}")

for path in files[:50]:
    print(f"  {path}")

# ---------------------------------------------------------
# JSON results
# ---------------------------------------------------------

json_files = [
    p for p in files
    if p.suffix.lower() == ".json"
]

print(f"\nJSON result files: {len(json_files):,}")

strategies = set()
symbols = set()
sides = set()
orders = 0

for path in json_files:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict):
            strategy = data.get("strategy")
            symbol = data.get("symbol")
            side = data.get("side")

            if strategy:
                strategies.add(str(strategy))

            if symbol:
                symbols.add(str(symbol))

            if side:
                sides.add(str(side))

            if "parent_quantity" in data:
                orders += 1

    except Exception:
        pass

print("\nDISCOVERED EXPERIMENT DIMENSIONS")
print("-" * 70)

print(f"Strategies: {sorted(strategies)}")
print(f"Symbols:    {sorted(symbols)}")
print(f"Sides:      {sorted(sides)}")
print(f"Orders:     {orders:,}")

print("\n" + "=" * 70)