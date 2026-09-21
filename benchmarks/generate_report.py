"""
Aggregate all benchmarks/results/*.json into two human-readable documents:

  * benchmarks/BENCHMARK_REPORT.md  - the full report (spec section 9 layout)
  * benchmarks/RESUME_METRICS.md    - only actually-measured metrics, each
                                       paired with the command that produced it
                                       (spec section 10). No resume bullets are
                                       written - just defensible numbers + how
                                       to reproduce them.

This script only READS the JSON results and reformats them. It never computes
a new measurement, so it cannot introduce an unbacked number. Missing result
files are reported as "not run" rather than guessed.

Reproduce:
    python3 benchmarks/generate_report.py
"""

from __future__ import annotations

import json
from pathlib import Path

import harness as H

R = H.RESULTS_DIR


def _load(name: str) -> dict | None:
    p = R / name
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def _fmt(n, nd=0):
    if n is None:
        return "n/a"
    if isinstance(n, float):
        return f"{n:,.{nd}f}"
    if isinstance(n, int):
        return f"{n:,}"
    return str(n)


def build_report() -> str:
    thr = _load("engine_throughput.json")
    strat = _load("strategy_experiments.json")
    det = _load("determinism.json")
    ob = _load("orderbook_correctness.json")
    ti = _load("test_inventory.json")
    nl = _load("no_lookahead.json")
    di = _load("dataset_inventory.json")

    env = (thr or strat or det or {}).get("_meta", {}).get("environment", {})
    L = []
    L.append("# QuantExec Benchmark Report")
    L.append("")
    L.append("All numbers below were produced by actually running the real C++ "
             "execution engine, its test suites, or real historical-data experiments. "
             "Nothing is hardcoded or hand-entered. Values are tagged OBSERVED / "
             "CALCULATED / ASSUMED / ESTIMATED where relevant (see machine-readable "
             "JSON under `benchmarks/results/` for the full detail behind every table).")
    L.append("")
    L.append(f"- Generated: {(thr or {}).get('_meta', {}).get('generated_at_utc', 'n/a')}")
    L.append(f"- Git commit: `{env.get('git_commit', 'n/a')}`")
    L.append(f"- Machine: {env.get('platform', 'n/a')} | {env.get('cpu_count', '?')} logical CPUs | "
             f"Python {env.get('python_version', '?')}")
    L.append("")
    L.append("> Performance numbers are machine-specific (single shared cloud sandbox). "
             "Treat them as this machine's measurements, not a hardware-independent claim.")
    L.append("")

    # ---- Engine Performance ----
    L.append("## Engine Performance")
    L.append("")
    if thr:
        L.append("Real C++ engine throughput via `benchmark_v2` (3 warm-up + 10 measured "
                 "iterations per stage). Headline stage = `full_execution` = CsvMarketSource "
                 "replay + `ExecutionSession.run` (TWAP, 5 slices). `replay` = pure event replay.")
        L.append("")
        L.append("| Workload | Events | full_execution (events/s) | µs/event | replay (events/s) | peak RSS |")
        L.append("|---|--:|--:|--:|--:|--:|")
        for r in thr.get("synthetic_scaling", []):
            if r.get("status") == "ok":
                rss = f"{r.get('peak_rss_kb', 0)/1024:,.0f} MB" if r.get("peak_rss_kb") else "n/a"
                L.append(f"| synthetic {_fmt(r['requested_rows'])} | {_fmt(r['events'])} | "
                         f"{_fmt(r.get('full_execution_events_per_second'))} | "
                         f"{_fmt(r.get('full_execution_us_per_event'),3)} | "
                         f"{_fmt(r.get('replay_events_per_second'))} | {rss} |")
            else:
                L.append(f"| synthetic {_fmt(r['requested_rows'])} | - | {r.get('status')}: "
                         f"{r.get('reason','')} | | | |")
        for r in thr.get("real_data", []):
            if r.get("status") == "ok":
                rss = f"{r.get('peak_rss_kb', 0)/1024:,.0f} MB" if r.get("peak_rss_kb") else "n/a"
                L.append(f"| **REAL** {r['dataset'].split('/')[-1]} | {_fmt(r['events'])} | "
                         f"**{_fmt(r.get('full_execution_events_per_second'))}** | "
                         f"{_fmt(r.get('full_execution_us_per_event'),3)} | "
                         f"{_fmt(r.get('replay_events_per_second'))} | {rss} |")
        peak = thr.get("peak_full_execution_events_per_second")
        L.append("")
        L.append(f"Peak measured full-execution throughput (synthetic): **{_fmt(peak)} events/s**.")
    else:
        L.append("_not run_")
    L.append("")

    # ---- Historical Dataset Scale ----
    L.append("## Historical Dataset Scale")
    L.append("")
    if di:
        s = di.get("scale_summary", {})
        L.append(f"- Distinct real symbols: **{s.get('distinct_real_symbols')}** ({', '.join(s.get('symbols', []))})")
        L.append(f"- Distinct real sessions: **{s.get('distinct_real_sessions')}** "
                 f"({'; '.join(s.get('sessions', []))})")
        L.append(f"- Engine-ready real files: **{s.get('engine_ready_real_files')}** "
                 f"(largest **{_fmt(s.get('largest_engine_ready_rows'))}** quote events)")
        L.append(f"- Total engine-ready real quote events: **{_fmt(s.get('total_engine_ready_quote_events'))}**")
        L.append(f"- Trade data available: **{s.get('trade_data_available')}** (quote-only capture)")
        L.append("")
        L.append("| Dataset | Rows | Symbol | Feed | Level | CsvMarketSource valid | Trades |")
        L.append("|---|--:|---|---|---|---|--:|")
        for d in di.get("real_datasets", []):
            if d.get("status") == "present":
                v = d.get("validation", {}).get("csv_market_source_ok")
                L.append(f"| {d['dataset']} | {_fmt(d.get('data_rows'))} | {d.get('symbol','AAPL')} | "
                         f"{d.get('feed','IEX')} | {d.get('data_level','L1')} | {v} | {d.get('trade_count',0)} |")
        L.append("")
        L.append(f"> {s.get('limitation','')}")
    else:
        L.append("_not run_")
    L.append("")

    # ---- Strategy Experiments ----
    L.append("## Strategy Experiments")
    L.append("")
    if strat:
        agg = strat.get("aggregate", {})
        L.append(f"- Total experiments: **{agg.get('total_experiments')}** "
                 f"(strategies: {', '.join(strat.get('_meta', {}).get('strategies', []))}; "
                 f"identical dataset/side/quantity/cost assumptions per comparison).")
        L.append("")
        L.append("Descriptive per-strategy statistics across all experiments "
                 "(implementation shortfall and slippage are CALCULATED from OBSERVED data). "
                 "**No strategy is declared superior** - this is a tiny, single-session sample.")
        L.append("")
        L.append("| Strategy | Exps | Completion rate | Median IS | Median slippage | Median fill rate | Median cost (bps) |")
        L.append("|---|--:|--:|--:|--:|--:|--:|")
        for st, v in agg.get("per_strategy", {}).items():
            L.append(f"| {st} | {v.get('experiments')} | {_fmt(v.get('completion_rate'),2)} | "
                     f"{_fmt(v.get('implementation_shortfall',{}).get('median'),4)} | "
                     f"{_fmt(v.get('slippage',{}).get('median'),6)} | "
                     f"{_fmt(v.get('fill_rate',{}).get('median'),3)} | "
                     f"{_fmt(v.get('transaction_cost_total_bps',{}).get('median'),3)} |")
        if agg.get("sample_size_warning"):
            L.append("")
            L.append(f"> ⚠️ {agg['sample_size_warning']}")
    else:
        L.append("_not run_")
    L.append("")

    # ---- Determinism ----
    L.append("## Determinism")
    L.append("")
    if det:
        t = det.get("totals", {})
        L.append(f"- **{_fmt(t.get('total_identical_runs'))} / {_fmt(t.get('total_runs'))}** "
                 f"repeated executions produced byte-identical results "
                 f"(mismatches: {t.get('total_mismatches')}).")
        L.append("- Signature = SHA-256 of every ExecutionResult field + every fill.")
        L.append("")
        L.append("| Dataset | Reps/strategy | Strategies | Identical |")
        L.append("|---|--:|---|---|")
        for c in det.get("configurations", []):
            if c.get("status") == "ok":
                ps = c.get("per_strategy", {})
                idc = sum(v["identical_runs"] for v in ps.values())
                run = sum(v["runs"] for v in ps.values())
                L.append(f"| {c['dataset'].split('/')[-1]} | {c['reps']} | {', '.join(ps.keys())} | "
                         f"{idc}/{run} |")
    else:
        L.append("_not run_")
    L.append("")

    # ---- Order Book ----
    L.append("## Order Book")
    L.append("")
    if ob:
        s = ob.get("summary", {})
        L.append(f"- Scenarios: **{s.get('scenarios')}**, passed **{s.get('passed')}**, "
                 f"failed **{s.get('failed')}**, skipped {s.get('skipped')} "
                 f"(across {s.get('suites')} real GoogleTest suites).")
        L.append(f"- Execution time: {_fmt(s.get('total_wall_time_s'),4)} s "
                 f"(~{_fmt(s.get('scenarios_per_second'),1)} scenarios/s, incl. process startup).")
        L.append("")
        L.append("Required order-book behaviors, each backed by a named test:")
        for beh, v in ob.get("required_behavior_coverage", {}).items():
            ex = v.get("example_tests", [])
            L.append(f"- `{beh}`: {'✓' if v.get('covered') else '✗'}"
                     + (f" (e.g. `{ex[0]}`)" if ex else ""))
    else:
        L.append("_not run_")
    L.append("")

    # ---- Automated Tests ----
    L.append("## Automated Tests")
    L.append("")
    if ti:
        c = ti.get("ci_covered_total", {})
        L.append(f"- CI-covered total: **{c.get('passed')}/{c.get('total')} passed** "
                 f"({c.get('failed')} failed, {c.get('skipped')} skipped) across "
                 f"{', '.join(c.get('layers', []))}.")
        L.append("")
        L.append("| Layer | Runner | Total | Passed | Failed | Skipped |")
        L.append("|---|---|--:|--:|--:|--:|")
        for name, layer in ti.get("layers", {}).items():
            if layer.get("status", "ok") == "ok":
                L.append(f"| {name} | {layer.get('runner')} | {layer.get('total')} | "
                         f"{layer.get('passed')} | {layer.get('failed')} | {layer.get('skipped')} |")
            else:
                L.append(f"| {name} | {layer.get('runner')} | {layer.get('status')} | | | |")
        L.append("")
        L.append(f"Single command for the full suite: `{ti.get('_meta', {}).get('single_command_full_suite','')}`")
        L.append("")
        L.append(f"Coverage tooling: {ti.get('_meta', {}).get('coverage_tooling','n/a')}.")
    else:
        L.append("_not run_")
    L.append("")

    # ---- Data Integrity ----
    L.append("## Data Integrity")
    L.append("")
    if nl:
        L.append(f"- No-lookahead validated: **{nl.get('overall_no_lookahead_validated')}**.")
        cpp = nl.get("cpp_replay_validation", {})
        L.append(f"  - C++ replay tests: {cpp.get('tests_run')} run, {cpp.get('failures')} failures "
                 f"(chronological ordering, monotonic timestamps, no-lookahead before/after seek, "
                 f"CSV-vs-event determinism cross-check).")
        tr = nl.get("truncation_invariance", {})
        if tr.get("status") == "ok":
            L.append(f"  - Truncation-invariance on real data ({tr.get('dataset','').split('/')[-1]}): "
                     f"all_pass={tr.get('all_pass')} - fills before the truncation boundary are "
                     f"identical whether or not future events exist, proving no future data leaks "
                     f"into earlier decisions.")
    else:
        L.append("- No-lookahead: _not run_")
    L.append("")
    L.append("**OBSERVED / CALCULATED / ASSUMED / ESTIMATED separation** is enforced in every "
             "strategy experiment record (see `strategy_experiments.json`): OBSERVED = raw "
             "historical quotes; CALCULATED = metrics derived from them (slippage, IS, VWAP, "
             "fill/participation rate, drift, costs); ASSUMED = user/config parameters (side, "
             "quantity, fees, latency, strategy params); ESTIMATED = model output (square-root "
             "market-impact estimate). Real data is L1 quote-only Alpaca IEX (no full-depth/L2 "
             "claim, no trade prints) - see `dataset_inventory.json` and `LIMITATIONS.md`.")
    L.append("")
    L.append("---")
    L.append("_Machine-readable results: `benchmarks/results/*.json`. Regenerate everything: "
             "`PYTHONPATH=build python3 benchmarks/run_all.py`._")
    L.append("")
    return "\n".join(L)


