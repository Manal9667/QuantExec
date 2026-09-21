#include "../include/execution.h"
#include "test_util.h"
#include "../include/algorithms.h"
#include "../include/market.h"
#include "../include/impact.h"
#include <cassert>
#include <cmath>
#include <iostream>
#include <stdexcept>

/**
 * Phase 2 tests (spec sections 29-31): POV, the latency model, and the
 * simplified market impact model. Uses the same hand-rolled assert
 * framework as the other test_*.cpp files - no external test dependency.
 */


namespace {
}

// ===========================================================================
// POVAlgorithm::next_order_qty()
// ===========================================================================

TEST(Phase2Test, test_pov_proportional_sizing) {
    POVAlgorithm pov(0.10); // 10% participation, no min/max
    // Market traded 5000 this event -> attempt ~500 (spec section 29 example)
    assert_true("10% of 5000 traded volume is 500", pov.next_order_qty(5000, 100000) == 500);
}

TEST(Phase2Test, test_pov_zero_market_volume_yields_zero_order) {
    POVAlgorithm pov(0.10);
    assert_true("no market volume this event -> no order", pov.next_order_qty(0, 100000) == 0);
}

TEST(Phase2Test, test_pov_clamped_to_remaining_quantity) {
    POVAlgorithm pov(0.5);
    // 50% of 1000 = 500, but only 300 shares remain on the parent order.
    assert_true("order size never exceeds remaining parent quantity",
                pov.next_order_qty(1000, 300) == 300);
}

TEST(Phase2Test, test_pov_zero_remaining_yields_zero_order) {
    POVAlgorithm pov(0.5);
    assert_true("fully filled parent order never generates another child order",
                pov.next_order_qty(1000, 0) == 0);
}

TEST(Phase2Test, test_pov_max_order_qty_cap) {
    POVAlgorithm pov(0.5, /*min_order_qty=*/1, /*max_order_qty=*/100);
    // 50% of 1000 = 500, but capped to 100 by max_order_qty.
    assert_true("max_order_qty caps a single child order",
                pov.next_order_qty(1000, 100000) == 100);
}

TEST(Phase2Test, test_pov_min_order_qty_snaps_to_zero) {
    POVAlgorithm pov(0.01, /*min_order_qty=*/10);
    // 1% of 50 = 0.5 -> rounds to 1, which is below min_order_qty=10, so
    // the strategy skips this event rather than rounding up (which would
    // inflate the realized participation rate above target).
    assert_true("below-floor size is skipped, not rounded up to the floor",
                pov.next_order_qty(50, 100000) == 0);
}

TEST(Phase2Test, test_pov_generate_orders_throws) {
    POVAlgorithm pov(0.1);
    bool threw = false;
    try {
        pov.generate_orders(1, OrderSide::Buy, 1000, 100.0, 10);
    } catch (const std::logic_error&) {
        threw = true;
    }
    assert_true("generate_orders() throws instead of faking a precomputed POV schedule", threw);
}

// ===========================================================================
// ExecutionSession::run_pov()
// ===========================================================================

TEST(Phase2Test, test_run_pov_targets_participation_rate) {
    // Three ticks, each trading 1000 shares of market volume and quoting
    // deep liquidity (10,000 shares) so POV's sizing decision - not
    // available liquidity - is the binding constraint.
    VectorMarketSource source({
        {100.0, 0.0, 99.5, 100.0, 10000, 10000, 1000, 1000, 1, {{99.5, 10000}}, {{100.0, 10000}}},
        {100.0, 0.0, 99.5, 100.0, 10000, 10000, 2000, 1000, 2, {{99.5, 10000}}, {{100.0, 10000}}},
        {100.0, 0.0, 99.5, 100.0, 10000, 10000, 3000, 1000, 3, {{99.5, 10000}}, {{100.0, 10000}}},
    });
    POVAlgorithm pov(0.10); // target 10% of each tick's traded volume
    ExecutionSession session;
    const auto result = session.run_pov(source, OrderSide::Buy, /*total_qty=*/10000, 1000.0, pov, 99.75);

    // 10% of 1000 per tick, 3 ticks -> 300 shares total.
    assert_true("run_pov fills 10% of each tick's realized volume", result.filled_quantity == 300);
    assert_true("requested_quantity reports the POV target, not what was filled",
                result.requested_quantity == 10000);
    assert_true("fill_rate reflects the shortfall against the target",
                close_enough(result.fill_rate, 300.0 / 10000.0));
}

