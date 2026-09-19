// Step 4: execution realism under stressed market conditions.
//
// Every test here runs the same TWAP execution against both a BUY and a
// SELL parent order over one of the stress datasets in datasets/stress/,
// then checks the invariants a trustworthy execution report must hold
// regardless of how ugly the underlying market data is:
//   - filled + unfilled == requested (unfilled quantity is never hidden)
//   - slippage/shortfall signs are correct for both sides (a buy that
//     executes above arrival price is a *cost*; a sell that executes above
//     arrival price is a *gain* - the sign must flip, not just the label)
//   - the engine never crashes or produces non-finite output on zero
//     volume, wide spreads, gaps, or rapid price swings.
//
// Run from the repo root (CMakeLists sets WORKING_DIRECTORY) since paths
// are relative to datasets/stress/.

#include "../include/execution.h"
#include "../include/algorithms.h"
#include "../include/market_data.h"
#include "test_util.h"
#include <cmath>
#include <iostream>
#include <string>
#include <vector>

struct StressCheck {
    std::string dataset;
    std::string label;
};

// Runs a TWAP execution for the given side over `dataset` and checks the
// cross-cutting invariants every stress dataset must satisfy.
void run_stress_case(const std::string& dataset, const std::string& label, OrderSide side) {
    CsvMarketSource source(dataset);
    assert_true(label + ": dataset loads (" + dataset + ")", source.ok());
    if (!source.ok()) return;

    const uint64_t requested_qty = 1000;
    const double limit_price = (side == OrderSide::Buy) ? 1e9 : 0.0001;  // effectively marketable
    TWAPAlgorithm twap;
    const auto orders = twap.generate_orders(1, side, requested_qty, limit_price, /*slices=*/5);

    ExecutionSession session;
    const double arrival_price = 100.0;  // fixed, comparable reference across all datasets
    const auto result = session.run(source, orders, arrival_price);

    const std::string side_label = (side == OrderSide::Buy) ? "BUY" : "SELL";

    // 1. Unfilled quantity is never hidden: filled + implied-unfilled ==
    //    requested, and filled never exceeds requested.
    assert_true(label + " [" + side_label + "]: filled_quantity <= requested_quantity",
                result.filled_quantity <= result.requested_quantity);
    assert_true(label + " [" + side_label + "]: requested_quantity matches parent order size",
                result.requested_quantity == requested_qty);

    // 2. Every reported metric is finite - a crossed/zero/gapped market
    //    should degrade to zero fill or zero cost, never NaN/inf.
    assert_true(label + " [" + side_label + "]: average_execution_price is finite",
                std::isfinite(result.average_execution_price));
    assert_true(label + " [" + side_label + "]: slippage is finite",
                std::isfinite(result.slippage));
    assert_true(label + " [" + side_label + "]: implementation_shortfall is finite",
                std::isfinite(result.implementation_shortfall));

    // 3. Sign correctness: implementation_shortfall must have the sign
    //    that makes "positive == cost to the parent order", for BOTH
    //    sides. If avg execution price is above arrival:
    //      BUY  -> paid more than the benchmark -> shortfall > 0 (cost)
    //      SELL -> received more than the benchmark -> shortfall < 0 (gain)
    if (result.filled_quantity > 0) {
        const double price_vs_arrival = result.average_execution_price - result.arrival_price;
        if (std::abs(price_vs_arrival) > 1e-9) {
            const bool expect_positive_shortfall = (side == OrderSide::Buy) ? (price_vs_arrival > 0) : (price_vs_arrival < 0);
            const bool shortfall_sign_ok = expect_positive_shortfall
                ? result.implementation_shortfall > 0
                : result.implementation_shortfall < 0;
            assert_true(label + " [" + side_label + "]: implementation_shortfall sign is correct for this side",
                        shortfall_sign_ok);
        }
    }
}

namespace {
const std::vector<StressCheck> kStressCases = {
    {"datasets/stress/wide_spread.csv", "wide_spread"},
    {"datasets/stress/thin_liquidity.csv", "thin_liquidity"},
    {"datasets/stress/price_gap.csv", "price_gap"},
    {"datasets/stress/zero_volume.csv", "zero_volume"},
    {"datasets/stress/incomplete_depth.csv", "incomplete_depth"},
    {"datasets/stress/rapid_price_change.csv", "rapid_price_change"},
};
}  // namespace

// Every stress dataset must satisfy the cross-cutting execution-report
// invariants for BOTH a buy and a sell parent order (see run_stress_case).
TEST(StressTest, invariants_hold_for_every_dataset_both_sides) {
    for (const auto& c : kStressCases) {
        run_stress_case(c.dataset, c.label, OrderSide::Buy);
        run_stress_case(c.dataset, c.label, OrderSide::Sell);
    }
}

// Thin liquidity specifically should produce a PARTIAL fill for a 1000-share
// order against single-digit displayed sizes - if this ever fills 100%,
// either the book isn't respecting displayed size or the test dataset stopped
// being "thin".
TEST(StressTest, thin_liquidity_order_is_not_fully_filled) {
    CsvMarketSource source("datasets/stress/thin_liquidity.csv");
    TWAPAlgorithm twap;
    const auto orders = twap.generate_orders(1, OrderSide::Buy, 1000, 1e9, 5);
    ExecutionSession session;
    const auto result = session.run(source, orders, 100.0);
    assert_true("thin_liquidity: 1000-share order against single-digit sizes is NOT fully filled",
                result.filled_quantity < result.requested_quantity);
}

// Zero volume: no trades should be reported as market volume, but resting
// displayed liquidity (bid_size/ask_size) still allows fills - this documents
// that "zero volume" in this schema means "no *trade* activity was reported",
// not "no liquidity was displayed" (see docs/EXECUTION_ASSUMPTIONS.md).
TEST(StressTest, zero_volume_reports_zero_market_vwap) {
    CsvMarketSource source("datasets/stress/zero_volume.csv");
    TWAPAlgorithm twap;
    const auto orders = twap.generate_orders(1, OrderSide::Buy, 1000, 1e9, 5);
    ExecutionSession session;
    const auto result = session.run(source, orders, 100.0);
    assert_true("zero_volume: market_vwap is 0 when no trade volume was reported",
                result.market_vwap == 0.0);
}

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
