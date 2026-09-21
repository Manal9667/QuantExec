#include "../include/algorithms.h"
#include "test_util.h"
#include <iostream>
#include <cassert>
#include <numeric>
#include <stdexcept>


/**
 * Test 1: TWAP divides evenly
 */
TEST(AlgorithmsTest, test_twap_divides_evenly) {
    TWAPAlgorithm twap;
    auto orders = twap.generate_orders(1, OrderSide::Buy, 1000, 100.0, 10);
    
    assert_eq("10 orders generated", orders.size(), 10UL);
    
    // Each should be 100 shares
    uint64_t total = 0;
    for (const auto& o : orders) {
        total += o.qty;
        assert_eq("each order qty is 100", o.qty, 100UL);
    }
    
    assert_eq("total qty is 1000", total, 1000UL);
}

/**
 * Test 2: TWAP handles remainder
 */
TEST(AlgorithmsTest, test_twap_handles_remainder) {
    TWAPAlgorithm twap;
    // 1000 / 3 = 333 remainder 1
    // Should be [334, 333, 333]
    auto orders = twap.generate_orders(1, OrderSide::Buy, 1000, 100.0, 3);
    
    assert_eq("3 orders", orders.size(), 3UL);
    
    uint64_t total = 0;
    for (const auto& o : orders) {
        total += o.qty;
    }
    assert_eq("total is 1000", total, 1000UL);
    
    // First should have remainder
    assert_eq("first order has remainder", orders[0].qty, 334UL);
    assert_eq("second order", orders[1].qty, 333UL);
    assert_eq("third order", orders[2].qty, 333UL);
}

/**
 * Test 3: VWAP with uniform profile equals TWAP
 */
TEST(AlgorithmsTest, test_vwap_uniform_matches_twap) {
    TWAPAlgorithm twap;
    VWAPAlgorithm vwap;
    
    auto twap_orders = twap.generate_orders(1, OrderSide::Buy, 1000, 100.0, 4);
    
    // VWAP without profile defaults to uniform
    auto vwap_orders = vwap.generate_orders(2, OrderSide::Buy, 1000, 100.0, 4);
    
    assert_eq("same number of orders", vwap_orders.size(), twap_orders.size());
    
    // Check quantities match
    for (size_t i = 0; i < twap_orders.size(); ++i) {
        assert_eq("orders have same qty", vwap_orders[i].qty, twap_orders[i].qty);
    }
}

/**
 * Test 4: VWAP with profile
 */
TEST(AlgorithmsTest, test_vwap_with_profile) {
    VWAPAlgorithm vwap;
    // Profile: 40% early, 30%, 20%, 10%
    std::vector<double> profile = {0.4, 0.3, 0.2, 0.1};
    vwap.set_volume_profile(profile);
    
    auto orders = vwap.generate_orders(1, OrderSide::Buy, 1000, 100.0, 4);
    
    assert_eq("4 orders", orders.size(), 4UL);
    
    // Should roughly follow: 400, 300, 200, 100
    assert_eq("first order ~400", orders[0].qty, 400UL);
    assert_eq("second order ~300", orders[1].qty, 300UL);
    assert_eq("third order ~200", orders[2].qty, 200UL);
    assert_eq("fourth order ~100", orders[3].qty, 100UL);
    
    // Verify total
    uint64_t total = 0;
    for (const auto& o : orders) {
        total += o.qty;
    }
    assert_eq("total is 1000", total, 1000UL);
}

/**
 * Test 5: VWAP skewed profile
 */
TEST(AlgorithmsTest, test_vwap_skewed_profile) {
    VWAPAlgorithm vwap;
    // Skewed: 70% early, 30% later
    std::vector<double> profile = {0.7, 0.3};
    vwap.set_volume_profile(profile);
    
    auto orders = vwap.generate_orders(1, OrderSide::Buy, 1000, 100.0, 2);
    
    assert_eq("2 orders", orders.size(), 2UL);
    assert_eq("first order 700", orders[0].qty, 700UL);
    assert_eq("second order 300", orders[1].qty, 300UL);
}

/**
 * Test 6: Algorithm names
 */
TEST(AlgorithmsTest, test_algorithm_names) {
    TWAPAlgorithm twap;
    VWAPAlgorithm vwap;
    AdaptiveAlgorithm adaptive;
    
    assert_true("TWAP name correct", twap.name() == "TWAP");
    assert_true("VWAP name correct", vwap.name() == "VWAP");
    assert_true("Adaptive name correct", adaptive.name() == "Adaptive");
}

