"""
Central runtime configuration (spec section 41: "avoid hardcoding
parameters; use configuration objects/files").

Everything that used to be a hardcoded constant scattered across the backend
- the SQLite location, the CORS allow-list, the API host/port, the default
transaction-cost assumptions, and the log level - is read from environment
variables here. The defaults are exactly the values that were previously
hardcoded, so behaviour is unchanged when nothing is set.

A ``.env`` file at the repository root (or the path in ``QUANTEXEC_ENV_FILE``)
is loaded automatically if present; see ``.env.example``. The tiny parser
below is intentionally dependency-free (spec section 40, Rule 9: "do not add
dependencies without a reason") - it is not a full dotenv implementation, just
enough for ``KEY=value`` lines.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = REPO_ROOT / ".env"


def load_dotenv(path: Path | str | None = None, *, override: bool = False) -> None:
    """Load ``KEY=value`` pairs from a .env file into ``os.environ``.

    Existing environment variables win over the file unless ``override`` is
    set, so an explicit shell export always beats a committed default. Lines
    that are blank, comments (``#``), or malformed are skipped. Surrounding
    single/double quotes on the value are stripped.
    """
    env_path = Path(path or os.environ.get("QUANTEXEC_ENV_FILE", DEFAULT_ENV_FILE))
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and (override or key not in os.environ):
            os.environ[key] = value


def _get_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _get_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _get_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    """Resolved, immutable snapshot of the backend's runtime configuration."""

    db_path: Path
    cors_origins: List[str]
    api_host: str
    api_port: int
    log_level: str
    # Default transaction-cost assumptions applied when a request omits them
    # (spec section 41 lists "fees" as configuration, not code).
    default_commission_bps: float
    default_exchange_fee_bps: float
    default_fixed_fee_per_fill: float


def load_settings() -> Settings:
    """Build a Settings from the current environment (loading .env first)."""
    load_dotenv()

    db_path = Path(
        os.environ.get(
            "QUANTEXEC_DB_PATH",
            str(REPO_ROOT / "experiments" / "experiments.db"),
        )
    ).expanduser()

    origins_raw = os.environ.get("QUANTEXEC_CORS_ORIGINS", "*")
    cors_origins = [o.strip() for o in origins_raw.split(",") if o.strip()] or ["*"]

    return Settings(
        db_path=db_path,
        cors_origins=cors_origins,
        api_host=os.environ.get("QUANTEXEC_API_HOST", "127.0.0.1"),
        api_port=_get_int("QUANTEXEC_API_PORT", 8000),
        log_level=os.environ.get("QUANTEXEC_LOG_LEVEL", "INFO").upper(),
        default_commission_bps=_get_float("QUANTEXEC_COMMISSION_BPS", 0.0),
        default_exchange_fee_bps=_get_float("QUANTEXEC_EXCHANGE_FEE_BPS", 0.0),
        default_fixed_fee_per_fill=_get_float("QUANTEXEC_FIXED_FEE_PER_FILL", 0.0),
    )


# Module-level singleton read once at import. Call load_settings() again if you
# need a fresh snapshot after changing the environment (used by the tests).
settings = load_settings()
