"""
Structured logging (Phase 2, spec section 35).

Emits one JSON object per line to stdout for each event listed in the spec:
replay started/completed, order submitted, partial fill, order completed,
insufficient liquidity, experiment completed - plus optional stage timing.

Deliberately NOT used inside the hot per-event replay loop in execution.cpp
(spec: "do not flood the hot execution loop with logs"). It logs around a
full experiment run, from the Python orchestration layer, not per market
tick.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from contextlib import contextmanager
from typing import Any, Iterator


def _make_logger() -> logging.Logger:
    logger = logging.getLogger("execution_engine")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


_logger = _make_logger()


def log_event(event: str, **fields: Any) -> None:
    """Emit one structured JSON log line: {"event": ..., "ts": ..., ...fields}."""
    record = {"event": event, "ts": time.time()}
    record.update(fields)
    _logger.info(json.dumps(record, default=str))


@contextmanager
def timed_stage(stage: str, **fields: Any) -> Iterator[None]:
    """
    Log a stage's wall-clock duration (spec section 35: "add timing
    information for: data loading, replay, order-book processing,
    execution, analytics"). Usage:

        with timed_stage("data_loading", dataset=path):
            ...load...
    """
    start = time.perf_counter()
    log_event(f"{stage}_started", **fields)
    try:
        yield
    finally:
        duration_ms = (time.perf_counter() - start) * 1000.0
        log_event(f"{stage}_completed", duration_ms=round(duration_ms, 3), **fields)