/**
 * Test 7: Child order IDs are unique
 */
TEST(AlgorithmsTest, test_child_order_ids_unique) {
    TWAPAlgorithm twap;
    auto orders = twap.generate_orders(5, OrderSide::Buy, 1000, 100.0, 5);
    
    // IDs should be: 5000, 5001, 5002, 5003, 5004
    for (size_t i = 0; i < orders.size(); ++i) {
        uint64_t expected_id = 5000 + i;
        assert_eq("order id", orders[i].id, expected_id);
    }
}

/**
 * Test 8: Orders have correct side and type
 */
TEST(AlgorithmsTest, test_order_side_and_type) {
    TWAPAlgorithm twap;
    auto orders = twap.generate_orders(1, OrderSide::Sell, 500, 99.5, 2);
    
    for (const auto& o : orders) {
        assert_true("side is sell", o.side == OrderSide::Sell);
        assert_true("type is limit", o.type == OrderType::Limit);
        assert_eq("price is correct", o.price, 99.5);
    }
}

/**
 * Test 9: Large order (stress test)
 */
TEST(AlgorithmsTest, test_large_order) {
    TWAPAlgorithm twap;
    uint64_t huge_qty = 1000000;  // 1 million shares
    auto orders = twap.generate_orders(1, OrderSide::Buy, huge_qty, 100.0, 100);
    
    assert_eq("100 orders", orders.size(), 100UL);
    
    uint64_t total = 0;
    for (const auto& o : orders) {
        total += o.qty;
    }
    assert_eq("total qty is 1M", total, huge_qty);
}

/**
 * Test 10: VWAP handles profile longer than num_slices
 */
TEST(AlgorithmsTest, test_vwap_long_profile) {
    VWAPAlgorithm vwap;
    // Profile with 10 buckets, but only request 5 slices
    std::vector<double> profile = {0.1, 0.15, 0.2, 0.2, 0.15, 0.1, 0.05, 0.03, 0.01, 0.01};
    vwap.set_volume_profile(profile);
    
    auto orders = vwap.generate_orders(1, OrderSide::Buy, 1000, 100.0, 5);
    
    // Should only use first 5 buckets of profile
    assert_eq("5 orders", orders.size(), 5UL);
    
    uint64_t total = 0;
    for (const auto& o : orders) {
        total += o.qty;
    }
    assert_eq("total qty is 1000", total, 1000UL);
}

// ===========================================================================
// AdaptiveAlgorithm::next_order_qty() - price-adaptive sizing
// ===========================================================================

/**
 * Adaptive 1: at arrival price the pace is exactly base_participation of
 * the remaining quantity (the neutral case, no price signal).
 */
TEST(AlgorithmsTest, test_adaptive_neutral_price_paces_off_remaining) {
    AdaptiveAlgorithm adaptive;  // base 0.1, sensitivity 5.0
    // mid == arrival -> favorability 0 -> 10% of 1000 remaining.
    assert_eq("neutral price executes base_participation of remaining",
              adaptive.next_order_qty(100.0, 100.0, OrderSide::Buy, 1000), 100UL);
}

/**
 * Adaptive 2: a BUY speeds up when the price is BELOW arrival (favorable).
 */
TEST(AlgorithmsTest, test_adaptive_buy_accelerates_when_price_favorable) {
    AdaptiveAlgorithm adaptive;  // base 0.1, sensitivity 5.0
    // mid 98 vs arrival 100 -> favorability +0.02 -> 0.1*(1+5*0.02)=0.11.
    uint64_t favorable = adaptive.next_order_qty(98.0, 100.0, OrderSide::Buy, 1000);
    uint64_t neutral = adaptive.next_order_qty(100.0, 100.0, OrderSide::Buy, 1000);
    assert_eq("favorable BUY price sizes larger than neutral", favorable, 110UL);
    assert_true("favorable > neutral", favorable > neutral);
}

/**
 * Adaptive 3: a BUY slows down when the price is ABOVE arrival (unfavorable),
 * but still makes some progress.
 */
TEST(AlgorithmsTest, test_adaptive_buy_decelerates_when_price_unfavorable) {
    AdaptiveAlgorithm adaptive;
    // mid 102 vs arrival 100 -> favorability -0.02 -> 0.1*(1-0.1)=0.09.
    uint64_t unfavorable = adaptive.next_order_qty(102.0, 100.0, OrderSide::Buy, 1000);
    assert_eq("unfavorable BUY price sizes smaller than neutral", unfavorable, 90UL);
    assert_true("unfavorable still makes progress (>0)", unfavorable > 0UL);
}

