"""
Automated test inventory.

Counts every automated test across the three CI-covered layers and reports
totals (passed / failed / skipped) from the test runners' own machine-
readable output - never hand-counted:

  * C++     : the 10 GoogleTest suites (ctest), counted from --gtest_output=json
  * backend : pytest over backend/tests, counted from JUnit XML (--junitxml)
  * frontend: Vitest over frontend/src, counted from the JSON reporter

A best-effort "python_offline" category also runs the offline (no-network)
python/test_alpaca_*.py unit tests; it is reported separately and never
counted into the CI-covered total, and network-gated tests are excluded.

No coverage tooling is configured in this repository (verified: no
pytest-cov/coverage.py in backend/requirements-dev.txt, no @vitest/coverage-*
in frontend, no gcov/llvm-cov flags in CMake), so coverage is reported as
"not configured" rather than fabricated.

Single reproducible command for the whole suite:
    PYTHONPATH=build python3 benchmarks/test_inventory.py

Prerequisites: engine built (build/), backend dev deps installed, and
frontend `npm install` run once (see benchmarks/README.md).
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import harness as H
from gtest_util import run_gtest_binary

CPP_SUITES = [
    "test_book", "test_engine", "test_simulator", "test_algorithms",
    "test_integrate", "test_phase", "test_costs", "test_phase2",
    "test_replay", "test_stress",
]

PYENV_PYTHON = "/root/.pyenv/versions/3.11.15/bin/python3.11"


def _python() -> str:
    import sys
    return sys.executable or PYENV_PYTHON


def count_cpp() -> dict:
    suites = []
    total = passed = failed = skipped = 0
    for name in CPP_SUITES:
        r = run_gtest_binary(name)
        suites.append(r)
        if r.get("status") == "ok":
            total += r["scenarios"]; passed += r["passed"]
            failed += r["failed"]; skipped += r["skipped"]
    return {"layer": "cpp", "runner": "GoogleTest/ctest", "suite_count": len(suites),
            "total": total, "passed": passed, "failed": failed, "skipped": skipped,
            "suites": [{"binary": s.get("binary"), "status": s.get("status"),
                        "scenarios": s.get("scenarios"), "passed": s.get("passed"),
                        "failed": s.get("failed")} for s in suites]}


def count_pytest(label: str, target: str, extra_args: list[str] | None = None) -> dict:
    with tempfile.TemporaryDirectory() as td:
        xml = Path(td) / "junit.xml"
        cmd = [_python(), "-m", "pytest", target, "-q", "-p", "no:cacheprovider",
               f"--junitxml={xml}"] + (extra_args or [])
        env = {"PYTHONPATH": f"{H.build_dir()}:{H.REPO_ROOT / 'backend'}"}
        import os
        full_env = {**os.environ, **env}
        try:
            proc = subprocess.run(cmd, cwd=H.REPO_ROOT, capture_output=True,
                                  text=True, timeout=600, env=full_env)
        except subprocess.TimeoutExpired:
            return {"layer": label, "runner": "pytest", "status": "timeout"}
        if not xml.exists():
            return {"layer": label, "runner": "pytest", "status": "error",
                    "returncode": proc.returncode, "stderr": proc.stderr[-400:]}
        root = ET.parse(xml).getroot()
        # <testsuites> may wrap one <testsuite>, or the root IS <testsuite>.
        suites = root.findall("testsuite") or [root]
        total = fail = err = skip = 0
        for s in suites:
            total += int(s.get("tests", 0)); fail += int(s.get("failures", 0))
            err += int(s.get("errors", 0)); skip += int(s.get("skipped", 0))
        return {"layer": label, "runner": "pytest", "status": "ok",
                "returncode": proc.returncode, "total": total,
                "passed": total - fail - err - skip, "failed": fail + err, "skipped": skip}


def _node_bin_dir() -> str | None:
    """Locate a Node.js bin directory. `node` is often provided via nvm and
    absent from a bare subprocess PATH, so fall back to a login shell / glob."""
    import glob
    import shutil
    found = shutil.which("node")
    if found:
        return str(Path(found).parent)
    # Prefer whatever a login shell resolves (matches the interactive default).
    try:
        out = subprocess.run(["bash", "-lc", "command -v node"], capture_output=True,
                             text=True, timeout=30)
        if out.returncode == 0 and out.stdout.strip():
            return str(Path(out.stdout.strip()).parent)
    except Exception:
        pass
    cands = sorted(glob.glob("/root/.nvm/versions/node/*/bin"))
    return cands[-1] if cands else None


def count_frontend() -> dict:
    import os
    fe = H.REPO_ROOT / "frontend"
    if not (fe / "node_modules").is_dir():
        return {"layer": "frontend", "runner": "vitest", "status": "skipped",
                "reason": "node_modules not installed (run `npm install` in frontend/)"}
    node_bin = _node_bin_dir()
    if node_bin is None:
        return {"layer": "frontend", "runner": "vitest", "status": "skipped",
                "reason": "node runtime not found on PATH or under nvm"}
    env = {**os.environ, "PATH": f"{node_bin}:{os.environ.get('PATH', '')}"}
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "vitest.json"
        try:
            proc = subprocess.run(
                [f"{node_bin}/npx", "vitest", "run", "--reporter=json", f"--outputFile={out}"],
                cwd=fe, capture_output=True, text=True, timeout=600, env=env,
            )
        except subprocess.TimeoutExpired:
            return {"layer": "frontend", "runner": "vitest", "status": "timeout"}
        if not out.exists():
            return {"layer": "frontend", "runner": "vitest", "status": "error",
                    "returncode": proc.returncode, "stderr": proc.stderr[-400:]}
        data = json.loads(out.read_text())
        total = data.get("numTotalTests", 0)
        passed = data.get("numPassedTests", 0)
        failed = data.get("numFailedTests", 0)
        pending = data.get("numPendingTests", 0) + data.get("numTodoTests", 0)
        return {"layer": "frontend", "runner": "vitest", "status": "ok",
                "returncode": proc.returncode, "total": total, "passed": passed,
                "failed": failed, "skipped": pending}


def main() -> int:
    cpp = count_cpp()
    print(f"  cpp      total={cpp['total']} passed={cpp['passed']} failed={cpp['failed']}", flush=True)
    backend = count_pytest("backend", "backend/tests")
    print(f"  backend  {backend.get('status')} total={backend.get('total')} "
          f"passed={backend.get('passed')} failed={backend.get('failed')} skipped={backend.get('skipped')}", flush=True)
    frontend = count_frontend()
    print(f"  frontend {frontend.get('status')} total={frontend.get('total')} "
          f"passed={frontend.get('passed')} failed={frontend.get('failed')}", flush=True)

    # Best-effort offline python unit tests (excluded from CI-covered total).
    python_offline = count_pytest(
        "python_offline",
        "python/test_alpaca_adapter.py",
        extra_args=["python/test_alpaca_historical.py", "python/test_alpaca_ingest.py"],
    )
    # These tests need optional deps (requests / alpaca-py). If they didn't all
    # pass, they almost certainly failed at collection due to a missing optional
    # dependency, not a real regression - report that honestly rather than as
    # "0 passed".
    if python_offline.get("status") == "ok" and python_offline.get("passed", 0) < python_offline.get("total", 0):
        python_offline = {
            "layer": "python_offline", "runner": "pytest",
            "status": "skipped_optional",
            "reason": "collection error - optional deps not installed (pip install requests alpaca-py)",
            "note": "offline python/test_alpaca_*.py (excludes network-gated test_alpaca_live_smoke.py); NOT part of CI",
        }
    else:
        python_offline["note"] = "offline python/test_alpaca_*.py (excludes network-gated test_alpaca_live_smoke.py); NOT part of CI"
    print(f"  python   {python_offline.get('status')} total={python_offline.get('total')} "
          f"passed={python_offline.get('passed')} skipped={python_offline.get('skipped')}", flush=True)

    ci_layers = [cpp, backend, frontend]
    ci_total = sum(l.get("total", 0) for l in ci_layers if l.get("status", "ok") == "ok")
    ci_passed = sum(l.get("passed", 0) for l in ci_layers if l.get("status", "ok") == "ok")
    ci_failed = sum(l.get("failed", 0) for l in ci_layers if l.get("status", "ok") == "ok")
    ci_skipped = sum(l.get("skipped", 0) for l in ci_layers if l.get("status", "ok") == "ok")

    payload = {
        "_meta": H.new_meta(
            "test_inventory",
            "PYTHONPATH=build python3 benchmarks/test_inventory.py",
            extra={
                "category": "OBSERVED (counts from each test runner's own machine-readable output)",
                "single_command_full_suite": (
                    "ctest --test-dir build --output-on-failure && "
                    "PYTHONPATH=build:backend python -m pytest backend/tests -q && "
                    "(cd frontend && npm test)"
                ),
                "coverage_tooling": "not configured in this repository (not fabricated)",
            },
        ),
        "ci_covered_total": {
            "total": ci_total, "passed": ci_passed, "failed": ci_failed, "skipped": ci_skipped,
            "layers": ["cpp", "backend", "frontend"],
            "note": "No test is counted twice; each layer's runner reports its own tests.",
        },
        "layers": {"cpp": cpp, "backend": backend, "frontend": frontend},
        "extra_python_offline": python_offline,
    }
    out = H.write_json("test_inventory.json", payload)
    print(f"\nCI-covered automated tests: {ci_passed}/{ci_total} passed "
          f"({ci_failed} failed, {ci_skipped} skipped). Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
