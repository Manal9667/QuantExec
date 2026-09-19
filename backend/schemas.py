"""Pydantic models for the FastAPI backend (Phase 2, spec section 32)."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


class CostConfig(BaseModel):
    commission_bps: float = 0.0
    exchange_fee_bps: float = 0.0
    fixed_fee_per_fill: float = 0.0


class ImpactConfig(BaseModel):
    """Enable the simplified market-impact estimate (spec section 31). Off
    by default - it's an educational, non-fitted estimate, not a core
    execution-quality metric, so it should be opt-in."""

    enabled: bool = False
    eta: float = 0.1


class ExperimentRequest(BaseModel):
    """POST /experiments body.

    strategy-specific fields are only required for their own strategy;
    validated in `check_strategy_fields` below rather than left to fail
    deep inside the engine with a confusing error.
    """

    symbol: str = Field(..., min_length=1)
    dataset: str = Field(..., description="Path to a CSV dataset under datasets/, e.g. datasets/sample_synthetic.csv")
    side: Literal["BUY", "SELL"]
    quantity: int = Field(..., gt=0)
    strategy: Literal["TWAP", "VWAP", "POV"]

    # TWAP / VWAP
    slices: Optional[int] = Field(default=None, gt=0, le=100_000)
    volume_profile: Optional[list[float]] = None

    # POV
    participation_rate: Optional[float] = Field(default=None, gt=0, le=1)
    min_order_qty: int = Field(default=1, ge=1)
    max_order_qty: int = Field(default=0, ge=0)  # 0 = unbounded

    # Optional Phase 2 latency model (spec section 30). 0 = disabled.
    latency_ms: int = Field(default=0, ge=0)

    limit_price: Optional[float] = None
    arrival_price: Optional[float] = None

    costs: CostConfig = Field(default_factory=CostConfig)
    impact: ImpactConfig = Field(default_factory=ImpactConfig)

    @model_validator(mode="after")
    def check_strategy_fields(self) -> "ExperimentRequest":
        if self.strategy in ("TWAP", "VWAP") and not self.slices:
            raise ValueError(f"'slices' is required for strategy={self.strategy}")
        if self.strategy == "POV" and not self.participation_rate:
            raise ValueError("'participation_rate' is required for strategy=POV")
        return self


class FillOut(BaseModel):
    seq: int
    timestamp_ms: int
    price: float
    qty: int
    bid: float
    ask: float
    market_volume: int


class ExecutionMetricsOut(BaseModel):
    requested_quantity: int
    filled_quantity: int
    fill_rate: float
    arrival_price: float
    limit_price: float
    average_execution_price: float
    market_vwap: float
    slippage: float
    implementation_shortfall: float
    vwap_deviation: float
    completion_time_ms: int
    market_price_drift: float
    estimated_spread_cost: float
    estimated_execution_cost: float


class CostBreakdownOut(BaseModel):
    commission: float
    exchange_fees: float
    fixed_fees: float
    spread_cost: float
    total_cost: float
    total_cost_bps: float


class ImpactEstimateOut(BaseModel):
    participation_rate: float
    impact_bps: float
    impact_cost: float


class ExperimentSummaryOut(BaseModel):
    id: int
    created_at: str
    symbol: str
    dataset: str
    side: str
    quantity: int
    strategy: str
    status: str
    dataset_checksum: Optional[str] = None
    filled_quantity: Optional[int] = None
    requested_quantity: Optional[int] = None
    fill_rate: Optional[float] = None
    average_execution_price: Optional[float] = None
    slippage: Optional[float] = None
    total_cost: Optional[float] = None
    total_cost_bps: Optional[float] = None


class ExperimentDetailOut(BaseModel):
    id: int
    created_at: str
    symbol: str
    dataset: str
    side: str
    quantity: int
    strategy: str
    status: str
    error: Optional[str] = None
    config: dict
    dataset_checksum: Optional[str] = None
    config_hash: Optional[str] = None
    duplicate_of: Optional[int] = Field(
        default=None,
        description=(
            "Set when this response reuses an earlier experiment with an "
            "identical configuration and dataset checksum, instead of "
            "re-running the engine (Step 6 duplicate-submission policy). "
            "Refers to the experiment id whose result is being reused."
        ),
    )
    metrics: Optional[ExecutionMetricsOut] = None
    costs: Optional[CostBreakdownOut] = None
    impact: Optional[ImpactEstimateOut] = None


class ErrorOut(BaseModel):
    """Structured error body for request-level failures (Step 6: 'return
    structured validation errors' instead of a bare string). Every
    ExperimentError the API raises carries an `error_type` from a known,
    documented set (see experiment_service.ExperimentError) so a client
    can branch on it programmatically instead of pattern-matching on
    human-readable text."""

    error_type: str
    detail: str


class StrategyInfo(BaseModel):
    name: str
    description: str
    required_fields: list[str]
    optional_fields: list[str]