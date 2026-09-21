"""
No-lookahead / data-integrity validation.

An execution algorithm must never be able to act on market information that,
in real historical time, had not happened yet. This is the single most
important credibility property for historical execution research: if a
strategy could peek at future prices, every backtest number would be
meaningless.

This benchmark validates no-lookahead two independent ways:

  A. C++ REPLAY TESTS (authoritative): runs the existing GoogleTest
     no-lookahead assertions in tests/test_replay.cpp
     (test_no_lookahead, test_no_lookahead_after_seek) plus the
     chronological/validation and CSV-vs-event determinism cross-check
     tests, via --gtest_filter. These assert the ReplayController clock
     never precedes/exceeds the state it just returned, nothing before a
     seek() target is reachable, timestamps are strictly monotonic, and the
     event pipeline reproduces CsvMarketSource state-for-state.

  B. PYTHON TRUNCATION-INVARIANCE DEMONSTRATION (empirical, end-to-end):
     For a data-dependent strategy (POV and Adaptive size each child order
     from the CURRENT event only), we run the full real dataset, then run a
     truncated copy containing only the first K events. If any execution
     decision had used future data, truncating the future would change the
     early fills. We assert every fill at a timestamp <= t_K is byte-identical
     between the full run and the truncated run. Identical => no future
     information leaked backwards.

Reproduce:
    PYTHONPATH=build python3 benchmarks/no_lookahead.py
"""

from __future__ import annotations

import csv
import tempfile
from pathlib import Path

import harness as H
from gtest_util import run_gtest_binary

# The real dataset used for the empirical demonstration (has bar_volume so
# POV is data-dependent and meaningful).
DATASET = "data/raw/alpaca/AAPL/AAPL_2024-01-03_1430-1530_quotes.csv"
NO_LOOKAHEAD_TESTS = [
    "ReplayTest.test_no_lookahead",
    "ReplayTest.test_no_lookahead_after_seek",
    "ReplayTest.test_parse_produces_events_in_order",
    "ReplayTest.test_rejects_duplicate_timestamp",
    "ReplayTest.test_rejects_non_monotonic_timestamp",
    "ReplayTest.test_events_to_states_matches_csv_source",
]


def _fill_tuples(result):
    """Exact, comparable representation of every fill."""
    return [
        (f.timestamp_ms, repr(f.trade.price), f.trade.qty, repr(f.bid), repr(f.ask))
        for f in result.fills
    ]


