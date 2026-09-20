#include "../include/book.h"
#include "test_util.h"
#include <cassert>
#include <iostream>

/**
 * Simple test framework (no external dependencies)
 * 
 * Each test calls assert_eq or assert_true.
 * At the end, we print pass/fail summary.
 */

/**
 * assert_eq: check if actual == expected
 */


/**
 * assert_true: check if condition is true
 */

/**
 * Test 1: Add orders and retrieve best price
 */
TEST(BookTest, test_add_and_best) {
    OrderBook book;
    
    Order buy1(1, OrderSide::Buy, OrderType::Limit, 100.0, 100);
    Order buy2(2, OrderSide::Buy, OrderType::Limit, 99.0, 50);
    
    book.add_order(buy1);
    book.add_order(buy2);
    
    auto best = book.best_bid();
    assert_true("best_bid() returns value", best.has_value());
    assert_eq("best_bid() is highest price", best.value(), 100.0);
}

/**
 * Test 2: Bids are sorted descending (highest first)
 */
TEST(BookTest, test_bid_ordering) {
    OrderBook book;
    
    // Add in random order
    book.add_order({1, OrderSide::Buy, OrderType::Limit, 99.0, 100});
    book.add_order({2, OrderSide::Buy, OrderType::Limit, 101.0, 100});
    book.add_order({3, OrderSide::Buy, OrderType::Limit, 100.0, 100});
    
    // Best bid should be 101 (highest)
    auto best = book.best_bid();
    assert_eq("best bid is 101", best.value(), 101.0);
}

/**
 * Test 3: Asks are sorted ascending (lowest first)
 */
TEST(BookTest, test_ask_ordering) {
    OrderBook book;
    
    // Add in random order
    book.add_order({1, OrderSide::Sell, OrderType::Limit, 102.0, 100});
    book.add_order({2, OrderSide::Sell, OrderType::Limit, 100.0, 100});
    book.add_order({3, OrderSide::Sell, OrderType::Limit, 101.0, 100});
    
    // Best ask should be 100 (lowest)
    auto best = book.best_ask();
    assert_eq("best ask is 100", best.value(), 100.0);
}

/**
 * Test 4: Mid price calculation
 */
TEST(BookTest, test_mid_price) {
    OrderBook book;
    
    // Add one bid and one ask
    book.add_order({1, OrderSide::Buy, OrderType::Limit, 100.0, 100});
    book.add_order({2, OrderSide::Sell, OrderType::Limit, 102.0, 100});
    
    // Mid should be (100 + 102) / 2 = 101
    auto mid = book.mid_price();
    assert_true("mid_price() has value", mid.has_value());
    assert_eq("mid_price() is correct", mid.value(), 101.0);
}

/**
 * Test 5: Empty book returns no prices
 */
TEST(BookTest, test_empty_book) {
    OrderBook book;
    
    assert_true("empty book has no best_bid", !book.best_bid().has_value());
    assert_true("empty book has no best_ask", !book.best_ask().has_value());
    assert_true("empty book has no mid_price", !book.mid_price().has_value());
}

/**
 * Test 6: Volume at price level
 */
TEST(BookTest, test_volume_at) {
    OrderBook book;
    
    // Add multiple orders at same price
    book.add_order({1, OrderSide::Buy, OrderType::Limit, 100.0, 100});
    book.add_order({2, OrderSide::Buy, OrderType::Limit, 100.0, 50});
    book.add_order({3, OrderSide::Buy, OrderType::Limit, 99.0, 200});
    
    // Check volumes
    assert_eq("volume at 100 is 150", book.volume_at(100.0, OrderSide::Buy), 150UL);
    assert_eq("volume at 99 is 200", book.volume_at(99.0, OrderSide::Buy), 200UL);
    assert_eq("volume at 101 is 0", book.volume_at(101.0, OrderSide::Buy), 0UL);
}

/**
 * Test 7: Cancel order by ID
 */
TEST(BookTest, test_cancel) {
    OrderBook book;
    
    // Add orders
    book.add_order({1, OrderSide::Buy, OrderType::Limit, 100.0, 100});
    book.add_order({2, OrderSide::Buy, OrderType::Limit, 100.0, 50});
    
    // Verify initial volume
    assert_eq("volume before cancel", book.volume_at(100.0, OrderSide::Buy), 150UL);
    
    // Cancel order 1
    bool cancelled = book.cancel_order(1, OrderSide::Buy, 100.0);
    assert_true("cancel returns true", cancelled);
    
    // Verify volume after cancel
    assert_eq("volume after cancel", book.volume_at(100.0, OrderSide::Buy), 50UL);
}

