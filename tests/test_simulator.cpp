#include "../include/market.h"
#include "test_util.h"
#include <iostream>
#include <cassert>
#include <cmath>


/**
 * Test 1: Simulator initializes correctly
 */
TEST(SimulatorTest, test_simulator_initializes) {
    LiquidityModel liq(0.01, 1000, 0.0001);
    MarketSimulator sim(100.0, liq);
    
    assert_true("initial price is 100", sim.get_current_price() == 100.0);
}

/**
 * Test 2: Price evolves over ticks
 */
TEST(SimulatorTest, test_price_evolves) {
    LiquidityModel liq(0.01, 1000, 0.0001);
    MarketSimulator sim(100.0, liq);
    
    double initial = sim.get_current_price();
    
    // Run backtest with 10 ticks and 1% volatility
    std::vector<Order> empty_orders;
    sim.run_backtest(empty_orders, 10, 0.01);
    
    double final = sim.get_current_price();
    
    // Price should have moved (with high probability)
    // Note: very small chance it stays exactly at 100.0, but extremely unlikely
    assert_true("price changed after ticks", initial != final);
}

/**
 * Test 3: Slippage calculation
 */
TEST(SimulatorTest, test_slippage_calculation) {
    LiquidityModel liq(0.01, 1000, 0.0001);
    MarketSimulator sim(100.0, liq);
    
    double arrival = 100.0;
    double execution = 100.10;  // Paid 10 cents more
    double slippage = sim.calculate_slippage(arrival, execution);
    
    // Slippage should be 0.10 / 100.0 = 0.001 = 0.1%
    assert_near("slippage is 0.001", slippage, 0.001);
}

/**
 * Test 4: Liquidity model spreads
 */
TEST(SimulatorTest, test_liquidity_model_spreads) {
    LiquidityModel liq(0.02, 1000, 0.0001);  // 2 cent spread
    
    double mid = 100.0;
    double ask_small = liq.get_ask_for_qty(mid, 100);
    double ask_large = liq.get_ask_for_qty(mid, 1000);
    
    // Larger order should have worse (higher) ask price
    assert_true("larger order has worse ask", ask_large > ask_small);
}

/**
 * Test 5: Market snapshots captured
 */
TEST(SimulatorTest, test_snapshots_captured) {
    LiquidityModel liq(0.01, 1000, 0.0001);
    MarketSimulator sim(100.0, liq);
    
    std::vector<Order> empty_orders;
    sim.run_backtest(empty_orders, 5, 0.01);
    
    auto snapshots = sim.get_snapshots();
    // Should have captured 5 snapshots (one per tick)
    assert_eq("5 snapshots captured", snapshots.size(), 5UL);
}

/**
 * Test 6: Quotes are derived from the current mid, not hardcoded prices.
 */
TEST(SimulatorTest, test_quotes_follow_current_mid) {
    LiquidityModel liq(0.02, 500, 0.0001);
    MarketSimulator sim(100.0, liq);

    std::vector<Order> empty_orders;
    sim.run_backtest(empty_orders, 8, 0.01);

    const auto& snapshots = sim.get_snapshots();
    bool saw_non_100_ask = false;

    for (const auto& snap : snapshots) {
        assert_near("snapshot bid matches model", snap.bid, liq.quoted_bid(snap.mid_price));
        assert_near("snapshot ask matches model", snap.ask, liq.quoted_ask(snap.mid_price));
        assert_true("bid is below mid", snap.bid < snap.mid_price);
        assert_true("ask is above mid", snap.ask > snap.mid_price);
        assert_eq("bid volume comes from model", snap.bid_volume, liq.quoted_quantity());
        assert_eq("ask volume comes from model", snap.ask_volume, liq.quoted_quantity());
        if (std::abs(snap.ask - 100.0) > 1e-9) {
            saw_non_100_ask = true;
        }
    }

    assert_true("ask is not stuck at hardcoded 100", saw_non_100_ask);
}

/**
 * Test 7: With no volatility, quotes stay locked to the initial mid and spread.
 */
TEST(SimulatorTest, test_zero_volatility_quotes_are_stable) {
    LiquidityModel liq(0.01, 1000, 0.0001);
    MarketSimulator sim(100.0, liq);

    std::vector<Order> empty_orders;
    sim.run_backtest(empty_orders, 5, 0.0);

    for (const auto& snap : sim.get_snapshots()) {
        assert_near("mid stays at 100", snap.mid_price, 100.0);
        assert_near("bid is mid minus half spread", snap.bid, 99.995);
        assert_near("ask is mid plus half spread", snap.ask, 100.005);
        assert_eq("quoted size is 1000", snap.bid_volume, 1000UL);
    }
}

/**
 * Test 8: The matching engine's top of book matches the current synthetic quotes.
 */
TEST(SimulatorTest, test_book_matches_current_quotes) {
    LiquidityModel liq(0.01, 750, 0.0001);
    MarketSimulator sim(100.0, liq);

    std::vector<Order> empty_orders;
    sim.run_backtest(empty_orders, 6, 0.01);

    const auto& last = sim.get_snapshots().back();
    const auto& book = sim.get_engine().get_book();

    auto best_bid = book.best_bid();
    auto best_ask = book.best_ask();

    assert_true("book has a bid", best_bid.has_value());
    assert_true("book has an ask", best_ask.has_value());
    assert_near("book bid equals current quoted bid", *best_bid, last.bid);
    assert_near("book ask equals current quoted ask", *best_ask, last.ask);
    assert_eq("book bid size equals model size", book.volume_at(*best_bid, OrderSide::Buy), 750UL);
    assert_eq("book ask size equals model size", book.volume_at(*best_ask, OrderSide::Sell), 750UL);
}

/**
 * Test 9: Strategy orders execute at the live ask, not a hardcoded $100.
 */
TEST(SimulatorTest, test_execution_uses_live_ask) {
    LiquidityModel liq(0.01, 1000, 0.0001);
    MarketSimulator sim(100.0, liq);

    // Marketable buy: crosses whatever the current ask is.
    std::vector<Order> orders = {
        Order(1, OrderSide::Buy, OrderType::Limit, 1e9, 100)
    };
    sim.run_backtest(orders, 1, 0.0);

    auto trades = sim.get_engine().get_all_trades();
    assert_eq("one trade", trades.size(), 1UL);
    assert_eq("filled 100", trades[0].qty, 100UL);
    assert_near("fill price is the live ask", trades[0].price, 100.005);
}

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    int rc = RUN_ALL_TESTS();
    return rc;
}
