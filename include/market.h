#ifndef EXECUTOR_MARKET_H
#define EXECUTOR_MARKET_H

#include "types.h"
#include "engine.h"
#include "market_data.h"
#include <vector>
#include <random>
#include <optional>

/**
 * MarketSnapshot
 * 
 * Captures the state of the market at a point in time.
 * Used by the simulator to track price evolution.
 */
/**
 * LiquidityModel
 * 
 * Models the shape of the order book (spreads and volumes).
 * Used to calculate realistic execution prices.
 * 
 * Simple model:
 * - Base spread: the bid-ask spread at mid price
 * - Liquidity at level: how much volume at each level
 * - Spread widening: spreads get wider as you move away from mid
 * 
 * Example usage:
 *   LiquidityModel liq(0.01, 1000, 0.0001);
 *   double ask_price = liq.get_ask_for_qty(100.0, 500);  // What price for 500 shares?
 */
class LiquidityModel {
public:
    double base_spread;           // Base bid-ask spread (e.g., 0.01 = 1 cent)
    double liquidity_at_level;    // Shares available at each price level
    double spread_widening;       // How much spread widens with size
    
    /**
     * Constructor
     * 
     * Example:
     *   LiquidityModel(0.01, 1000, 0.0001)
     *   - 1 cent spread at mid
     *   - 1000 shares at each level
     *   - spreads widen as you take more
     */
    LiquidityModel(double spread = 0.01, double qty = 1000, double widening = 0.0001)
        : base_spread(spread), liquidity_at_level(qty), spread_widening(widening) {}
    
    /**
     * Inside bid for the current mid. Derived from the market model, not a fixed price.
     */
    double quoted_bid(double mid) const {
        return mid - base_spread / 2.0;
    }

    /**
     * Inside ask for the current mid. Derived from the market model, not a fixed price.
     */
    double quoted_ask(double mid) const {
        return mid + base_spread / 2.0;
    }

    /**
     * Displayed size at the inside quote. Comes from the liquidity model.
     */
    uint64_t quoted_quantity() const {
        return static_cast<uint64_t>(liquidity_at_level);
    }

    /**
     * Calculate ask price for buying qty shares
     * 
     * Formula: ask = mid + base_spread/2 + (qty / liquidity) * spread_widening
     * 
     * Result: larger orders pay worse prices (market impact)
     */
    double get_ask_for_qty(double mid, uint64_t qty) const {
        double base_ask = quoted_ask(mid);
        double impact = (double)qty / liquidity_at_level * spread_widening;
        return base_ask + impact;
    }
    
    /**
     * Calculate bid price for selling qty shares
     * 
     * Formula: bid = mid - base_spread/2 - (qty / liquidity) * spread_widening
     * 
     * Result: larger orders get worse prices (market impact)
     */
    double get_bid_for_qty(double mid, uint64_t qty) const {
        double base_bid = quoted_bid(mid);
        double impact = (double)qty / liquidity_at_level * spread_widening;
        return base_bid - impact;
    }
};

/**
 * MarketSimulator
 * 
 * Simulates a market with realistic prices and liquidity.
 * Evolves prices over time using random walk (can upgrade to GBM).
 * Orchestrates backtests by executing orders against the market.
 * 
 * Example usage:
 *   LiquidityModel liq(0.01, 1000, 0.0001);
 *   MarketSimulator sim(100.0, liq);  // Start at $100
 *   
 *   std::vector<Order> orders = ...;
 *   sim.run_backtest(orders, 10, 0.01);  // 10 ticks, 1% volatility
 *   
 *   auto trades = sim.get_engine().get_all_trades();
 *   double slippage = sim.calculate_slippage(100.0, avg_exec_price);
 */
class MarketSimulator {
private:
    MatchingEngine engine;
    LiquidityModel liquidity;
    double current_price;
    std::mt19937 rng;                      // Random number generator
    std::vector<MarketSnapshot> snapshots;

    // Resting synthetic quotes currently on the book (0 = none)
    uint64_t synthetic_bid_id = 0;
    uint64_t synthetic_ask_id = 0;
    double synthetic_bid_price = 0.0;
    double synthetic_ask_price = 0.0;
    uint64_t next_synthetic_id = 1000000000;
    uint64_t total_synthetic_volume_ = 0;  // running total for snapshot.volume

    /**
     * Cancel previous synthetic quotes (if still resting) and post new
     * bid/ask derived from the current mid and liquidity model.
     */
    void refresh_synthetic_quotes();
    
    /**
     * Evolve price using random walk
     * 
     * Simple model: price_new = price_old * (1 + drift + N(0, volatility))
     * Where N(0, v) is a normal random variable
     * 
     * Can be upgraded to geometric Brownian motion later
     */
    void evolve_price(double volatility, double drift);
    
public:
    /**
     * Constructor
     */
    MarketSimulator(double initial_price, const LiquidityModel& liq,
                    uint32_t seed = std::random_device{}());
    
    /**
     * Run a backtest: execute orders over time
     * 
     * Simulates:
     * - Price evolution each tick
     * - Order submission each tick
     * - Trade execution via matching engine
     * 
     * Captures snapshots of market state over time
     */
    void run_backtest(const std::vector<Order>& orders, int num_ticks, double volatility);
    
    /**
     * Get the matching engine (read-only)
     */
    const MatchingEngine& get_engine() const { return engine; }
    
    /**
     * Get current price
     */
    double get_current_price() const { return current_price; }
    
    /**
     * Get all market snapshots captured during backtest
     */
    const std::vector<MarketSnapshot>& get_snapshots() const { return snapshots; }

    VectorMarketSource snapshot_source() const;
    
    /**
     * Calculate slippage: (actual_price - arrival_price) / arrival_price
     * 
     * Slippage is a key metric: how much worse did you execute vs the initial price?
     * 0.001 = 0.1% slippage
     * 0.005 = 0.5% slippage (bad)
     * -0.001 = -0.1% (good, you beat the initial price!)
     */
    double calculate_slippage(double arrival_price, double avg_exec_price) const;
    
    /**
     * Calculate market impact: (final_price - initial_price) / initial_price
     * 
     * How much did the market move because of your trade?
     * Positive = market moved against you (price went up while you were buying)
     */
    double calculate_market_impact(double initial_mid, const std::vector<Trade>& trades) const;
};

#endif