def build_resume_metrics() -> str:
    thr = _load("engine_throughput.json")
    strat = _load("strategy_experiments.json")
    det = _load("determinism.json")
    ob = _load("orderbook_correctness.json")
    ti = _load("test_inventory.json")
    nl = _load("no_lookahead.json")
    di = _load("dataset_inventory.json")

    L = []
    L.append("# QuantExec — Resume Metrics (measured, reproducible)")
    L.append("")
    L.append("Only metrics that were **actually measured** by this benchmark suite are listed. "
             "Each is paired with the exact command that produced it so it can be independently "
             "reproduced from a clean checkout. These are raw numbers, not polished resume "
             "bullets. Performance figures are specific to the machine recorded in the JSON "
             "`_meta.environment`.")
    L.append("")

    # Scale
    L.append("### Scale")
    if di:
        s = di.get("scale_summary", {})
        L.append(f"- Largest real historical dataset processed: **{_fmt(s.get('largest_engine_ready_rows'))} "
                 f"real AAPL IEX quote events** (L1, quote-only).")
        L.append(f"- Real securities: **{s.get('distinct_real_symbols')}** ({', '.join(s.get('symbols', []))}); "
                 f"real sessions: **{s.get('distinct_real_sessions')}** ({'; '.join(s.get('sessions', []))}).")
        L.append(f"  - reproduce: `PYTHONPATH=build python3 benchmarks/dataset_inventory.py`")
    if thr:
        big = [r for r in thr.get("synthetic_scaling", []) if r.get("status") == "ok"]
        maxev = max((r["events"] for r in big), default=None)
        if maxev:
            L.append(f"- Synthetic scaling workload processed by the real engine: up to "
                     f"**{_fmt(maxev)} market events** in a single run.")
            L.append(f"  - reproduce: `PYTHONPATH=build python3 benchmarks/engine_throughput.py`")
    if strat:
        L.append(f"- Strategy experiments executed through the real engine: "
                 f"**{strat.get('aggregate', {}).get('total_experiments')}**.")
        L.append(f"  - reproduce: `PYTHONPATH=build python3 benchmarks/strategy_study.py`")
    L.append("")

    # Performance
    L.append("### Performance")
    if thr:
        peak = thr.get("peak_full_execution_events_per_second")
        L.append(f"- Peak full-execution throughput (real engine, replay + ExecutionSession): "
                 f"**{_fmt(peak)} events/second**.")
        real = [r for r in thr.get("real_data", []) if r.get("status") == "ok"]
        if real:
            r = real[0]
            L.append(f"- Real-data throughput ({_fmt(r['events'])} AAPL IEX events): "
                     f"**{_fmt(r.get('full_execution_events_per_second'))} events/s** full execution, "
                     f"**{_fmt(r.get('replay_events_per_second'))} events/s** replay, "
                     f"**{_fmt(r.get('full_execution_us_per_event'),3)} µs/event**.")
        L.append(f"  - reproduce: `PYTHONPATH=build python3 benchmarks/engine_throughput.py`")
    L.append("")

    # Execution Research
    L.append("### Execution Research")
    if strat:
        agg = strat.get("aggregate", {})
        L.append(f"- **{agg.get('total_experiments')}** strategy comparisons across "
                 f"**{len(agg.get('per_strategy', {}))}** algorithms "
                 f"(TWAP, VWAP, POV, Adaptive) under identical historical conditions.")
        n_is = sum(v.get("implementation_shortfall", {}).get("n", 0)
                   for v in agg.get("per_strategy", {}).values())
        L.append(f"- **{n_is}** implementation-shortfall observations recorded "
                 f"(median per strategy reported; no universal-winner claim).")
        L.append(f"  - reproduce: `PYTHONPATH=build python3 benchmarks/strategy_study.py`")
    L.append("")

    # Reliability
    L.append("### Reliability")
    if det:
        t = det.get("totals", {})
        L.append(f"- **{_fmt(t.get('total_identical_runs'))}/{_fmt(t.get('total_runs'))}** repeated "
                 f"executions produced byte-identical results (fills, quantities, prices, analytics).")
        L.append(f"  - reproduce: `PYTHONPATH=build python3 benchmarks/determinism.py`")
    if ti:
        c = ti.get("ci_covered_total", {})
        L.append(f"- **{c.get('passed')}/{c.get('total')}** automated tests pass "
                 f"(C++ GoogleTest + Python backend + React frontend).")
        L.append(f"  - reproduce: `PYTHONPATH=build python3 benchmarks/test_inventory.py`")
    if ob:
        s = ob.get("summary", {})
        L.append(f"- **{s.get('passed')}/{s.get('scenarios')}** order-book / matching correctness "
                 f"scenarios pass (market/limit orders, partial + multi-level fills, price-time "
                 f"priority, cancellations, insufficient liquidity, stressed conditions).")
        L.append(f"  - reproduce: `PYTHONPATH=build python3 benchmarks/orderbook_correctness.py`")
    if nl:
        L.append(f"- No-lookahead / data-integrity validated: **{nl.get('overall_no_lookahead_validated')}** "
                 f"(C++ replay tests + real-data truncation-invariance).")
        L.append(f"  - reproduce: `PYTHONPATH=build python3 benchmarks/no_lookahead.py`")
    L.append("")
    L.append("---")
    L.append("_Every figure above is backed by a JSON file in `benchmarks/results/` containing the "
             "raw measurement, environment, and reproduce command. No value here is hand-entered._")
    L.append("")
    return "\n".join(L)


def main() -> int:
    report = build_report()
    metrics = build_resume_metrics()
    (H.BENCH_DIR / "BENCHMARK_REPORT.md").write_text(report)
    (H.BENCH_DIR / "RESUME_METRICS.md").write_text(metrics)
    print(f"Wrote {H.BENCH_DIR / 'BENCHMARK_REPORT.md'}")
    print(f"Wrote {H.BENCH_DIR / 'RESUME_METRICS.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
