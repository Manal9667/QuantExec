#ifndef EXECUTOR_BOOK_H
#define EXECUTOR_BOOK_H

#include "types.h"
#include <map>
#include <deque>
#include <optional>
#include <unordered_set>
#include <vector>

/**
 * OrderBook class
 * 
 * Maintains bid (buy) and ask (sell) sides of an order book.
 * 
 * Design:
 *   Bids: std::map with prices as keys, sorted descending (highest price first)
 *   Asks: std::map with prices as keys, sorted ascending (lowest price first)
 *   
 *   At each price level, orders are queued in a deque to maintain FIFO (first in, first out).
 *   When an incoming order fills, it fills against the oldest order first.
 * 
 * Time Complexity:
 *   add_order():        O(log P) where P = number of price levels
 *   best_bid/ask():     O(1) amortized
 *   mid_price():        O(1) amortized
 *   volume_at():        O(n) where n = orders at that level
 *   cancel_order():     O(n) to find + O(1) to remove
 * 
 * Example usage:
 *   OrderBook book;
 *   Order sell1(1, OrderSide::Sell, OrderType::Limit, 100.0, 100);
 *   book.add_order(sell1);
 *   
 *   auto best_ask = book.best_ask();  // Returns optional<double> = 100.0
 *   auto mid = book.mid_price();      // Returns optional<double>
 */
class OrderBook {
private:
    
    std::map<double, std::deque<Order>, std::greater<double>> bids;

    std::map<double, std::deque<Order>> asks;
    std::unordered_set<uint64_t> order_ids;
    
public:
    /**
     * Constructor (default)
     */
    OrderBook() = default;
    
    /**
     * Add an order to the book
     * 
     * If this is a resting order (limit order not immediately filled),
     * it goes here. The order is placed at the appropriate price level,
     * queued with other orders at that level.
     * 
     * Time: O(log P)
     */
    void add_order(const Order& order);
    
    /**
     * Cancel an order from the book
     * 
     * Returns true if order was found and canceled, false otherwise.
     * 
     * Time: O(n) to find, O(1) to remove
     */
    bool cancel_order(uint64_t order_id, OrderSide side, double price);
    
    /**
     * Get the best (highest) bid price
     * 
     * Returns std::optional - either the price or std::nullopt if no bids
     * 
     * Time: O(1) amortized
     */
    std::optional<double> best_bid() const;
    
    /**
     * Get the best (lowest) ask price
     * 
     * Returns std::optional - either the price or std::nullopt if no asks
     * 
     * Time: O(1) amortized
     */
    std::optional<double> best_ask() const;
    
    /**
     * Get the mid price (average of best bid and ask)
     * 
     * Returns std::optional - either the price or std::nullopt if no two-sided market
     * 
     * Time: O(1) amortized
     */
    std::optional<double> mid_price() const;
    
    
    uint64_t volume_at(double price, OrderSide side) const;

    /**
     * Visible bid levels, best first. Does not include empty levels.
     */
    std::vector<BookLevel> bid_depth(size_t max_levels = 10) const;

    /**
     * Visible ask levels, best first. Does not include empty levels.
     */
    std::vector<BookLevel> ask_depth(size_t max_levels = 10) const;
    
    const std::deque<Order>* get_queue(double price, OrderSide side) const;

    bool fill_front(double price, OrderSide side, uint64_t quantity);
    
    void remove_level(double price, OrderSide side);

    void clear();
    
    void print_state() const;
};

#endif