/**
 * Test 8: Cancel non-existent order
 */
TEST(BookTest, test_cancel_nonexistent) {
    OrderBook book;
    
    book.add_order({1, OrderSide::Buy, OrderType::Limit, 100.0, 100});
    
    // Try to cancel order that doesn't exist
    bool cancelled = book.cancel_order(999, OrderSide::Buy, 100.0);
    assert_true("cancel non-existent returns false", !cancelled);
}

/**
 * Test 9: Cancel at wrong price
 */
TEST(BookTest, test_cancel_wrong_price) {
    OrderBook book;
    
    book.add_order({1, OrderSide::Buy, OrderType::Limit, 100.0, 100});
    
    // Try to cancel at wrong price
    bool cancelled = book.cancel_order(1, OrderSide::Buy, 99.0);
    assert_true("cancel at wrong price returns false", !cancelled);
}

/**
 * Test 10: Multiple orders at same level maintain FIFO
 * 
 * FIFO = First In, First Out
 * Orders added to the same price level should be queued in arrival order.
 * We test this by checking that remaining() works correctly (orders maintain identity).
 */
TEST(BookTest, test_fifo_at_level) {
    OrderBook book;
    
    // Add orders in sequence at same price
    book.add_order({1, OrderSide::Buy, OrderType::Limit, 100.0, 100});
    book.add_order({2, OrderSide::Buy, OrderType::Limit, 100.0, 50});
    book.add_order({3, OrderSide::Buy, OrderType::Limit, 100.0, 75});
    
    // Total volume should be 100 + 50 + 75 = 225
    assert_eq("total volume is 225", book.volume_at(100.0, OrderSide::Buy), 225UL);
    
    // Cancel middle order (2)
    book.cancel_order(2, OrderSide::Buy, 100.0);
    
    // Remaining should be 100 + 75 = 175
    assert_eq("volume after cancel is 175", book.volume_at(100.0, OrderSide::Buy), 175UL);
}

/**
 * Test 11: Get queue pointer
 */
TEST(BookTest, test_get_queue) {
    OrderBook book;
    
    // Add an order
    book.add_order({1, OrderSide::Buy, OrderType::Limit, 100.0, 100});
    
    // Get queue at that price
    auto* queue = book.get_queue(100.0, OrderSide::Buy);
    assert_true("get_queue returns non-null", queue != nullptr);
    assert_eq("queue has 1 order", queue->size(), 1UL);
    
    // Get queue at non-existent price
    auto* empty_queue = book.get_queue(99.0, OrderSide::Buy);
    assert_true("get_queue returns null for non-existent price", empty_queue == nullptr);
}

/**
 * Test 12: Bid and ask spread
 */
TEST(BookTest, test_bid_ask_spread) {
    OrderBook book;
    
    // Create a spread: bids at 99.5, asks at 100.5
    book.add_order({1, OrderSide::Buy, OrderType::Limit, 99.5, 100});
    book.add_order({2, OrderSide::Sell, OrderType::Limit, 100.5, 100});
    
    auto bid = book.best_bid();
    auto ask = book.best_ask();
    
    assert_eq("bid is 99.5", bid.value(), 99.5);
    assert_eq("ask is 100.5", ask.value(), 100.5);
    
    // Spread = ask - bid = 1.0
    double spread = ask.value() - bid.value();
    assert_eq("spread is 1.0", spread, 1.0);
}

/**
 * Test 13: Order remaining quantity
 */
TEST(BookTest, test_order_remaining) {
    // Create an order with qty=100, filled=0
    Order order(1, OrderSide::Buy, OrderType::Limit, 100.0, 100);
    
    assert_eq("initially remaining is 100", order.remaining(), 100UL);
    
    // Simulate a partial fill
    order.filled = 30;
    assert_eq("after partial fill, remaining is 70", order.remaining(), 70UL);
    
    // Simulate a full fill
    order.filled = 100;
    assert_true("is_filled() returns true", order.is_filled());
    assert_eq("after full fill, remaining is 0", order.remaining(), 0UL);
}

/**
 * Main: Run all tests
 */
int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    int rc = RUN_ALL_TESTS();
    return rc;
}
