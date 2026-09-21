"""
Helper to run a compiled GoogleTest binary and parse its machine-readable
JSON output (--gtest_output=json). Reused by orderbook_correctness.py and
test_inventory.py so gtest counts are parsed in exactly one place.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import time
from pathlib import Path

import harness as H


def _parse_time(t) -> float:
    if isinstance(t, (int, float)):
        return float(t)
    if isinstance(t, str) and t.endswith("s"):
        try:
            return float(t[:-1])
        except ValueError:
            return 0.0
    try:
        return float(t)
    except (TypeError, ValueError):
        return 0.0


def run_gtest_binary(name: str) -> dict:
    """Run build/<name> with JSON output. Returns counts, per-case results,
    and measured wall-clock time. status='missing' if the binary is absent."""
    exe = H.build_dir() / name
    if not exe.exists():
        return {"binary": name, "status": "missing"}
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / f"{name}.json"
        t0 = time.perf_counter()
        proc = subprocess.run(
            [str(exe), f"--gtest_output=json:{out}"],
            cwd=H.REPO_ROOT, capture_output=True, text=True, timeout=600,
        )
        wall = time.perf_counter() - t0
        if not out.exists():
            return {"binary": name, "status": "error",
                    "returncode": proc.returncode, "stderr": proc.stderr[-300:]}
        data = json.loads(out.read_text())

    total = data.get("tests", 0)
    failures = data.get("failures", 0)
    errors = data.get("errors", 0)
    disabled = data.get("disabled", 0)
    skipped = 0
    cases = []
    for suite in data.get("testsuites", []):
        for c in suite.get("testsuite", []):
            result = c.get("result", "")
            case_failed = bool(c.get("failures"))
            if result == "SKIPPED":
                skipped += 1
            cases.append({
                "suite": suite.get("name"),
                "name": c.get("name"),
                "passed": (result == "COMPLETED" and not case_failed),
                "time_s": _parse_time(c.get("time", 0)),
            })
    passed = total - failures - errors - skipped
    return {
        "binary": name,
        "status": "ok",
        "returncode": proc.returncode,
        "scenarios": total,
        "passed": passed,
        "failed": failures + errors,
        "skipped": skipped,
        "disabled": disabled,
        "gtest_reported_time_s": _parse_time(data.get("time", 0)),
        "wall_time_s": round(wall, 4),
        "cases": cases,
    }