/**
 * Adaptive 4: SELL is the mirror image - favorable when the price is ABOVE
 * arrival.
 */
TEST(AlgorithmsTest, test_adaptive_sell_is_symmetric) {
    AdaptiveAlgorithm adaptive;
    // SELL favorable when mid > arrival.
    uint64_t sell_favorable = adaptive.next_order_qty(102.0, 100.0, OrderSide::Sell, 1000);
    uint64_t sell_unfavorable = adaptive.next_order_qty(98.0, 100.0, OrderSide::Sell, 1000);
    assert_eq("favorable SELL price (mid>arrival) sizes larger", sell_favorable, 110UL);
    assert_eq("unfavorable SELL price (mid<arrival) sizes smaller", sell_unfavorable, 90UL);
}

/**
 * Adaptive 5: the min_order_qty floor guarantees forward progress even when
 * the computed size rounds to 0 (small remaining, or strongly unfavorable).
 */
TEST(AlgorithmsTest, test_adaptive_min_qty_guarantees_progress) {
    AdaptiveAlgorithm adaptive;  // min_order_qty defaults to 1
    // 10% of 3 = 0.3 -> rounds to 0 -> floored to min(1, remaining).
    assert_eq("small remaining still trades at least the floor",
              adaptive.next_order_qty(100.0, 100.0, OrderSide::Buy, 3), 1UL);
    // Strongly unfavorable BUY (mid far above arrival) drives the fraction
    // to 0, but the floor still makes progress.
    assert_eq("strongly unfavorable price still trades the floor",
              adaptive.next_order_qty(1000.0, 100.0, OrderSide::Buy, 1000), 1UL);
}

/**
 * Adaptive 6: the per-event fraction is capped by max_participation, and the
 * order is never larger than the remaining parent quantity.
 */
TEST(AlgorithmsTest, test_adaptive_clamps_to_remaining) {
    AdaptiveAlgorithm adaptive(0.5, 20.0, 1, 1.0);
    // favorability (100-90)/100 = 0.1 -> 0.5*(1+20*0.1)=1.5, capped at 1.0,
    // so it would clear 100% of remaining this event.
    assert_eq("fraction capped at max_participation -> clears remaining",
              adaptive.next_order_qty(90.0, 100.0, OrderSide::Buy, 200), 200UL);
}

/**
 * Adaptive 7: no price signal (non-positive mid) falls back to neutral pace.
 */
TEST(AlgorithmsTest, test_adaptive_no_price_signal_is_neutral) {
    AdaptiveAlgorithm adaptive;
    assert_eq("missing mid price -> neutral base pace",
              adaptive.next_order_qty(0.0, 100.0, OrderSide::Buy, 1000), 100UL);
}

/**
 * Adaptive 8: zero remaining never generates another order.
 */
TEST(AlgorithmsTest, test_adaptive_zero_remaining_yields_zero) {
    AdaptiveAlgorithm adaptive;
    assert_eq("filled parent order generates no further child order",
              adaptive.next_order_qty(98.0, 100.0, OrderSide::Buy, 0), 0UL);
}

/**
 * Adaptive 9: like POV, a precomputed schedule would be fake, so
 * generate_orders() throws rather than delegating to TWAP.
 */
TEST(AlgorithmsTest, test_adaptive_generate_orders_throws) {
    AdaptiveAlgorithm adaptive;
    bool threw = false;
    try {
        adaptive.generate_orders(1, OrderSide::Buy, 1000, 100.0, 10);
    } catch (const std::logic_error&) {
        threw = true;
    }
    assert_true("generate_orders() throws instead of faking an adaptive schedule", threw);
}

/**
 * Adaptive 10: fully deterministic - identical inputs give identical outputs
 * (spec section 27).
 */
TEST(AlgorithmsTest, test_adaptive_is_deterministic) {
    AdaptiveAlgorithm adaptive(0.15, 3.0, 2, 0.8);
    uint64_t a = adaptive.next_order_qty(97.5, 100.0, OrderSide::Buy, 5000);
    uint64_t b = adaptive.next_order_qty(97.5, 100.0, OrderSide::Buy, 5000);
    assert_eq("same inputs -> same output", a, b);
}

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    int rc = RUN_ALL_TESTS();
    return rc;
}
