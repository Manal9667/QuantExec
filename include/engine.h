#ifndef EXECUTOR_ENGINE_H
#define EXECUTOR_ENGINE_H

#include "types.h"
#include "book.h"
#include <unordered_set>
#include <vector>
#include <memory>

/**
 * MatchingEngine class
 * 
 * Processes incoming orders and matches them against the order book.
 * 
 * Main entry point: submit_order(order)
 * Returns a vector of Trade objects created by the match.
 * 
 * Handles:
 * - Market orders (fill greedily at best available prices)
 * - Limit orders (fill up to price limit, post remainder)
 * - Partial fills (one order can match multiple price levels)
 * - FIFO semantics (first order in, first order out at each level)
 * 
 * Example usage:
 *   MatchingEngine engine;
 *   Order sell_order(1, OrderSide::Sell, OrderType::Limit, 100.0, 100);
 *   engine.submit_order(sell_order);
 *   
 *   Order buy_order(2, OrderSide::Buy, OrderType::Market, 0, 100);
 *   auto trades = engine.submit_order(buy_order);
 *   // trades[0] contains the matched trade
 */
class MatchingEngine {
private:
    OrderBook book;                    // The order book
    std::vector<Trade> trades;         // All trades executed so far
    std::unordered_set<uint64_t> submitted_order_ids_;
    
    /**
     * Helper: Try to fill one resting order against incoming order
     * Returns quantity that was filled
     */
    uint64_t fill_against_resting(Order& incoming, Order& resting, double price);
    void validate_and_register(const Order& order, OrderType expected_type);
    
public:
    /**
     * Constructor (default)
     */
    MatchingEngine() = default;
    
    /**
     * Main entry point: Submit an order to the matching engine
     * 
     * Dispatches to match_market() or match_limit() based on order type.
     * Returns vector of Trade objects created by this order.
     * 
     * Time: O(n log P) where n = orders to match, P = price levels
     */
    std::vector<Trade> submit_order(const Order& order);

    /**
     * Cancel a resting order. Returns true if it was found and removed.
     */
    bool cancel_order(uint64_t order_id, OrderSide side, double price);

    void clear_book() {
        book.clear();
        submitted_order_ids_.clear();
    }
    
    /**
     * Match a market order
     * 
     * A market order fills immediately at the best available prices.
     * Walks from best to worst price level, filling greedily.
     * If not enough liquidity, partially fills and rejects remainder.
     * 
     * Time: O(n log P)
     */
    std::vector<Trade> match_market(Order order);
    
    /**
     * Match a limit order
     * 
     * A limit order fills up to its limit price.
     * Walks from best to worst price level, but STOPS if price crosses limit.
     * Posts any remainder as a resting order on the book.
     * 
     * Time: O(n log P)
     */
    std::vector<Trade> match_limit(Order order);
    
    /**
     * Get the order book (read-only access)
     */
    const OrderBook& get_book() const { return book; }
    
    /**
     * Get all trades executed so far
     */
    const std::vector<Trade>& get_all_trades() const { return trades; }
    
    /**
     * Get count of trades executed
     */
    uint64_t get_trade_count() const { return trades.size(); }
};

#endif