#include "book.h"
#include <iostream>
#include <algorithm>
#include <cmath>
#include <iomanip>
#include <stdexcept>

void OrderBook::add_order(const Order& order) {
    if (order.type != OrderType::Limit || order.qty == 0 || order.filled >= order.qty ||
        !std::isfinite(order.price) || order.price <= 0.0 ||
        (order.side != OrderSide::Buy && order.side != OrderSide::Sell)) {
        throw std::invalid_argument("OrderBook accepts only valid, non-empty limit orders");
    }
    if (order_ids.find(order.id) != order_ids.end()) {
        throw std::invalid_argument("duplicate resting order id");
    }
    order_ids.insert(order.id);

    if (order.side == OrderSide::Buy) {
        // Add to bid side
        // If price level doesn't exist, map creates it automatically
        bids[order.price].push_back(order);
    } else {
        // Add to ask side
        asks[order.price].push_back(order);
    }
}
    /**
     * best_bid()
     * 
     * Returns the highest bid price (best bid).
     * Returns std::nullopt if no bids exist.
     * 
     * How it works:
     *   - bids map is sorted descending (due to std::greater<double>)
     *   - begin() points to the highest price
     *   - Return that price, or nullopt if empty
     * 
     * Time: O(1) amortized
     */

std::optional<double> OrderBook::best_bid() const {
    if (bids.empty()) {
        return std::nullopt;
    }
    // begin() is the highest price due to descending sort
    return bids.begin()->first;
}

std::optional<double> OrderBook::best_ask() const {
    if (asks.empty()) {
        return std::nullopt;
    }
    // begin() is the lowest price due to ascending sort
    return asks.begin()->first;
}

std::optional<double> OrderBook::mid_price() const {
    auto bid = best_bid();
    auto ask = best_ask();
    
    if (bid && ask) {
        // Both exist, return average
        return (*bid + *ask) / 2.0;
    }
    // One or both don't exist
    return std::nullopt;
}

std::vector<BookLevel> OrderBook::bid_depth(size_t max_levels) const {
    std::vector<BookLevel> levels;
    for (const auto& [price, queue] : bids) {
        if (levels.size() >= max_levels) {
            break;
        }
        uint64_t qty = 0;
        for (const auto& order : queue) {
            qty += order.remaining();
        }
        if (qty > 0) {
            levels.push_back({price, qty});
        }
    }
    return levels;
}

std::vector<BookLevel> OrderBook::ask_depth(size_t max_levels) const {
    std::vector<BookLevel> levels;
    for (const auto& [price, queue] : asks) {
        if (levels.size() >= max_levels) {
            break;
        }
        uint64_t qty = 0;
        for (const auto& order : queue) {
            qty += order.remaining();
        }
        if (qty > 0) {
            levels.push_back({price, qty});
        }
    }
    return levels;
}

uint64_t OrderBook::volume_at(double price, OrderSide side) const {
    uint64_t total = 0;
    if (side == OrderSide::Buy) {
        auto it = bids.find(price);
        if (it == bids.end()) {
            return 0;
        }
        for (const auto& order : it->second) {
            total += order.remaining();
        }
    } else {
        auto it = asks.find(price);
        if (it == asks.end()) {
            return 0;
        }
        for (const auto& order : it->second) {
            total += order.remaining();
        }
    }
    return total;
}

const std::deque<Order>* OrderBook::get_queue(double price, OrderSide side) const {
    if (side == OrderSide::Buy) {
        auto it = bids.find(price);
        if (it == bids.end()) {
            return nullptr;
        }
        return &(it->second);
    } else {
        auto it = asks.find(price);
        if (it == asks.end()) {
            return nullptr;
        }
        return &(it->second);
    }
}

bool OrderBook::fill_front(double price, OrderSide side, uint64_t quantity) {
    std::deque<Order>* queue = nullptr;
    if (side == OrderSide::Buy) {
        auto it = bids.find(price);
        if (it != bids.end()) queue = &it->second;
    } else {
        auto it = asks.find(price);
        if (it != asks.end()) queue = &it->second;
    }
    if (queue == nullptr || queue->empty() || quantity == 0 ||
        quantity > queue->front().remaining()) {
        return false;
    }

    Order& order = queue->front();
    order.filled += quantity;
    if (order.is_filled()) {
        order_ids.erase(order.id);
        queue->pop_front();
        if (queue->empty()) remove_level(price, side);
    }
    return true;
}

bool OrderBook::cancel_order(uint64_t order_id, OrderSide side, double price) {
    if (side == OrderSide::Buy) {
        auto it = bids.find(price);
        if (it == bids.end()) {
            return false;
        }
        
        auto& queue = it->second;
        auto order_it = std::find_if(
            queue.begin(), 
            queue.end(),
            [order_id](const Order& o) { return o.id == order_id; }
        );
        
        if (order_it == queue.end()) {
            return false;
        }
        
        queue.erase(order_it);
        order_ids.erase(order_id);
        
        if (queue.empty()) {
            bids.erase(it);
        }
        
        return true;
    } else {
        auto it = asks.find(price);
        if (it == asks.end()) {
            return false;
        }
        
        auto& queue = it->second;
        auto order_it = std::find_if(
            queue.begin(), 
            queue.end(),
            [order_id](const Order& o) { return o.id == order_id; }
        );
        
        if (order_it == queue.end()) {
            return false;
        }
        
        queue.erase(order_it);
        order_ids.erase(order_id);
        
        if (queue.empty()) {
            asks.erase(it);
        }
        
        return true;
    }
}

void OrderBook::remove_level(double price, OrderSide side) {
    if (side == OrderSide::Buy) {
        auto it = bids.find(price);
        if (it != bids.end()) {
            for (const auto& order : it->second) order_ids.erase(order.id);
            bids.erase(it);
        }
    } else {
        auto it = asks.find(price);
        if (it != asks.end()) {
            for (const auto& order : it->second) order_ids.erase(order.id);
            asks.erase(it);
        }
    }
}

void OrderBook::print_state() const {
    std::cout << "=== Order Book ===" << std::endl;
    
    // Print bids
    std::cout << "BIDS:" << std::endl;
    if (bids.empty()) {
        std::cout << "  (empty)" << std::endl;
    } else {
        for (const auto& [price, queue] : bids) {
            // Count total quantity at this level
            uint64_t qty = 0;
            for (const auto& o : queue) {
                qty += o.remaining();
            }
            // Print: price, number of orders, total quantity
            std::cout << "  $" << std::fixed << std::setprecision(2) << price 
                      << ": " << queue.size() << " orders (" << qty << " qty)" << std::endl;
        }
    }
    
    // Print asks
    std::cout << "ASKS:" << std::endl;
    if (asks.empty()) {
        std::cout << "  (empty)" << std::endl;
    } else {
        for (const auto& [price, queue] : asks) {
            // Count total quantity at this level
            uint64_t qty = 0;
            for (const auto& o : queue) {
                qty += o.remaining();
            }
            // Print: price, number of orders, total quantity
            std::cout << "  $" << std::fixed << std::setprecision(2) << price 
                      << ": " << queue.size() << " orders (" << qty << " qty)" << std::endl;
        }
    }
    
    // Print mid price
    if (auto mid = mid_price()) {
        std::cout << "Mid: $" << std::fixed << std::setprecision(2) << *mid << std::endl;
    }
    std::cout << std::endl;
}

void OrderBook::clear() {
    bids.clear();
    asks.clear();
    order_ids.clear();
}