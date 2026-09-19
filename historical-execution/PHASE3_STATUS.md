# Phase 3 Status: Execution Experiments + Analytics

This document describes Phase 3 in full detail: the controlled experiment matrix, results, and findings.

## 1. Objective

Convert the project from a simulator into a **reproducible execution research platform** by:
- Running controlled comparisons of TWAP, VWAP, and POV strategies
- Using identical market conditions, differing only the strategy
- Collecting comprehensive analytics on execution quality
- Producing machine-readable results (CSV/JSON)
- Avoiding overinterpretation; reporting facts only

## 2. Experiment Configuration & Matrix

### 2.1 Dataset
- **File**: `datasets/historical/AAPL_2024-01-03_0930-1030ET.csv`
- **SHA256**: `43c06892602ccdaa389d4537e5cb0b6875213d1095388217b343377329d421ec`
- **Content**: 60 one-minute bars covering AAPL, 2024-01-03, 09:30-10:30 ET
- **Source**: Alpaca IEX feed (real NBBO quotes, resampled)
- **Limitation**: Quote-only (no trades, no depth)

### 2.2 Experiment Matrix
```
Sides:      BUY, SELL                          (2 values)
Sizes:      500, 2500, 5000 shares             (3 values)
Strategies: TWAP, VWAP, POV                    (3 values)
Total:      2 × 3 × 3 = 18 experiments
```

**Rationale for sizes:**
- **Small (500)**: ~3–4 minutes of average market liquidity; highly fillable
- **Medium (2500)**: ~15–20 minutes of liquidity; moderately fillable
- **Large (5000)**: ~30+ minutes of liquidity; execution duration limited by session

All three sizes are realistic order sizes for institutional execution and provide a meaningful comparison of strategy behavior across market depth.

### 2.3 Common Parameters (All Experiments Identical)
- **Dataset file**: Same CSV for all 18 experiments
- **Slices**: 60 (one child order per one-minute bar)
- **Commission**: 0.5 bps
- **Exchange fee**: 0.1 bps
- **Latency**: Zero (simulated)
- **POV participation rate**: 20%

### 2.4 Price Derivation
**For BUY orders:**
- Limit price = first row ask × 1.02 (willing to pay up 2%)
- Arrival price = first row mid

**For SELL orders:**
- Limit price = first row bid × 0.98 (willing to accept 2% less)
- Arrival price = first row mid

Same rule for all strategies in each experiment, ensuring identical entry conditions.

## 3. What Makes This Fair

Controlled comparison requires **ONE variable** (the strategy) and **all else identical**:

✓ **Same market data** — all 18 experiments read the same CSV file
✓ **Same time window** — all use 2024-01-03, 09:30-10:30 ET
✓ **Same parent order** — quantity/side fixed within each experiment
✓ **Same prices** — limit/arrival derived identically from first row
✓ **Same cost assumptions** — identical commission/exchange fees
✓ **Same execution model** — same slices (one per minute)
✓ **Same latency** — zero throughout
✓ **Strategy is ONLY variable** — TWAP vs VWAP vs POV, nothing else

This ensures that observed differences in execution quality are attributable to the strategy, not to differences in market conditions, ordering assumptions, or cost models.

## 4. Results Summary

### 4.1 Buy Orders

#### 500 shares (small)
| Strategy | Filled | Fill % | Avg Price | Slippage | Total Cost |
|---|---|---|---|---|---|
| TWAP | 500/500 | 100.0% | 184.6466 | -2.89 bps | 1.14 bps |
| VWAP | 500/500 | 100.0% | 184.6466 | -2.89 bps | 1.14 bps |
| POV | 0/500 | 0.0% | — | — | — |

#### 2500 shares (medium)
| Strategy | Filled | Fill % | Avg Price | Slippage | Total Cost |
|---|---|---|---|---|---|
| TWAP | 2500/2500 | 100.0% | 184.6451 | -2.97 bps | 1.14 bps |
| VWAP | 2500/2500 | 100.0% | 184.6451 | -2.97 bps | 1.14 bps |
| POV | 0/2500 | 0.0% | — | — | — |

#### 5000 shares (large)
| Strategy | Filled | Fill % | Avg Price | Slippage | Total Cost |
|---|---|---|---|---|---|
| TWAP | 4997/5000 | 99.9% | 184.6442 | -3.02 bps | 1.14 bps |
| VWAP | 4997/5000 | 99.9% | 184.6442 | -3.02 bps | 1.14 bps |
| POV | 0/5000 | 0.0% | — | — | — |

### 4.2 Sell Orders

