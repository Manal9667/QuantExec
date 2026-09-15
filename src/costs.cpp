#include "costs.h"

TransactionCostBreakdown compute_transaction_costs(
    const ExecutionResult& result,
    const TransactionCostConfig& config
) {
    TransactionCostBreakdown out;

    double executed_notional = 0.0;
    for (const auto& fill : result.fills) {
        const double notional = fill.trade.price * static_cast<double>(fill.trade.qty);
        executed_notional += notional;
        out.commission += notional * (config.commission_bps / 10000.0);
        out.exchange_fees += notional * (config.exchange_fee_bps / 10000.0);
        out.fixed_fees += config.fixed_fee_per_fill;
    }

    // estimated_spread_cost is a fraction of the arrival mid price (see
    // execution.h). Scale it by executed notional so it sits in currency
    // terms alongside commission and fees rather than as a bare fraction.
    out.spread_cost = result.estimated_spread_cost * executed_notional;

    out.total_cost = out.commission + out.exchange_fees + out.fixed_fees + out.spread_cost;

    if (executed_notional > 0.0) {
        out.total_cost_bps = (out.total_cost / executed_notional) * 10000.0;
    }

    return out;
}