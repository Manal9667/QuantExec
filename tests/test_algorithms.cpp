#include "../include/algorithms.h"
#include "test_util.h"
#include <iostream>
#include <cassert>
#include <numeric>


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

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    int rc = RUN_ALL_TESTS();
    return rc;
}
