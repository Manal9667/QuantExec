"""
Order-book correctness / stress benchmark.

Runs the REAL C++ GoogleTest suites that exercise order-book and matching
correctness and reports how many deterministic scenarios pass. These are the
existing, authoritative correctness tests (tests/test_book.cpp,
test_engine.cpp, test_stress.cpp, test_algorithms.cpp, test_costs.cpp) - we
do not re-implement matching checks in Python, we run the engine's own tests
and count results from their machine-readable JSON.

Coverage the suites provide (verified by test-case names, listed in the
output): market orders, limit orders, partial fills, multi-level fills,
price-time priority, cancellations, insufficient liquidity, multiple orders,
and different order sizes - plus stressed-market conditions (wide spread,
thin liquidity, price gaps, zero volume, rapid price change) via test_stress.

Reports scenarios / passed / failed / skipped, execution time, and a
scenarios/second figure. NOTE: these scenarios are microbenchmarks that
complete near the timer floor, so scenarios/second is dominated by
process + test-framework startup and should be read as a lower bound, not a
raw engine-operation rate (that is what engine_throughput.py measures).

Reproduce:
    python3 benchmarks/orderbook_correctness.py
"""

from __future__ import annotations

import harness as H
from gtest_util import run_gtest_binary

# Correctness/stress suites (subset of the 10 ctest suites focused on
# order-book + matching + execution correctness).
CORRECTNESS_SUITES = [
    "test_book",       # order book structure, ordering, mid, depth, cancel
    "test_engine",     # matching: market/limit, partial, multi-level, price-time priority
    "test_stress",     # stressed market conditions on real edge-case fixtures
    "test_algorithms", # TWAP/VWAP/POV/Adaptive sizing correctness
    "test_costs",      # transaction cost calculation correctness
]

# Requirement -> substrings we expect to see among the test-case names, so the
# report can show each required behavior is actually covered by a real test.
REQUIRED_BEHAVIORS = {
    "market_orders": ["market"],
    "limit_orders": ["limit"],
    "partial_fills": ["partial"],
    "multi_level_fills": ["multi", "level", "sweep", "walk"],
    "price_time_priority": ["priority", "fifo", "time"],
    "cancellations": ["cancel"],
    "insufficient_liquidity": ["insufficient", "liquidity", "no_liquidity", "unfilled"],
    "multiple_orders": ["multiple", "orders"],
    "different_order_sizes": ["size", "large", "small", "huge"],
}


def main() -> int:
    suites = []
    all_case_names = []
    for name in CORRECTNESS_SUITES:
        res = run_gtest_binary(name)
        suites.append(res)
        if res.get("status") == "ok":
            all_case_names += [f"{c['suite']}.{c['name']}".lower() for c in res["cases"]]
            print(f"  {name:<16} scenarios={res['scenarios']:>3} passed={res['passed']:>3} "
                  f"failed={res['failed']} skipped={res['skipped']} wall={res['wall_time_s']}s", flush=True)
        else:
            print(f"  {name:<16} {res['status']}", flush=True)

    ok_suites = [s for s in suites if s.get("status") == "ok"]
    total_scenarios = sum(s["scenarios"] for s in ok_suites)
    total_passed = sum(s["passed"] for s in ok_suites)
    total_failed = sum(s["failed"] for s in ok_suites)
    total_skipped = sum(s["skipped"] for s in ok_suites)
    total_wall = sum(s["wall_time_s"] for s in ok_suites)

    # Which required behaviors are demonstrably covered by a named test case.
    behavior_coverage = {}
    for behavior, keys in REQUIRED_BEHAVIORS.items():
        matches = [n for n in all_case_names if any(k in n for k in keys)]
        behavior_coverage[behavior] = {
            "covered": len(matches) > 0,
            "example_tests": matches[:3],
        }

    payload = {
        "_meta": H.new_meta(
            "orderbook_correctness",
            "python3 benchmarks/orderbook_correctness.py",
            extra={
                "source": "real C++ GoogleTest suites (tests/test_*.cpp) via --gtest_output=json",
                "category": "OBSERVED (pass/fail from actually running the engine's own tests)",
                "throughput_caveat": (
                    "scenarios_per_second includes process/test-framework startup and is a "
                    "lower bound; see engine_throughput.py for raw engine event throughput."
                ),
            },
        ),
        "summary": {
            "suites": len(ok_suites),
            "scenarios": total_scenarios,
            "passed": total_passed,
            "failed": total_failed,
            "skipped": total_skipped,
            "all_passed": total_failed == 0 and len(ok_suites) == len(CORRECTNESS_SUITES),
            "total_wall_time_s": round(total_wall, 4),
            "scenarios_per_second": round(total_scenarios / total_wall, 1) if total_wall > 0 else None,
        },
        "required_behavior_coverage": behavior_coverage,
        "suites": suites,
    }
    out = H.write_json("orderbook_correctness.json", payload)
    print(f"\n{total_passed}/{total_scenarios} scenarios passed across {len(ok_suites)} suites. Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
