#include "algorithms.h"
#include <algorithm>
#include <numeric>
#include <stdexcept>

/**
 * TWAPAlgorithm::generate_orders()
 * 
 * Split order evenly: qty1 = qty2 = ... = qty_n = total_qty / num_slices
 * 
 * Remainder is added to first slice to ensure total = total_qty
 * 
 * Time complexity: O(num_slices)
 */
std::vector<Order> TWAPAlgorithm::generate_orders(
    uint64_t parent_order_id,
    OrderSide side,
    uint64_t total_qty,
    double limit_price,
    int num_slices
) {
    std::vector<Order> orders;

    if (num_slices <= 0 || total_qty == 0) {
        return orders;
    }
    
    // Calculate slice size
    uint64_t slice_qty = total_qty / num_slices;
    uint64_t remainder = total_qty % num_slices;
    
    for (int i = 0; i < num_slices; ++i) {
        // Add remainder to first slice
        uint64_t qty = slice_qty + (i == 0 ? remainder : 0);
        
        // Create child order
        // ID format: parent_id * 1000 + slice_index
        uint64_t child_id = parent_order_id * 1000 + i;
        
        Order child(child_id, side, OrderType::Limit, limit_price, qty);
        orders.push_back(child);
    }
    
    return orders;
}

/**
 * VWAPAlgorithm::generate_orders()
 * 
 * Split order based on volume profile.
 * Each slice gets: qty_i = total_qty * profile[i]
 * 
 * If profile[i] = 0.3, then slice i gets 30% of total
 * If no profile set, use uniform (same as TWAP)
 * 
 * Time complexity: O(num_slices)
 */
std::vector<Order> VWAPAlgorithm::generate_orders(
    uint64_t parent_order_id,
    OrderSide side,
    uint64_t total_qty,
    double limit_price,
    int num_slices
) {
    std::vector<Order> orders;

    if (num_slices <= 0 || total_qty == 0) {
        return orders;
    }

    // If no profile, use uniform (default to TWAP behavior)
    if (volume_profile.empty()) {
        uint64_t slice_qty = total_qty / num_slices;
        uint64_t remainder = total_qty % num_slices;

        for (int i = 0; i < num_slices; ++i) {
            uint64_t qty = slice_qty + (i == 0 ? remainder : 0);

            uint64_t child_id = parent_order_id * 1000 + i;
            Order child(
                child_id,
                side,
                OrderType::Limit,
                limit_price,
                qty
            );

            orders.push_back(child);
        }

        return orders;
    }

    // Only use as many profile buckets as there are requested slices.
    size_t num_profile_slices = std::min(
        volume_profile.size(),
        static_cast<size_t>(num_slices)
    );

    // Normalize only the profile buckets we are actually using.
    double total_profile_volume = 0.0;

    for (size_t i = 0; i < num_profile_slices; ++i) {
        if (volume_profile[i] > 0.0) {
            total_profile_volume += volume_profile[i];
        }
    }

    if (total_profile_volume <= 0.0) {
        TWAPAlgorithm twap;
        return twap.generate_orders(
            parent_order_id, side, total_qty, limit_price, num_slices);
    }

    uint64_t total_assigned = 0;

    for (size_t i = 0; i < num_profile_slices; ++i) {

        // Convert the profile value into a normalized fraction.
        double fraction = volume_profile[i] > 0.0
            ? volume_profile[i] / total_profile_volume
            : 0.0;

        uint64_t qty = static_cast<uint64_t>(
            total_qty * fraction
        );

        // Give the final slice any remaining quantity caused by
        // integer rounding.
        if (i == num_profile_slices - 1) {
            qty = total_qty - total_assigned;
        }

        total_assigned += qty;

        uint64_t child_id = parent_order_id * 1000 + i;

        Order child(
            child_id,
            side,
            OrderType::Limit,
            limit_price,
            qty
        );

        orders.push_back(child);
    }

    return orders;
}


