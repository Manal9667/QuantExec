#include "../include/types.h"
#include "test_util.h"
#include "../include/book.h"
#include "../include/engine.h"
#include "../include/market.h"
#include "../include/algorithms.h"
#include <iostream>
#include <algorithm>
#include <cassert>
#include <cmath>

/**
 * Integration Tests - End-to-End Workflows
 * 
 * These tests verify that all components work together correctly
 * in realistic scenarios.
 */


/**
 * Integration Test 1: Complete order-to-trade workflow
 * 
 * Scenario:
 * 1. Build an order book with bids and asks
 * 2. Submit a market buy order
 * 3. Verify trades are generated
 * 4. Verify order book is updated
 */
TEST(IntegrateTest, test_complete_workflow) {
    std::cout << "\nTest 1: Complete Order-to-Trade Workflow" << std::endl;
    std::cout << "─────────────────────────────────────────" << std::endl;
    
    MatchingEngine engine;
    
    // Build initial order book
    // Sellers: 100 shares at $100, $100.50, $101
    engine.submit_order(Order(1, OrderSide::Sell, OrderType::Limit, 100.0, 100));
    engine.submit_order(Order(2, OrderSide::Sell, OrderType::Limit, 100.5, 100));
    engine.submit_order(Order(3, OrderSide::Sell, OrderType::Limit, 101.0, 100));
    
    // Buyers: 100 shares at $99, $99.50
    engine.submit_order(Order(4, OrderSide::Buy, OrderType::Limit, 99.0, 100));
    engine.submit_order(Order(5, OrderSide::Buy, OrderType::Limit, 99.5, 100));
    
    // Market buy 150 shares (should fill from ask side)
    auto trades = engine.submit_order(Order(6, OrderSide::Buy, OrderType::Market, 0, 150));
    
    // Verify
    assert_eq("2 trades generated (crosses 2 price levels)", trades.size(), 2UL);
    assert_eq("trade 1 qty is 100", trades[0].qty, 100UL);
    assert_eq("trade 2 qty is 50", trades[1].qty, 50UL);
    assert_true("trade 1 price is best ask (100.0)", trades[0].price == 100.0);
    assert_true("trade 2 price is 100.5", trades[1].price == 100.5);
}

/**
 * Integration Test 2: TWAP Algorithm Integration
 * 
 * Scenario:
 * 1. Generate a TWAP order split (1000 shares → 10 x 100)
 * 2. Submit all slices to engine
 * 3. Verify all fill
 * 4. Verify fills are recorded in trade history
 */
TEST(IntegrateTest, test_twap_integration) {
    std::cout << "\nTest 2: TWAP Algorithm Integration" << std::endl;
    std::cout << "─────────────────────────────────────────" << std::endl;
    
    MatchingEngine engine;
    TWAPAlgorithm twap;
    
    // Seed the order book with lots of liquidity
    for (int i = 0; i < 20; ++i) {
        engine.submit_order(Order(1000 + i, OrderSide::Sell, OrderType::Limit, 100.0, 100));
    }
    
    // Generate TWAP orders
    auto twap_orders = twap.generate_orders(100, OrderSide::Buy, 1000, 100.0, 10);
    
    assert_eq("10 child orders", twap_orders.size(), 10UL);
    
    // Submit all TWAP orders
    uint64_t total_filled = 0;
    for (const auto& order : twap_orders) {
        auto fills = engine.submit_order(order);
        for (const auto& fill : fills) {
            total_filled += fill.qty;
        }
    }
    
    assert_eq("all 1000 shares filled", total_filled, 1000UL);
    assert_eq("total trades recorded", engine.get_trade_count(), 10UL);
}

/**
 * Integration Test 3: VWAP with Volume Profile
 * 
 * Scenario:
 * 1. Set up a volume-weighted profile: [40%, 30%, 20%, 10%]
 * 2. Generate VWAP orders
 * 3. Verify split is volume-weighted
 * 4. Execute and measure slippage
 */
TEST(IntegrateTest, test_vwap_integration) {
    std::cout << "\nTest 3: VWAP Algorithm Integration" << std::endl;
    std::cout << "─────────────────────────────────────────" << std::endl;
    
    VWAPAlgorithm vwap;
    std::vector<double> profile = {0.4, 0.3, 0.2, 0.1};
    vwap.set_volume_profile(profile);
    
    // Generate orders
    auto vwap_orders = vwap.generate_orders(200, OrderSide::Buy, 1000, 100.0, 4);
    
    assert_eq("4 child orders", vwap_orders.size(), 4UL);
    assert_eq("first order 400", vwap_orders[0].qty, 400UL);
    assert_eq("second order 300", vwap_orders[1].qty, 300UL);
    assert_eq("third order 200", vwap_orders[2].qty, 200UL);
    assert_eq("fourth order 100", vwap_orders[3].qty, 100UL);
    
    // Verify total
    uint64_t total_qty = 0;
    for (const auto& o : vwap_orders) {
        total_qty += o.qty;
    }
    assert_eq("total is 1000", total_qty, 1000UL);
}