TEST(Phase2Test, test_run_pov_stops_once_target_reached) {
    VectorMarketSource source({
        {100.0, 0.0, 99.5, 100.0, 10000, 10000, 1000, 1000, 1, {{99.5, 10000}}, {{100.0, 10000}}},
        {100.0, 0.0, 99.5, 100.0, 10000, 10000, 2000, 1000, 2, {{99.5, 10000}}, {{100.0, 10000}}},
        {100.0, 0.0, 99.5, 100.0, 10000, 10000, 3000, 1000, 3, {{99.5, 10000}}, {{100.0, 10000}}},
    });
    POVAlgorithm pov(0.10);
    ExecutionSession session;
    // Target only 150 shares - should finish partway through tick 2 and
    // never touch tick 3's volume.
    const auto result = session.run_pov(source, OrderSide::Buy, /*total_qty=*/150, 1000.0, pov, 99.75);

    assert_true("run_pov stops submitting once the target quantity is reached",
                result.filled_quantity == 150);
    assert_true("fill_rate is 100% once the (small) target is fully reached",
                close_enough(result.fill_rate, 1.0));
}

// ===========================================================================
// ExecutionSession::run_adaptive()
// ===========================================================================

TEST(Phase2Test, test_run_adaptive_completes_and_is_engine_driven) {
    // Ten ticks of deep, constant liquidity so adaptive's sizing - not
    // available liquidity - is the only constraint. With base 0.5 the
    // remaining quantity decays fast enough to fully complete within the
    // window, and the min-qty floor clears the tail.
    std::vector<MarketState> ticks;
    for (int i = 0; i < 10; ++i) {
        ticks.push_back({100.0, 0.0, 99.5, 100.0, 10000, 10000,
                         static_cast<uint64_t>(1000 * (i + 1)), 1000,
                         static_cast<uint64_t>(i + 1),
                         {{99.5, 10000}}, {{100.0, 10000}}});
    }
    VectorMarketSource source(ticks);
    AdaptiveAlgorithm adaptive(0.5); // aggressive base pace
    ExecutionSession session;
    const auto result = session.run_adaptive(source, OrderSide::Buy, /*total_qty=*/100, 1000.0, adaptive, 99.75);

    assert_true("run_adaptive completes the parent order over a long-enough window",
                result.filled_quantity == 100);
    assert_true("fill_rate is 100% once completed", close_enough(result.fill_rate, 1.0));
    assert_true("every fill has a real execution price from the engine",
                !result.fills.empty() && result.fills.front().trade.price > 0.0);
}

TEST(Phase2Test, test_run_adaptive_generate_orders_throws) {
    AdaptiveAlgorithm adaptive;
    bool threw = false;
    try {
        adaptive.generate_orders(1, OrderSide::Buy, 1000, 100.0, 10);
    } catch (const std::logic_error&) {
        threw = true;
    }
    assert_true("adaptive generate_orders() throws instead of faking a schedule", threw);
}

TEST(Phase2Test, test_run_adaptive_is_reproducible) {
    // Identical dataset + config must produce identical results (spec 27).
    std::vector<MarketState> ticks;
    for (int i = 0; i < 8; ++i) {
        // Declining price (favorable for a BUY) exercises the adaptive path.
        double px = 100.0 - i * 0.1;
        ticks.push_back({px, 0.0, px - 0.25, px + 0.25, 10000, 10000,
                         static_cast<uint64_t>(1000 * (i + 1)), 1000,
                         static_cast<uint64_t>(i + 1),
                         {{px - 0.25, 10000}}, {{px + 0.25, 10000}}});
    }
    AdaptiveAlgorithm adaptive(0.2, 5.0);
    ExecutionSession s1, s2;
    VectorMarketSource src1(ticks), src2(ticks);
    const auto r1 = s1.run_adaptive(src1, OrderSide::Buy, 500, 1000.0, adaptive, 100.0);
    const auto r2 = s2.run_adaptive(src2, OrderSide::Buy, 500, 1000.0, adaptive, 100.0);
    assert_true("same filled quantity across identical runs", r1.filled_quantity == r2.filled_quantity);
    assert_true("same fill count across identical runs", r1.fills.size() == r2.fills.size());
    assert_true("same average execution price across identical runs",
                close_enough(r1.average_execution_price, r2.average_execution_price));
}

// ===========================================================================
// ExecutionSession::run_with_latency()
// ===========================================================================

TEST(Phase2Test, test_latency_zero_matches_run) {
    VectorMarketSource source({
        {100.0, 0.0, 99.0, 100.0, 100, 100, 1000, 100, 1, {{99.0, 100}}, {{100.0, 100}, {100.5, 200}}},
        {100.0, 0.0, 99.0, 100.0, 100, 100, 1200, 200, 2, {{99.0, 100}}, {{100.0, 100}, {100.5, 200}}}
    });
    TWAPAlgorithm twap;
    const auto orders = twap.generate_orders(10, OrderSide::Buy, 250, 1000.0, 2);

    ExecutionSession session_plain;
    const auto plain = session_plain.run(source, orders, 99.5);

    ExecutionSession session_latency;
    const auto delayed = session_latency.run_with_latency(source, orders, 99.5, /*latency_ms=*/0);

    assert_true("zero latency fills the same quantity as run()",
                delayed.filled_quantity == plain.filled_quantity);
    assert_true("zero latency produces the same fill count as run()",
                delayed.fills.size() == plain.fills.size());
    assert_true("zero latency produces the same average execution price as run()",
                close_enough(delayed.average_execution_price, plain.average_execution_price));
}