/**
 * AdaptiveAlgorithm::generate_orders()
 *
 * See the class comment in algorithms.h: like POV, Adaptive sizes each
 * child order from data observed during replay (here the current price),
 * so there is no honest precomputed schedule. Use
 * ExecutionSession::run_adaptive() for real adaptive execution.
 */
std::vector<Order> AdaptiveAlgorithm::generate_orders(
    uint64_t /*parent_order_id*/,
    OrderSide /*side*/,
    uint64_t /*total_qty*/,
    double /*limit_price*/,
    int /*num_slices*/
) {
    throw std::logic_error(
        "AdaptiveAlgorithm::generate_orders() is not supported: Adaptive "
        "sizes each child order from the price observed during replay, "
        "which is not known ahead of time. Use "
        "ExecutionSession::run_adaptive(source, side, total_qty, "
        "limit_price, adaptive, arrival_price) instead."
    );
}

/**
 * AdaptiveAlgorithm::next_order_qty()
 *
 * Time complexity: O(1). Pure function: does not touch the book, the
 * engine, or any strategy-internal fill bookkeeping (spec section 12).
 */
uint64_t AdaptiveAlgorithm::next_order_qty(double mid_price,
                                           double arrival_price,
                                           OrderSide side,
                                           uint64_t remaining_qty) const {
    if (remaining_qty == 0) {
        return 0;
    }

    // Favorability: signed fractional price improvement vs arrival for this
    // side. No signal (0) when either price is non-positive.
    double favorability = 0.0;
    if (mid_price > 0.0 && arrival_price > 0.0) {
        const double direction = side == OrderSide::Buy ? 1.0 : -1.0;
        favorability = direction * (arrival_price - mid_price) / arrival_price;
    }

    double fraction = base_participation_ * (1.0 + price_sensitivity_ * favorability);
    if (fraction < 0.0) {
        fraction = 0.0;
    }
    if (fraction > max_participation_) {
        fraction = max_participation_;
    }

    double raw = fraction * static_cast<double>(remaining_qty);
    uint64_t qty = static_cast<uint64_t>(raw + 0.5); // round to nearest share

    if (qty > remaining_qty) {
        qty = remaining_qty;
    }
    // Guarantee forward progress: never stall on a neutral/unfavorable event.
    if (qty < min_order_qty_) {
        qty = std::min(min_order_qty_, remaining_qty);
    }
    return qty;
}


/**
 * POVAlgorithm::generate_orders()
 *
 * See the class comment in algorithms.h for why this throws instead of
 * returning a precomputed schedule: POV needs realized market volume,
 * which does not exist yet at schedule-build time. Use
 * ExecutionSession::run_pov() for real POV execution.
 */
std::vector<Order> POVAlgorithm::generate_orders(
    uint64_t /*parent_order_id*/,
    OrderSide /*side*/,
    uint64_t /*total_qty*/,
    double /*limit_price*/,
    int /*num_slices*/
) {
    throw std::logic_error(
        "POVAlgorithm::generate_orders() is not supported: POV sizes each "
        "child order from realized market volume observed during replay, "
        "which is not known ahead of time. Use "
        "ExecutionSession::run_pov(source, side, total_qty, limit_price, "
        "pov, arrival_price) instead."
    );
}

/**
 * POVAlgorithm::next_order_qty()
 *
 * Time complexity: O(1). Pure function: does not touch the book, the
 * engine, or any strategy-internal fill bookkeeping (spec section 12).
 */
uint64_t POVAlgorithm::next_order_qty(uint64_t event_market_volume, uint64_t remaining_qty) const {
    if (remaining_qty == 0 || event_market_volume == 0 || participation_rate_ <= 0.0) {
        return 0;
    }

    double raw = participation_rate_ * static_cast<double>(event_market_volume);
    uint64_t qty = static_cast<uint64_t>(raw + 0.5); // round to nearest share

    if (max_order_qty_ > 0 && qty > max_order_qty_) {
        qty = max_order_qty_;
    }
    if (qty > remaining_qty) {
        qty = remaining_qty;
    }
    if (qty < min_order_qty_) {
        return 0;
    }
    return qty;
}