def _write_truncated(src: Path, dst: Path, k_rows: int) -> int:
    """Copy header + first k_rows data rows. Returns the timestamp_ms of the
    last kept row."""
    with open(src, newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        ts_idx = header.index("timestamp_ms")
        rows = []
        last_ts = 0
        for i, row in enumerate(reader):
            if i >= k_rows:
                break
            rows.append(row)
            last_ts = int(row[ts_idx])
    with open(dst, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return last_ts


def _run(ex, du, dataset_path: Path, strategy: str):
    limit_buy, arrival = du.resolve_prices(dataset_path, None, None)
    source = ex.CsvMarketSource(str(dataset_path))
    session = ex.ExecutionSession()
    s = ex.OrderSide.Buy
    qty = 5000
    if strategy == "POV":
        return session.run_pov(source, s, qty, limit_buy, ex.POVAlgorithm(0.2, 1, 0), arrival)
    if strategy == "ADAPTIVE":
        return session.run_adaptive(source, s, qty, limit_buy, ex.AdaptiveAlgorithm(0.2, 5.0, 1, 1.0), arrival)
    raise ValueError(strategy)


def cpp_validation() -> dict:
    gfilter = ":".join(NO_LOOKAHEAD_TESTS)
    exe = H.build_dir() / "test_replay"
    if not exe.exists():
        return {"status": "missing", "reason": "test_replay binary not built"}
    import json as _json
    import subprocess
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "replay.json"
        proc = subprocess.run(
            [str(exe), f"--gtest_filter={gfilter}", f"--gtest_output=json:{out}"],
            cwd=H.REPO_ROOT, capture_output=True, text=True, timeout=300,
        )
        data = _json.loads(out.read_text())
    cases = []
    for suite in data.get("testsuites", []):
        for c in suite.get("testsuite", []):
            cases.append({"name": f"{suite['name']}.{c['name']}",
                          "passed": c.get("result") == "COMPLETED" and not c.get("failures")})
    return {
        "status": "ok",
        "returncode": proc.returncode,
        "tests_run": data.get("tests", 0),
        "failures": data.get("failures", 0),
        "all_passed": data.get("failures", 0) == 0 and proc.returncode == 0,
        "tests": cases,
    }


def truncation_invariance(ex, du) -> dict:
    dpath = H.REPO_ROOT / DATASET
    if not dpath.exists():
        return {"status": "missing", "dataset": DATASET}
    total_rows = H.count_data_rows(dpath)
    k = min(5000, total_rows // 2)  # keep first half (bounded)
    results = {}
    with tempfile.TemporaryDirectory() as td:
        trunc = Path(td) / "truncated.csv"
        last_ts = _write_truncated(dpath, trunc, k)
        for strat in ("POV", "ADAPTIVE"):
            full = _run(ex, du, dpath, strat)
            part = _run(ex, du, trunc, strat)
            full_fills = _fill_tuples(full)
            part_fills = _fill_tuples(part)
            # Fills from the full run that happened at or before the truncation
            # boundary must exactly equal all fills from the truncated run.
            full_prefix = [t for t in full_fills if t[0] <= last_ts]
            identical = full_prefix == part_fills
            results[strat] = {
                "truncated_at_row": k,
                "truncation_boundary_timestamp_ms": last_ts,
                "full_run_total_fills": len(full_fills),
                "full_run_fills_within_prefix": len(full_prefix),
                "truncated_run_fills": len(part_fills),
                "prefix_fills_identical": identical,
                "interpretation": (
                    "PASS - early fills are unchanged by removing future data, "
                    "so no execution decision used future information"
                    if identical else
                    "FAIL - early fills changed when future data was removed (lookahead!)"
                ),
            }
            print(f"  truncation-invariance {strat:<9} "
                  f"prefix_identical={identical} "
                  f"(full_prefix={len(full_prefix)} == truncated={len(part_fills)})", flush=True)
    return {"status": "ok", "dataset": DATASET,
            "dataset_sha256": H.sha256_file(dpath), "total_rows": total_rows,
            "per_strategy": results,
            "all_pass": all(r["prefix_fills_identical"] for r in results.values())}


def main() -> int:
    ex = H.import_executor()
    du = H.import_dataset_utils()

    print("[no-lookahead] C++ replay validation tests ...", flush=True)
    cpp = cpp_validation()
    print(f"  C++ replay tests: {cpp.get('tests_run')} run, {cpp.get('failures')} failures, "
          f"all_passed={cpp.get('all_passed')}", flush=True)

    print("[no-lookahead] Python truncation-invariance demonstration ...", flush=True)
    trunc = truncation_invariance(ex, du)

    overall = bool(cpp.get("all_passed")) and bool(trunc.get("all_pass"))
    payload = {
        "_meta": H.new_meta(
            "no_lookahead",
            "PYTHONPATH=build python3 benchmarks/no_lookahead.py",
            extra={
                "category": "OBSERVED (real test + real engine runs); property is data integrity, not performance",
                "property": "execution decisions can only use information available at or before the current replay time",
            },
        ),
        "overall_no_lookahead_validated": overall,
        "cpp_replay_validation": cpp,
        "truncation_invariance": trunc,
    }
    out = H.write_json("no_lookahead.json", payload)
    print(f"\nno-lookahead validated: {overall}. Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