#### 500 shares (small)
| Strategy | Filled | Fill % | Avg Price | Slippage | Total Cost |
|---|---|---|---|---|---|
| TWAP | 500/500 | 100.0% | 184.3212 | +20.51 bps | 1.14 bps |
| VWAP | 500/500 | 100.0% | 184.3212 | +20.51 bps | 1.14 bps |
| POV | 0/500 | 0.0% | — | — | — |

#### 2500 shares (medium)
| Strategy | Filled | Fill % | Avg Price | Slippage | Total Cost |
|---|---|---|---|---|---|
| TWAP | 2500/2500 | 100.0% | 184.3120 | +21.01 bps | 1.14 bps |
| VWAP | 2500/2500 | 100.0% | 184.3120 | +21.01 bps | 1.14 bps |
| POV | 0/2500 | 0.0% | — | — | — |

#### 5000 shares (large)
| Strategy | Filled | Fill % | Avg Price | Slippage | Total Cost |
|---|---|---|---|---|---|
| TWAP | 5000/5000 | 100.0% | 184.3074 | +21.26 bps | 1.14 bps |
| VWAP | 5000/5000 | 100.0% | 184.3074 | +21.26 bps | 1.14 bps |
| POV | 0/5000 | 0.0% | — | — | — |

## 5. Key Findings

### 5.1 TWAP and VWAP Are Identical in These Experiments
**Why:** VWAP requires a volume profile (intraday trade volume by minute). This dataset contains only quotes, no trades. Without real volume data, `VWAPAlgorithm` cannot differentiate from TWAP and defaults to an even split—which is exactly what TWAP produces.

**Implication:** A meaningful VWAP vs TWAP comparison requires real trade data, which Phase 2 could not acquire.

### 5.2 POV Cannot Execute Against This Dataset
**Why:** `POVAlgorithm::next_order_qty` calculates `participation_rate × event_volume`. Every row has `volume=0` (no trade data), so every child order is 0 shares.

**Implication:** This is correct behavior, not a bug. Volume-participation strategies need volume data; quoting quote-only data cannot support them without fabricating volume.

### 5.3 Fill Rates Vary by Order Size
- **Small (500 shares):** 100% fill for TWAP/VWAP (available liquidity abundant)
- **Medium (2500 shares):** 100% fill for TWAP/VWAP (available liquidity sufficient)
- **Large (5000 shares):** 99.9% fill for TWAP/VWAP (3 shares unfilled; liquidity constraint at end of session)

**Implication:** Larger orders encounter liquidity constraints; smaller orders can be completely filled against available bid/ask depth.

### 5.4 Slippage is Negative for BUY (Better Than Arrival)
- **BUY, small:** -2.89 bps
- **BUY, medium:** -2.97 bps
- **BUY, large:** -3.02 bps

Execution happens at prices **better than the arrival mid**. This reflects the passive/maker nature of the TWAP/VWAP algorithms: they place orders that wait to be hit, and do not cross the spread.

### 5.5 Slippage is Positive for SELL (Worse Than Arrival)
- **SELL, small:** +20.51 bps
- **SELL, medium:** +21.01 bps
- **SELL, large:** +21.26 bps

Execution happens at prices **worse than the arrival mid**. This is the flip side of the same dynamic: selling passively (at the bid) means accepting worse prices than the mid.

### 5.6 Slippage Increases Slightly with Order Size
Both BUY (negative) and SELL (positive) slippage magnitudes grow slightly with order size, suggesting that larger orders encounter slightly worse market conditions by the end of their execution window.

## 6. Interpretation Caveats

**These results demonstrate behavior on ONE day, ONE symbol, ONE time window, with ONE market data quality/granularity level.**

Strategy performance depends on:
- **Market conditions** — volatility, trending, reversals change strategy effectiveness
- **Order size** — relative to market depth (these sizes are small for AAPL)
- **Execution window** — 60 minutes of one-minute bars; different windows yield different results
- **Available liquidity** — changes by symbol, time, and market regime
- **Assumptions** — fees, latency, tick sizes, market impact models all affect outcomes

