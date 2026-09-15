#ifndef EXECUTOR_COSTS_H
#define EXECUTOR_COSTS_H

#include "execution.h"

/**
 * TransactionCostModel
 *
 * A separate, explicitly configurable transaction-cost component
 * (spec section 19). This is deliberately NOT folded into TWAP/VWAP
 * or into ExecutionSession::run() - strategies and the matching
 * engine only ever produce fills; cost assumptions live here, in one
 * place, so they can change without touching fill logic.
 *
 * Scope for Phase 1: commission, a flat exchange/regulatory fee, and
 * a fixed per-fill ticket charge, all configurable. These are
 * combined with the spread-cost estimate ExecutionSession already
 * computes (see execution.h's ExecutionResult::estimated_spread_cost)
 * to produce one total-cost figure in both currency and basis points.
 *
 * Explicitly NOT modeled here (out of scope for Phase 1):
 *   - maker/taker fee differentiation
 *   - venue-specific fee schedules
 *   - market impact beyond the spread-cost estimate already in
 *     ExecutionResult (see execution.h's comment on
 *     estimated_execution_cost for why that split stops where it does)
 */
struct TransactionCostConfig {
    double commission_bps = 0.0;      // bps of notional charged as commission
    double exchange_fee_bps = 0.0;     // bps of notional charged as exchange/regulatory fees
    double fixed_fee_per_fill = 0.0;   // flat currency charge per fill record
};

struct TransactionCostBreakdown {
    double commission = 0.0;      // currency
    double exchange_fees = 0.0;   // currency
    double fixed_fees = 0.0;      // currency
    double spread_cost = 0.0;     // currency (from ExecutionResult.estimated_spread_cost)
    double total_cost = 0.0;      // currency, sum of the above
    double total_cost_bps = 0.0;  // total_cost as bps of executed notional (0 if nothing filled)
};

/**
 * Compute the cost breakdown for a completed execution.
 *
 * Reads only `fills`, `filled_quantity`, and `estimated_spread_cost`
 * from `result` - it does not recompute or alter slippage,
 * implementation shortfall, or any other ExecutionResult field.
 */
TransactionCostBreakdown compute_transaction_costs(
    const ExecutionResult& result,
    const TransactionCostConfig& config
);

#endif