TEST(Phase2Test, test_latency_delays_execution_to_a_later_event) {
    // Two ticks 1ms apart. With 500ms latency, an order decided on tick 1
    // (t=1ms) cannot execute on tick 1 itself - only tick 2, if at all.
    VectorMarketSource source({
        {100.0, 0.0, 99.0, 100.0, 100, 100, 1000, 100, 1, {{99.0, 100}}, {{100.0, 500}}},
        {100.0, 0.0, 99.0, 100.0, 100, 100, 1200, 200, 600, {{99.0, 100}}, {{100.0, 500}}}
    });
    TWAPAlgorithm twap;
    // One slice per tick, 2 ticks -> 2 child orders of 100 shares each.
    const auto orders = twap.generate_orders(10, OrderSide::Buy, 200, 1000.0, 2);

    ExecutionSession session;
    const auto result = session.run_with_latency(source, orders, 99.5, /*latency_ms=*/500);

    // Order 1 decided at t=1ms, ready at t=501ms -> executes at t=600ms (tick 2).
    // Order 2 decided at t=600ms, ready at t=1100ms -> no later tick exists,
    // so it never executes.
    assert_true("only the order that became ready before replay ended is filled",
                result.filled_quantity == 100);
    assert_true("the filled order executed on the tick where its latency had elapsed",
                result.completion_time_ms == 600);
    assert_true("the order still queued when replay ended shows up as unfilled",
                close_enough(result.fill_rate, 0.5));
}

// ===========================================================================
// estimate_market_impact()
// ===========================================================================

TEST(Phase2Test, test_impact_zero_inputs_are_safe) {
    MarketImpactConfig config;
    auto zero_volume = estimate_market_impact(1000, 0, 0.02, 100.0, config);
    assert_true("zero market volume returns an all-zero estimate (no div-by-zero)",
                close_enough(zero_volume.impact_bps, 0.0) && close_enough(zero_volume.impact_cost, 0.0));

    auto zero_qty = estimate_market_impact(0, 100000, 0.02, 100.0, config);
    assert_true("zero executed quantity returns an all-zero estimate",
                close_enough(zero_qty.impact_bps, 0.0));

    auto zero_vol = estimate_market_impact(1000, 100000, 0.0, 100.0, config);
    assert_true("zero volatility returns an all-zero estimate",
                close_enough(zero_vol.impact_bps, 0.0));
}

TEST(Phase2Test, test_impact_scales_with_sqrt_participation) {
    MarketImpactConfig config;
    config.eta = 0.1;
    // participation = 10,000 / 100,000 = 0.10
    auto low = estimate_market_impact(10000, 100000, 0.02, 100.0, config);
    // participation = 40,000 / 100,000 = 0.40 (4x the participation of `low`)
    auto high = estimate_market_impact(40000, 100000, 0.02, 100.0, config);

    assert_true("participation_rate is computed as executed/market volume",
                close_enough(low.participation_rate, 0.10) && close_enough(high.participation_rate, 0.40));
    // sqrt(0.40)/sqrt(0.10) = sqrt(4) = 2, so impact_bps should exactly double.
    assert_true("impact scales with sqrt(participation), not linearly",
                close_enough(high.impact_bps, low.impact_bps * 2.0));
}

TEST(Phase2Test, test_impact_scales_linearly_with_eta) {
    MarketImpactConfig low_eta{0.05};
    MarketImpactConfig high_eta{0.10};
    auto low = estimate_market_impact(10000, 100000, 0.02, 100.0, low_eta);
    auto high = estimate_market_impact(10000, 100000, 0.02, 100.0, high_eta);
    assert_true("doubling eta exactly doubles impact_bps (linear calibration constant)",
                close_enough(high.impact_bps, low.impact_bps * 2.0));
}

TEST(Phase2Test, test_impact_cost_matches_bps_and_notional) {
    MarketImpactConfig config{0.1};
    auto est = estimate_market_impact(1000, 10000, 0.02, 50.0, config);
    const double expected_notional = 50.0 * 1000.0;
    const double expected_cost = (est.impact_bps / 10000.0) * expected_notional;
    assert_true("impact_cost is impact_bps applied to executed notional",
                close_enough(est.impact_cost, expected_cost));
}

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    int rc = RUN_ALL_TESTS();
    return rc;
}
