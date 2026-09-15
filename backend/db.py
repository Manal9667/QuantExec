"""
SQLite persistence (Phase 2, spec section 33).

Stores experiment configs, execution-run summaries, individual fills, and
strategy cost/impact results. Deliberately does NOT store raw market
datasets - those stay on disk as files (datasets/*.csv); only the dataset
*path* and lightweight metadata are ever written here, per spec section 33
("do not put massive raw market datasets into the database").

Plain stdlib sqlite3, no ORM: the schema is small and stable enough that an
ORM would be an unjustified dependency (spec section 40, Rule 9: "do not
add dependencies without a reason").
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "experiments" / "experiments.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS experiments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    symbol TEXT NOT NULL,
    dataset TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    strategy TEXT NOT NULL,
    config_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'completed',
    error TEXT
);

CREATE TABLE IF NOT EXISTS execution_runs (
    experiment_id INTEGER PRIMARY KEY REFERENCES experiments(id) ON DELETE CASCADE,
    requested_quantity INTEGER NOT NULL,
    filled_quantity INTEGER NOT NULL,
    arrival_price REAL NOT NULL,
    limit_price REAL NOT NULL,
    average_execution_price REAL NOT NULL,
    market_vwap REAL NOT NULL,
    fill_rate REAL NOT NULL,
    slippage REAL NOT NULL,
    implementation_shortfall REAL NOT NULL,
    vwap_deviation REAL NOT NULL,
    completion_time_ms INTEGER NOT NULL,
    market_price_drift REAL NOT NULL,
    estimated_spread_cost REAL NOT NULL,
    estimated_execution_cost REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    timestamp_ms INTEGER NOT NULL,
    price REAL NOT NULL,
    qty INTEGER NOT NULL,
    bid REAL NOT NULL,
    ask REAL NOT NULL,
    market_volume INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fills_experiment ON fills(experiment_id);

CREATE TABLE IF NOT EXISTS strategy_results (
    experiment_id INTEGER PRIMARY KEY REFERENCES experiments(id) ON DELETE CASCADE,
    commission REAL NOT NULL,
    exchange_fees REAL NOT NULL,
    fixed_fees REAL NOT NULL,
    spread_cost REAL NOT NULL,
    total_cost REAL NOT NULL,
    total_cost_bps REAL NOT NULL,
    impact_participation_rate REAL,
    impact_bps REAL,
    impact_cost REAL
);

CREATE TABLE IF NOT EXISTS dataset_metadata (
    dataset TEXT PRIMARY KEY,
    symbol TEXT,
    date_range TEXT,
    resolution TEXT,
    fields TEXT,
    data_type TEXT,
    notes TEXT
);
"""

_local = threading.local()


def get_connection(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """One connection per thread (FastAPI's default threadpool executor uses
    multiple worker threads; sqlite3 connections are not safe to share
    across threads without check_same_thread=False + external locking, so
    each thread gets its own)."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(SCHEMA)
        _local.conn = conn
    return conn


@contextmanager
def transaction(db_path: Path = DEFAULT_DB_PATH) -> Iterator[sqlite3.Connection]:
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def insert_experiment(
    conn: sqlite3.Connection,
    *,
    created_at: str,
    symbol: str,
    dataset: str,
    side: str,
    quantity: int,
    strategy: str,
    config: dict,
    status: str = "completed",
    error: Optional[str] = None,
) -> int:
    cur = conn.execute(
        """INSERT INTO experiments
           (created_at, symbol, dataset, side, quantity, strategy, config_json, status, error)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (created_at, symbol, dataset, side, quantity, strategy, json.dumps(config), status, error),
    )
    return int(cur.lastrowid)


def insert_execution_run(conn: sqlite3.Connection, experiment_id: int, result: dict) -> None:
    conn.execute(
        """INSERT INTO execution_runs
           (experiment_id, requested_quantity, filled_quantity, arrival_price, limit_price,
            average_execution_price, market_vwap, fill_rate, slippage,
            implementation_shortfall, vwap_deviation, completion_time_ms,
            market_price_drift, estimated_spread_cost, estimated_execution_cost)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            experiment_id,
            result["requested_quantity"],
            result["filled_quantity"],
            result["arrival_price"],
            result["limit_price"],
            result["average_execution_price"],
            result["market_vwap"],
            result["fill_rate"],
            result["slippage"],
            result["implementation_shortfall"],
            result["vwap_deviation"],
            result["completion_time_ms"],
            result["market_price_drift"],
            result["estimated_spread_cost"],
            result["estimated_execution_cost"],
        ),
    )


def insert_fills(conn: sqlite3.Connection, experiment_id: int, fills: list[dict]) -> None:
    conn.executemany(
        """INSERT INTO fills (experiment_id, seq, timestamp_ms, price, qty, bid, ask, market_volume)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (experiment_id, i, f["timestamp_ms"], f["price"], f["qty"], f["bid"], f["ask"], f["market_volume"])
            for i, f in enumerate(fills)
        ],
    )


def insert_strategy_result(conn: sqlite3.Connection, experiment_id: int, costs: dict, impact: Optional[dict]) -> None:
    conn.execute(
        """INSERT INTO strategy_results
           (experiment_id, commission, exchange_fees, fixed_fees, spread_cost, total_cost, total_cost_bps,
            impact_participation_rate, impact_bps, impact_cost)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            experiment_id,
            costs["commission"],
            costs["exchange_fees"],
            costs["fixed_fees"],
            costs["spread_cost"],
            costs["total_cost"],
            costs["total_cost_bps"],
            impact["participation_rate"] if impact else None,
            impact["impact_bps"] if impact else None,
            impact["impact_cost"] if impact else None,
        ),
    )


def upsert_dataset_metadata(conn: sqlite3.Connection, dataset: str, meta: dict) -> None:
    conn.execute(
        """INSERT INTO dataset_metadata (dataset, symbol, date_range, resolution, fields, data_type, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(dataset) DO UPDATE SET
             symbol=excluded.symbol, date_range=excluded.date_range, resolution=excluded.resolution,
             fields=excluded.fields, data_type=excluded.data_type, notes=excluded.notes""",
        (
            dataset,
            meta.get("symbol"),
            meta.get("date_range"),
            meta.get("resolution"),
            meta.get("fields"),
            meta.get("data_type"),
            meta.get("notes"),
        ),
    )


def list_experiments(conn: sqlite3.Connection, limit: int = 100) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT e.*, r.filled_quantity, r.requested_quantity, r.fill_rate,
                  r.average_execution_price, r.slippage, s.total_cost, s.total_cost_bps
           FROM experiments e
           LEFT JOIN execution_runs r ON r.experiment_id = e.id
           LEFT JOIN strategy_results s ON s.experiment_id = e.id
           ORDER BY e.id DESC LIMIT ?""",
        (limit,),
    ).fetchall()


def get_experiment(conn: sqlite3.Connection, experiment_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM experiments WHERE id = ?", (experiment_id,)).fetchone()


def get_execution_run(conn: sqlite3.Connection, experiment_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM execution_runs WHERE experiment_id = ?", (experiment_id,)).fetchone()


def get_strategy_result(conn: sqlite3.Connection, experiment_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM strategy_results WHERE experiment_id = ?", (experiment_id,)).fetchone()


def get_fills(conn: sqlite3.Connection, experiment_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM fills WHERE experiment_id = ? ORDER BY seq ASC", (experiment_id,)
    ).fetchall()