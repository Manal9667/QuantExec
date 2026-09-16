# Execution Assumptions (Step 4)

Every simplification below is deliberate and testable, not an accident.
This document exists so nobody has to reverse-engineer them from
`src/execution.cpp`. If you are extending the engine and need to change
one of these, update this file in the same change.

## 1. How a replayed market event becomes a fillable book

Each time `ExecutionSession::run()` (and its `run_with_latency` /
`run_pov` siblings) reads one `MarketState` from the data source, it:

1. Clears the matching engine's book completely (`engine_.clear_book()`).
2. Re-populates it from that event's `bids`/`asks` (top-of-book, or full
   depth if the dataset provides `bid_depth`/`ask_depth`).
3. Submits **one** child order into that freshly-populated book (or, for
   POV, whatever quantity the volume-driven sizing function decides).

**What this means in practice:** a child order can only ever match
liquidity that was *displayed in that same event*. It cannot match
liquidity from a previous event that never traded, and it cannot see
liquidity from a future event. This is what "no lookahead" means
concretely in this engine, and it is why replaying the same dataset twice
always gives the same fills — see `BASELINE.md` §3.4.

**Known consequence:** because the book is cleared and rebuilt every
event, a resting *unfilled remainder* of a child order does not persist
as a resting order competing for queue position at the next event. Each
child order is matched-or-partially-matched against exactly one event's
displayed liquidity, then whatever didn't fill is simply not filled by
that order (the strategy's next child order gets its own turn at the next
event). This is the single biggest simplification in the engine and is
the reason queue position is not modeled (§3 below) — there is no
persistent queue across events to hold a position in.

## 2. Partial fills

Partial fills are fully supported and are the normal case, not an edge
case: `MatchingEngine::match_market` / `match_limit` (`src/engine.cpp`)
walk price levels and fill as much of an incoming order as the displayed
liquidity allows, returning one `Trade` per level consumed. Unfilled
remaining quantity on a child order is simply not filled — it is **never
silently dropped from the report**: `ExecutionResult::filled_quantity`
vs. `requested_quantity` always reflects the true total, and `fill_rate`
is computed directly from those two numbers (see
`tests/test_stress.cpp`, `thin_liquidity` case, which asserts a large
order against single-digit displayed sizes is *not* fully filled).

## 3. Queue position: explicitly not modeled

This engine does not model FIFO queue position **across replayed
events**. Within a single event's book (step 1 above), FIFO ordering at a
price level is respected (`OrderBook` uses a `deque` per price level -
see `include/book.h`), but because the book is rebuilt every event (§1),
there is no persistent queue for a resting order to hold a position in
from one event to the next.

**Why this is the documented choice instead of an approximation:** every
queue-position approximation we considered (e.g., "assume your order is
always last in the displayed size" or "assume a fixed percentile") would
inject an unstated, non-obvious assumption into every single trade in
every experiment. We judged an explicit "not modeled" to be more honest
and more useful to a researcher than a silent guess dressed up as
realism. If you need queue-position analysis, treat this as the system's
current ceiling, not a bug to route around invisibly.

## 4. Order lifetime and cancellation

`MatchingEngine::cancel_order()` and `OrderBook::cancel_order()` exist and
are unit-tested (`tests/test_book.cpp`), but the replay loop in
`ExecutionSession` does not currently exercise cancellation, because it
never carries a resting order across events (§1) — there is nothing left
to cancel by the time the next event arrives. Cancellation is available
for any code that drives the engine directly against a persistent book
(e.g. a future live/streaming mode), but historical replay through
`ExecutionSession` does not need it given the current event model.

## 5. Latency

`ExecutionSession::run_with_latency()` (see the docstring in
`include/execution.h`) delays a child order's submission by a fixed
`latency_ms` after the event that "decided" it. It is explicitly *not* a
simulation of real network/exchange infrastructure — it exists to make a
timing assumption visible and testable, nothing more. `latency_ms = 0` is
provably equivalent to `run()` (this is unit-tested, not just asserted in
a comment). Latency can only ever delay an order into the future, never
pull information from the future into a decision made earlier — this is
what "latency cannot create impossible fills" means and is covered by the
no-lookahead tests in `tests/test_replay.cpp`.

## 6. Cost decomposition — what each number actually measures

`ExecutionResult` and `compute_transaction_costs()` (`src/costs.cpp`)
report five genuinely different quantities; they are documented together
here because conflating them is the easiest way to misread a result:

| Field | What it measures | What it does NOT measure |
|---|---|---|
| `estimated_spread_cost` | Half the first observed bid/ask spread, as a fraction of the first mid price | Anything about how much of the spread was actually paid on any individual fill |
| Commission / exchange fees / fixed fees (`compute_transaction_costs`) | Configured, explicit costs applied per the `TransactionCostConfig` the experiment specified | Any fee schedule not entered into that config — there is no built-in "realistic" fee table |
| `slippage` | Signed, arrival-price-relative deviation of the actual average execution price | Market impact caused *by this order* specifically (see next row) |
| `market_price_drift` | How much the mid price moved from first to last observed event during the replay window | Whether that drift was caused by this order, by other market activity, or both — the engine has no way to separate the two |
| `estimated_execution_cost` | `slippage - estimated_spread_cost`, a residual | A validated market-impact model — it is what's left over after removing the spread-cost estimate from slippage, nothing more |

The optional `estimate_market_impact()` (`src/impact.cpp`) is a
simplified, non-fitted, educational estimate — off by default in the
backend (`ImpactConfig.enabled = False`) for exactly this reason (see
`backend/schemas.py`).

## 7. Buy/sell sign conventions

`finalize_result()` in `src/execution.cpp` multiplies every
benchmark-relative metric by `direction = +1` for BUY, `-1` for SELL, so
that **positive always means "cost to the parent order," for either
side** — a BUY that executes above arrival price and a SELL that executes
below arrival price both report positive slippage/shortfall; a BUY below
arrival and a SELL above arrival both report negative (a gain). This is
exercised directly by `tests/test_stress.cpp`, which runs every stress
dataset for both sides and asserts the shortfall sign flips correctly.

## 8. Stress datasets (`datasets/stress/`)

Six small, deterministic, manifest-validated fixtures exist specifically
to exercise the assumptions above at their edges:

| File | What it stresses |
|---|---|
| `wide_spread.csv` | A 10-point bid/ask spread — spread-cost dominates slippage |
| `thin_liquidity.csv` | Single-digit displayed sizes — forces partial fills on a 1000-share order |
| `price_gap.csv` | A sudden 50% price jump then drop between events |
| `zero_volume.csv` | No traded volume reported in any event (`market_vwap` must come back `0`, not a divide-by-zero) |
| `incomplete_depth.csv` | Depth columns present on some rows, blank on others |
| `rapid_price_change.csv` | Six events 100ms apart with alternating up/down price swings |

Every file is run through `scripts/build_dataset_manifest.py` (see
`dataset.md`) and through `tests/test_stress.cpp` for both BUY and SELL
parent orders.
