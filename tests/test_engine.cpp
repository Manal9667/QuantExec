#include "../include/engine.h"
#include "test_util.h"
#include <cassert>
#include <iostream>


/**
 * Test 1: Market order fills immediately
 */
TEST(EngineTest, test_market_order_fills) {
    MatchingEngine engine;
    
    // Add resting sell order
    Order sell1(1, OrderSide::Sell, OrderType::Limit, 100.0, 100);
    engine.submit_order(sell1);
    
    // Market buy should fill immediately
    Order buy1(2, OrderSide::Buy, OrderType::Market, 0, 100);
    auto fills = engine.submit_order(buy1);
    
    assert_eq("market buy fills", fills.size(), 1UL);
    assert_eq("fill qty is correct", fills[0].qty, 100UL);
    assert_eq("fill price is ask", fills[0].price, 100.0);
}

/**
 * Test 2: Limit order can rest
 */
TEST(EngineTest, test_limit_order_rests) {
    MatchingEngine engine;
    
    // Add buy limit that doesn't cross
    Order buy1(1, OrderSide::Buy, OrderType::Limit, 99.0, 100);
    auto fills = engine.submit_order(buy1);
    
    assert_eq("no fills (price too low)", fills.size(), 0UL);
    assert_eq("order rests on book", engine.get_book().volume_at(99.0, OrderSide::Buy), 100UL);
}

/**
 * Test 3: Partial fill across price levels
 */
TEST(EngineTest, test_partial_fill_across_levels) {
    MatchingEngine engine;
    
    // Add two sell levels
    Order sell1(1, OrderSide::Sell, OrderType::Limit, 100.0, 50);
    Order sell2(2, OrderSide::Sell, OrderType::Limit, 100.5, 75);
    engine.submit_order(sell1);
    engine.submit_order(sell2);
    
    // Market buy 100 shares: 50 @ 100.0, 50 @ 100.5
    Order buy1(3, OrderSide::Buy, OrderType::Market, 0, 100);
    auto fills = engine.submit_order(buy1);
    
    assert_eq("two fills at two prices", fills.size(), 2UL);
    assert_eq("first fill at 100.0", fills[0].price, 100.0);
    assert_eq("first fill qty 50", fills[0].qty, 50UL);
    assert_eq("second fill at 100.5", fills[1].price, 100.5);
    assert_eq("second fill qty 50", fills[1].qty, 50UL);
}

/**
 * Test 4: FIFO at same price level
 */
TEST(EngineTest, test_fifo_at_price_level) {
    MatchingEngine engine;
    
    // Add two orders at same price, first one arrived first
    Order sell1(1, OrderSide::Sell, OrderType::Limit, 100.0, 50);
    Order sell2(2, OrderSide::Sell, OrderType::Limit, 100.0, 50);
    engine.submit_order(sell1);
    engine.submit_order(sell2);
    
    // Market buy 75 shares: should get sell1 first (50), then part of sell2 (25)
    Order buy1(3, OrderSide::Buy, OrderType::Market, 0, 75);
    auto fills = engine.submit_order(buy1);
    
    assert_eq("two fills", fills.size(), 2UL);
    assert_eq("first fill from order 1", fills[0].sell_order_id, 1UL);
    assert_eq("first fill qty 50", fills[0].qty, 50UL);
    assert_eq("second fill from order 2", fills[1].sell_order_id, 2UL);
    assert_eq("second fill qty 25", fills[1].qty, 25UL);
}

/**
 * Test 5: Limit order partially fills and rests
 */
TEST(EngineTest, test_limit_partial_fill_and_rest) {
    MatchingEngine engine;
    
    // Add sell order
    Order sell1(1, OrderSide::Sell, OrderType::Limit, 100.0, 50);
    engine.submit_order(sell1);
    
    // Limit buy 100 @ 100.5: fills 50 against sell1, rests 50 @ 100.5
    Order buy1(2, OrderSide::Buy, OrderType::Limit, 100.5, 100);
    auto fills = engine.submit_order(buy1);
    
    assert_eq("one fill", fills.size(), 1UL);
    assert_eq("fill qty 50", fills[0].qty, 50UL);
    assert_eq("buy order rested 50", engine.get_book().volume_at(100.5, OrderSide::Buy), 50UL);
}

