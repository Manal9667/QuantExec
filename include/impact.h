#ifndef EXECUTOR_IMPACT_H
#define EXECUTOR_IMPACT_H

#include <cstdint>

/**
 * SimpleMarketImpactModel - Phase 2, spec section 31.
 *
 * A deliberately simple, fully-documented estimate of how much of our
 * execution cost is attributable to *our own* participation, rather than
 * to general market movement. This is reporting-only: it is computed
 * AFTER an ExecutionResult already exists, from fills that were produced
 * purely by consuming order-book liquidity (execution.cpp). It never
 * feeds back into fills or into any strategy's sizing decisions - doing
 * that would blur the responsibility boundary in spec section 12 (the
 * execution engine alone produces fills) and would let a strategy quietly
 * "simulate its own fills" through the back door (Rule 7, section 40).
 *
 * Formula (a square-root participation law, the same functional form used
 * by e.g. Almgren-Chriss-style temporary-impact terms, but NOT a fit or
 * reproduction of any specific published model - see limitations below):
 *
 *     impact_bps  = eta * sigma * sqrt(participation_rate) * 10000
 *     impact_cost = (impact_bps / 10000) * executed_notional
 *
 * where:
 *     eta                 - free calibration constant (config, unitless).
 *                            The caller is responsible for choosing and
 *                            justifying it; this model does not calibrate
 *                            itself against any dataset.
 *     sigma               - short-horizon volatility of the traded
 *                            instrument over the execution window, as a
 *                            fraction (e.g. 0.02 = 2%). Computed by the
 *                            caller and passed in; this function does not
 *                            compute volatility itself.
 *     participation_rate  - executed_quantity / market_volume_over_window.
 *
 * Limitations (must accompany any reported number - see docs/PHASE2.md):
 *   - eta is not fit to any real dataset here; changing it changes the
 *     answer by construction, so the number is only ever "an estimate
 *     under an assumed eta", never a measured fact.
 *   - Ignores order-book shape/depth beyond what already went into the
 *     fills, momentum, information leakage, and permanent vs. temporary
 *     impact decay - it is a single instantaneous number, not a curve.
 *   - Assumes impact scales with sqrt(participation); this functional
 *     form is a common modeling choice, not something this project has
 *     validated against real execution data.
 *   - Explicitly NOT the Almgren-Chriss model, and must not be described
 *     as reproducing it - it borrows only the square-root functional
 *     shape of the temporary-impact term.
 *   - Degenerate inputs (zero market volume, zero executed quantity, or
 *     non-finite volatility) return an all-zero estimate rather than
 *     dividing by zero or propagating NaN.
 */
struct MarketImpactConfig {
    double eta = 0.1; // calibration constant, config-only, unitless
};

struct MarketImpactEstimate {
    double participation_rate = 0.0; // executed_quantity / market_volume_over_window
    double impact_bps = 0.0;         // estimated impact, in bps of executed notional
    double impact_cost = 0.0;        // impact_bps translated into currency
};

/**
 * Estimate the impact-attributable share of execution cost for a
 * completed (or partially completed) execution.
 *
 * Returns an all-zero estimate if market_volume_over_window == 0,
 * executed_quantity == 0, or volatility <= 0 - there is nothing
 * meaningful to attribute impact to in those cases.
 */
MarketImpactEstimate estimate_market_impact(
    uint64_t executed_quantity,
    uint64_t market_volume_over_window,
    double volatility,
    double avg_execution_price,
    const MarketImpactConfig& config
);

#endif