/**
 * Integration Test 4: Market Simulator with Realistic Execution
 * 
 * Scenario:
 * 1. Create a market simulator at $100
 * 2. Build an order book
 * 3. Run backtest with orders over multiple ticks
 * 4. Verify price evolved and trades were recorded
 * 5. Calculate slippage
 */
TEST(IntegrateTest, test_market_simulator_integration) {
    std::cout << "\nTest 4: Market Simulator Integration" << std::endl;
    std::cout << "─────────────────────────────────────────" << std::endl;
    
    LiquidityModel liq(0.01, 1000, 0.0001);
    MarketSimulator sim(100.0, liq);
    
    // Create orders to submit during backtest
    std::vector<Order> orders;
    for (int i = 0; i < 5; ++i) {
        orders.push_back(Order(i, OrderSide::Buy, OrderType::Limit, 100.0, 100));
    }
    
    // Run backtest
    sim.run_backtest(orders, 10, 0.01);  // 10 ticks, 1% volatility
    
    // Verify
    assert_true("price evolved", sim.get_current_price() != 100.0);
    assert_eq("snapshots captured", sim.get_snapshots().size(), 10UL);
    
    // Check slippage calculation
    double slippage = sim.calculate_slippage(100.0, 100.05);
    assert_eq("slippage calculated", slippage, 0.0005, 0.001);
}

/**
 * Integration Test 5: Full Pipeline - Algorithm → Engine → Simulator → Analysis
 * 
 * Scenario:
 * 1. TWAP algorithm generates 10 orders from 1000 share parent
 * 2. Submit to market simulator (which has engine inside)
 * 3. Backtest runs over 10 ticks
 * 4. Calculate final slippage and cost
 * 5. Verify complete end-to-end flow
 */
TEST(IntegrateTest, test_full_pipeline) {
    std::cout << "\nTest 5: Full Pipeline (Algorithm → Simulator → Analysis)" << std::endl;
    std::cout << "─────────────────────────────────────────" << std::endl;
    
    // Setup
    LiquidityModel liq(0.01, 5000, 0.0001);
    MarketSimulator sim(100.0, liq);
    TWAPAlgorithm twap;
    
    // Marketable TWAP slices so they take the live ask (mid + half spread).
    auto orders = twap.generate_orders(1, OrderSide::Buy, 1000, 1e9, 10);
    assert_eq("10 TWAP slices", orders.size(), 10UL);
    
    // Run backtest (simulator will execute orders internally)
    sim.run_backtest(orders, 10, 0.01);
    
    // Get results from engine inside simulator
    auto all_trades = sim.get_engine().get_all_trades();
    for (const auto& trade : all_trades) {
        std::cout << "Trade price: $" << trade.price
                << " qty: " << trade.qty << std::endl;
    }
    
    // Calculate metrics
    uint64_t total_qty = 0;
    double total_cost = 0;
    for (const auto& trade : all_trades) {
        total_qty += trade.qty;
        total_cost += trade.price * trade.qty;
    }
    
    double avg_exec_price = (total_qty > 0) ? (total_cost / total_qty) : 100.0;
    double slippage = (avg_exec_price - 100.0) / 100.0;

    double min_ask = sim.get_snapshots().front().ask;
    double max_ask = min_ask;
    for (const auto& snap : sim.get_snapshots()) {
        min_ask = std::min(min_ask, snap.ask);
        max_ask = std::max(max_ask, snap.ask);
    }
    
    // Verify
    assert_true("trades were generated", all_trades.size() > 0);
    assert_true("some quantity was filled", total_qty > 0);
    assert_true(
        "average price is within observed asks",
        avg_exec_price >= min_ask - 1e-9 && avg_exec_price <= max_ask + 1e-9
    );
    
    std::cout << "    Final price: $" << avg_exec_price << std::endl;
    std::cout << "    Slippage: " << (slippage * 100) << "%" << std::endl;
}

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    int rc = RUN_ALL_TESTS();
    return rc;
}
