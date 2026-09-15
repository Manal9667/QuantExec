#ifndef EXECUTOR_EXECUTION_H
#define EXECUTOR_EXECUTION_H

#include "engine.h"
#include "market_data.h"
#include "algorithms.h"
#include <vector>

struct ExecutionFill {
    Trade trade;
    uint64_t timestamp_ms = 0;
    double bid = 0.0;
    double ask = 0.0;
    uint64_t market_volume = 0;
};

struct ExecutionResult {
    uint64_t requested_quantity = 0;
    uint64_t filled_quantity = 0;
    double arrival_price = 0.0;
    double average_execution_price = 0.0;
    double market_vwap = 0.0;
    double fill_rate = 0.0;
    double slippage = 0.0;
    double implementation_shortfall = 0.0;
    double vwap_deviation = 0.0;
    uint64_t completion_time_ms = 0;

    // --- Market impact decomposition (Phase 3, section 3.5) -----------------
    // (unchanged from Phase 1 — see original file for the full comment)
    double market_price_drift = 0.0;
    double estimated_spread_cost = 0.0;
    double estimated_execution_cost = 0.0;

    std::vector<ExecutionFill> fills;
};

class ExecutionSession {
public:
    ExecutionResult run(
        MarketDataSource& source,
        const std::vector<Order>& child_orders,
        double arrival_price
    );

    /**
     * run_with_latency() - Phase 2, spec section 30.
     *
     * Identical to run() except that each child order's actual submission
     * to the matching engine is delayed by latency_ms after the event that
     * "decided" it, modeling:
     *
     *     strategy decision -> latency -> order becomes executable
     *
     * "Decision" happens at the same cadence as run(): one child order
     * becomes decided per replayed market event, in order. The decided
     * order is queued and only actually submitted once an event's
     * timestamp reaches (decision_timestamp + latency_ms). If replay ends
     * before a queued order's delay has elapsed, that order is never
     * submitted and shows up as unfilled remaining quantity - this is
     * realistic behavior (a late decision that never got to trade before
     * the window closed), not a bug.
     *
     * latency_ms = 0 reduces exactly to run(): every order becomes ready
     * on the same event that decided it, which is what run() already does.
     * This equivalence is covered by a unit test rather than asserted here.
     *
     * This is a fixed, explicit delay - not an attempt to simulate real
     * network/exchange infrastructure (spec section 30 is explicit that
     * this is out of scope). It exists to make timing assumptions visible
     * and testable, nothing more.
     */
    ExecutionResult run_with_latency(
        MarketDataSource& source,
        const std::vector<Order>& child_orders,
        double arrival_price,
        uint64_t latency_ms
    );

    /**
     * run_pov() - Phase 2, spec section 29.
     *
     * Runs a live Percentage-of-Volume execution: unlike run()/
     * run_with_latency(), there is no precomputed child_orders list.
     * Each replayed market event's realized volume is fed to
     * pov.next_order_qty() to decide that event's child order size
     * on the fly, which is then submitted through the same matching
     * engine / liquidity-consuming fill path as every other strategy
     * (spec section 12: the strategy decides sizing, the engine alone
     * produces fills).
     *
     * total_qty is the parent order size POV is targeting; if the replay
     * window ends before that target is reached (not enough realized
     * volume), the result is underfilled - see ExecutionResult::fill_rate.
     */
    ExecutionResult run_pov(
        MarketDataSource& source,
        OrderSide side,
        uint64_t total_qty,
        double limit_price,
        const POVAlgorithm& pov,
        double arrival_price
    );

    const MatchingEngine& engine() const { return engine_; }

private:
    MatchingEngine engine_;
};

#endif