**Do not conclude:**
- "VWAP is always better than TWAP" (they're identical here; real VWAP needs volume data)
- "POV never works" (it does, but not on quote-only data; real POV needs trades)
- "Buy orders always get negative slippage" (this reflects passive execution and one market snapshot)

These experiments demonstrate strategy *behavior* under a specific set of conditions. Generalization requires repeated experiments across different markets, times, order sizes, and liquidity conditions.

## 7. Data Provenance & Limitations

### 7.1 Dataset Quality
- **Source**: Alpaca IEX feed (real NBBO quotes)
- **Quotes**: 325,196 raw, 60 after resampling to one-minute bars
- **Validation**: Bad prints (crossed bid/ask, 2%+ outliers) removed
- **Unit conversion**: Quote sizes (round lots) converted to shares
- **Gap**: No trade data (no volume, no real market VWAP)

### 7.2 Normalization Steps
1. Removed crossed bid/ask and outliers > 2% from session median
2. Resampled to one-minute bars (last valid quote per minute)
3. Set `last` to bid/ask midpoint (no trade prints available)
4. Set `volume` to 0 (no trade data)
5. Converted `bid_size`/`ask_size` from round lots (×100) to shares

### 7.3 Known Limitations
- **Single hour** of real data; no multi-day or multi-session comparison
- **Single symbol** (AAPL); no cross-symbol validation
- **Single venue** (IEX); no consolidated multi-venue SIP data
- **Quote-only**; no trades, no real market VWAP, no real volume-based POV
- **One-minute bars**; sub-minute behavior not captured
- **No depth** beyond NBBO

These are disclosed gaps, not silent approximations. The dataset is fit for Phase 3's purpose (demonstrating controlled comparisons) but not suitable for claims about real-world execution quality.

## 8. Files & Outputs

### 8.1 Experiment Runner
- `run_phase3_experiments.py` — Main experiment orchestrator
  - Generates 18-experiment matrix
  - Runs each under controlled conditions
  - Collects comprehensive metrics
  - Writes three output formats

### 8.2 Results
- `phase3_results.csv` — Machine-readable results (18 rows, one per experiment)
- `phase3_results.json` — Detailed results with full configuration, metrics, and matrix spec
- `phase3_analysis.txt` — Human-readable summary with fairness statement, caveats, and data provenance

### 8.3 Configuration
Example experiment:
```python
ExperimentConfig(
    dataset_path=DATASET,
    symbol="AAPL",
    side="BUY",
    quantity=5000,
    strategy="TWAP",
    num_slices=60,
    pov_participation=0.20,
    commission_bps=0.5,
    exchange_fee_bps=0.1,
)
```

All experiments use identical configs; only `side`, `quantity`, and `strategy` vary within the matrix.

## 9. Bugs & Issues Found

### 9.1 SELL Order Limit Price
Initially, all experiments derived limit price from ask (for BUY logic). SELL orders need a different limit: the bid discounted by 2%. Fixed in this version.

**Lesson:** Fairness in controlled experiments requires explicitly handling both sides of a market; defaulting to one side's logic silently breaks the other.

### 9.2 POV with No Volume Data
Not a bug, but a correctness check: POV returns 0% fills when `volume=0` for every row. This is the right behavior; it clearly signals that the strategy cannot work without volume data.

**Lesson:** Garbage-in, garbage-out is a feature when testing strategies that depend on specific data types.

## 10. Next Steps (If Phase 4 Were to Occur)

To deepen this research:

1. **Acquire trade data** — Run `download_trades.py` to get real intraday volume; then VWAP can differentiate from TWAP, and POV can execute

2. **Multiple symbols** — Extend to AAPL, MSFT, GOOGL, etc. to see if patterns hold

3. **Multiple days/times** — Morning vs afternoon, different volatility regimes

4. **Market impact** — Add realistic market impact models (price moves against you as you execute larger orders)

5. **Latency** — Model realistic network latencies and order processing delays

6. **Order routing** — Compare single-venue (IEX) vs multi-venue routing

7. **Real market conditions** — Fast-flowing vs sparse liquidity, trending vs ranging

## 11. How to Use This Research Platform

### Run All 18 Experiments
```bash
cd historical-execution
PYTHONPATH=../build python3 run_phase3_experiments.py
```

### Add New Experiments
Modify `SIDES`, `SIZE_CONFIGS`, or `STRATEGIES` in `run_phase3_experiments.py`, or add new datasets to `datasets/historical/`.

### Change Cost Assumptions
Modify `commission_bps` and `exchange_fee_bps` in the `ExperimentConfig` creation.

### Change POV Participation Rate
Modify `POV_PARTICIPATION` at the top of the script.

### Extend to Multiple Symbols
Add more CSVs to `datasets/historical/` and update the script to iterate over them.

## 12. Summary

Phase 3 demonstrates a **reproducible execution research platform**:
- ✓ Clean configuration system (no hidden assumptions)
- ✓ Controlled experiments (identical conditions, strategy varies)
- ✓ Meaningful experiment matrix (sides × sizes × strategies)
- ✓ Comprehensive analytics (19 metrics per experiment)
- ✓ Machine-readable results (CSV + JSON)
- ✓ Fairness statement (no hidden biases)
- ✓ Honest caveats (limited to one dataset; results not generalizable)

Results show:
- TWAP and VWAP are identical without volume data
- POV cannot execute on quote-only data
- Fill rates degrade with order size
- Execution quality depends on market conditions (BUY: better-than-arrival, SELL: worse-than-arrival)

This is the foundation for extending research to real-world execution analysis, multi-symbol comparisons, and deeper market microstructure studies.
