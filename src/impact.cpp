#include "impact.h"

#include <cmath>

MarketImpactEstimate estimate_market_impact(
    uint64_t executed_quantity,
    uint64_t market_volume_over_window,
    double volatility,
    double avg_execution_price,
    const MarketImpactConfig& config
) {
    MarketImpactEstimate out;

    if (executed_quantity == 0 || market_volume_over_window == 0 ||
        !(volatility > 0.0) || !std::isfinite(volatility)) {
        return out; // all-zero: nothing meaningful to attribute
    }

    out.participation_rate =
        static_cast<double>(executed_quantity) / static_cast<double>(market_volume_over_window);

    out.impact_bps = config.eta * volatility * std::sqrt(out.participation_rate) * 10000.0;

    const double executed_notional = avg_execution_price * static_cast<double>(executed_quantity);
    out.impact_cost = (out.impact_bps / 10000.0) * executed_notional;

    return out;
}