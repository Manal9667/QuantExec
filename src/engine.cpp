#include "engine.h"
#include <algorithm>
#include <cmath>
#include <iostream>
#include <stdexcept>

/**
 * submit_order()
 * 
 * Main entry point: submit an order and get fills back.
 * Dispatches to market or limit matching based on order type.
 */
std::vector<Trade> MatchingEngine::submit_order(const Order& order) {
    if (order.type == OrderType::Market) {
        return match_market(Order(order));  // Copy to allow modification
    } else {
        return match_limit(Order(order));   // Copy to allow modification
    }
}

bool MatchingEngine::cancel_order(uint64_t order_id, OrderSide side, double price) {
    return book.cancel_order(order_id, side, price);
}

void MatchingEngine::validate_and_register(const Order& order, OrderType expected_type) {
    if (order.type != expected_type || order.qty == 0 || order.filled >= order.qty ||
        (order.side != OrderSide::Buy && order.side != OrderSide::Sell) ||
        !std::isfinite(order.price) ||
        (expected_type == OrderType::Limit && order.price <= 0.0) ||
        (expected_type == OrderType::Market && order.price < 0.0)) {
        throw std::invalid_argument("invalid order type, side, price, or quantity");
    }
    if (!submitted_order_ids_.insert(order.id).second) {
        throw std::invalid_argument("duplicate order id in current book session");
    }
}

/**
 * match_market()
 * 
 * Market order: fills immediately at best available prices.
 * 
 * Algorithm:
 * 1. Determine opposite side (if buying, look at sells)
 * 2. Walk from best to worst price on opposite side
 * 3. At each price level, match against all resting orders (FIFO)
 * 4. Continue until incoming order is fully filled or no liquidity left
 * 5. Return all fills
 * 
 * Time: O(n log P) where n = orders matched, P = price levels
 */
std::vector<Trade> MatchingEngine::match_market(Order order) {
    validate_and_register(order, OrderType::Market);
    std::vector<Trade> fills;
    
    // Determine which side we're buying/selling against
    OrderSide opposite_side = (order.side == OrderSide::Buy) ? OrderSide::Sell : OrderSide::Buy;
    
    // Walk the opposite side from best to worst price, greedily fill
    while (order.remaining() > 0) {
        // Get best price on opposite side
        std::optional<double> best_opposite;
        if (opposite_side == OrderSide::Sell) {
            best_opposite = book.best_ask();
        } else {
            best_opposite = book.best_bid();
        }
        
        // No more liquidity = order partially fills
        if (!best_opposite) {
            break;  // Reject the unfilled part (in real markets you'd queue it)
        }
        
        double price = *best_opposite;
        const auto* queue = book.get_queue(price, opposite_side);
        
        // Safety check (shouldn't happen)
        if (queue == nullptr || queue->empty()) {
            break;
        }
        
        // Fill against all resting orders at this price level
        while (order.remaining() > 0) {
            queue = book.get_queue(price, opposite_side);
            if (queue == nullptr || queue->empty()) break;
            const Order resting = queue->front();
            
            // How much can we fill?
            uint64_t fill_qty = std::min(order.remaining(), resting.remaining());
            
            // Update filled amounts
            order.filled += fill_qty;
            if (!book.fill_front(price, opposite_side, fill_qty)) {
                throw std::logic_error("failed to apply fill to resting order");
            }
            
            // Record the trade
            // Note: buy_order_id is always the buyer, sell_order_id is always the seller
            Trade trade(
                (order.side == OrderSide::Buy) ? order.id : resting.id,
                (order.side == OrderSide::Buy) ? resting.id : order.id,
                price,
                fill_qty
            );
            fills.push_back(trade);
            trades.push_back(trade);
            
        }
    }
    
    return fills;
}

/**
 * match_limit()
 * 
 * Limit order: fills up to price limit, posts remainder as resting order.
 * 
 * Algorithm:
 * 1. Determine opposite side
 * 2. Walk from best to worst price on opposite side
 * 3. STOP if price crosses our limit price
 * 4. Match against resting orders at each level
 * 5. Post remainder as resting order
 * 6. Return all fills
 * 
 * Time: O(n log P)
 */
std::vector<Trade> MatchingEngine::match_limit(Order order) {
    validate_and_register(order, OrderType::Limit);
    std::vector<Trade> fills;
    
    OrderSide opposite_side = (order.side == OrderSide::Buy) ? OrderSide::Sell : OrderSide::Buy;
    
    // Walk opposite side, but STOP if price crosses our limit
    while (order.remaining() > 0) {
        std::optional<double> best_opposite;
        if (opposite_side == OrderSide::Sell) {
            best_opposite = book.best_ask();
        } else {
            best_opposite = book.best_bid();
        }
        
        if (!best_opposite) {
            break;  // No liquidity
        }
        
        double price = *best_opposite;
        
        // Check if price crosses our limit
        if (order.side == OrderSide::Buy) {
            // We're buying: ask price must be <= our limit price
            if (price > order.price) {
                break;  // Price too high, stop crossing
            }
        } else {
            // We're selling: bid price must be >= our limit price
            if (price < order.price) {
                break;  // Price too low, stop crossing
            }
        }
        
        const auto* queue = book.get_queue(price, opposite_side);
        if (queue == nullptr || queue->empty()) {
            break;
        }
        
        // Match against orders at this level
        while (order.remaining() > 0) {
            queue = book.get_queue(price, opposite_side);
            if (queue == nullptr || queue->empty()) break;
            const Order resting = queue->front();
            
            uint64_t fill_qty = std::min(order.remaining(), resting.remaining());
            
            order.filled += fill_qty;
            if (!book.fill_front(price, opposite_side, fill_qty)) {
                throw std::logic_error("failed to apply fill to resting order");
            }
            
            Trade trade(
                (order.side == OrderSide::Buy) ? order.id : resting.id,
                (order.side == OrderSide::Buy) ? resting.id : order.id,
                price,
                fill_qty
            );
            fills.push_back(trade);
            trades.push_back(trade);
            
        }
    }
    
    // Post remainder as a resting order on our side
    if (order.remaining() > 0) {
        Order resting(order);
        resting.qty = order.remaining();  // Adjust qty to just the unfilled part
        resting.filled = 0;
        book.add_order(resting);
    }
    
    return fills;
}