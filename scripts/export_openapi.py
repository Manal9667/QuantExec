#!/usr/bin/env python3
"""
Export the FastAPI OpenAPI schema to docs/openapi.json.

FastAPI serves the live schema at /openapi.json (and interactive docs at
/docs and /redoc), but committing a static copy lets anyone read the API
contract - and diff it in review - without building the C++ extension or
starting the server. Run this after changing endpoints/schemas to keep the
committed copy in sync.

Usage:
    PYTHONPATH=build:backend python3 scripts/export_openapi.py
    # optional: --check  (exit 1 if docs/openapi.json is stale; for CI)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT = REPO_ROOT / "docs" / "openapi.json"


def _load_app():
    # The backend uses flat imports (import db, import config, ...), so both
    # the built `executor` extension (build/) and backend/ must be importable.
    sys.path.insert(0, str(REPO_ROOT / "backend"))
    sys.path.insert(0, str(REPO_ROOT / "build"))
    try:
        from main import app  # noqa: WPS433
    except ModuleNotFoundError as exc:  # pragma: no cover - helpful message only
        raise SystemExit(
            f"Could not import the backend app ({exc}). Install deps and build the "
            f"engine first:\n"
            f"  pip install pybind11 -r backend/requirements.txt\n"
            f"  cmake -S . -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build --target executor\n"
            f"  PYTHONPATH=build:backend python3 scripts/export_openapi.py"
        ) from exc
    return app


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true",
                        help="Exit non-zero if docs/openapi.json differs from the current schema.")
    args = parser.parse_args(argv)

    app = _load_app()
    schema = app.openapi()
    rendered = json.dumps(schema, indent=2, sort_keys=True) + "\n"

    if args.check:
        current = OUTPUT.read_text() if OUTPUT.is_file() else ""
        if current != rendered:
            print(f"{OUTPUT.relative_to(REPO_ROOT)} is out of date - "
                  f"run: PYTHONPATH=build:backend python3 scripts/export_openapi.py")
            return 1
        print(f"{OUTPUT.relative_to(REPO_ROOT)} is up to date.")
        return 0

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(rendered)
    print(f"Wrote {OUTPUT.relative_to(REPO_ROOT)} "
          f"(OpenAPI {schema.get('openapi', '?')}, {len(schema.get('paths', {}))} paths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