/**
 * Test 6: Market order with insufficient liquidity
 */
TEST(EngineTest, test_market_insufficient_liquidity) {
    MatchingEngine engine;
    
    // Only 50 shares available
    Order sell1(1, OrderSide::Sell, OrderType::Limit, 100.0, 50);
    engine.submit_order(sell1);
    
    // Try to buy 100
    Order buy1(2, OrderSide::Buy, OrderType::Market, 0, 100);
    auto fills = engine.submit_order(buy1);
    
    assert_eq("partial fill", fills.size(), 1UL);
    assert_eq("filled 50, not 100", fills[0].qty, 50UL);
}

/**
 * Test 7: Trades are recorded
 */
TEST(EngineTest, test_trades_recorded) {
    MatchingEngine engine;
    
    Order sell1(1, OrderSide::Sell, OrderType::Limit, 100.0, 100);
    engine.submit_order(sell1);
    
    Order buy1(2, OrderSide::Buy, OrderType::Market, 0, 100);
    engine.submit_order(buy1);
    
    auto all_trades = engine.get_all_trades();
    assert_eq("one trade recorded", all_trades.size(), 1UL);
    assert_eq("trade count is 1", engine.get_trade_count(), 1UL);
}

/**
 * Test 8: Limit buy doesn't cross limit price
 */
TEST(EngineTest, test_limit_buy_respects_limit) {
    MatchingEngine engine;
    
    // Seller asking 100.5
    Order sell1(1, OrderSide::Sell, OrderType::Limit, 100.5, 100);
    engine.submit_order(sell1);
    
    // Buyer willing to pay only 100.0
    Order buy1(2, OrderSide::Buy, OrderType::Limit, 100.0, 100);
    auto fills = engine.submit_order(buy1);
    
    assert_eq("no fills (price too high)", fills.size(), 0UL);
    assert_eq("buy order rested", engine.get_book().volume_at(100.0, OrderSide::Buy), 100UL);
}

/**
 * Test 9: Limit sell doesn't cross limit price
 */
TEST(EngineTest, test_limit_sell_respects_limit) {
    MatchingEngine engine;
    
    // Buyer bidding 99.5
    Order buy1(1, OrderSide::Buy, OrderType::Limit, 99.5, 100);
    engine.submit_order(buy1);
    
    // Seller willing to sell only at 100.0
    Order sell1(2, OrderSide::Sell, OrderType::Limit, 100.0, 100);
    auto fills = engine.submit_order(sell1);
    
    assert_eq("no fills (price too low)", fills.size(), 0UL);
    assert_eq("sell order rested", engine.get_book().volume_at(100.0, OrderSide::Sell), 100UL);
}

/**
 * Test 10: Fill both sides correctly
 */
TEST(EngineTest, test_fill_both_sides_correctly) {
    MatchingEngine engine;
    
    Order sell1(1, OrderSide::Sell, OrderType::Limit, 100.0, 100);
    engine.submit_order(sell1);
    
    Order buy1(2, OrderSide::Buy, OrderType::Market, 0, 100);
    auto fills = engine.submit_order(buy1);
    
    assert_eq("one fill", fills.size(), 1UL);
    assert_eq("buy_order_id is buy", fills[0].buy_order_id, 2UL);
    assert_eq("sell_order_id is sell", fills[0].sell_order_id, 1UL);
    assert_eq("price is correct", fills[0].price, 100.0);
    assert_eq("qty is correct", fills[0].qty, 100UL);
}

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    int rc = RUN_ALL_TESTS();
    return rc;
}
