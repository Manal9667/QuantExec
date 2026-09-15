#include "execution.h"

#include <algorithm>
#include <deque>

namespace {

/**
 * Shared by run(), run_with_latency(), and run_pov(): every entry point
 * replays the same kind of market-state stream and needs the same set of
 * post-hoc metrics computed from whatever fills/volume it observed. Kept
 * as one function so the analytics formulas (spec section 20) exist in
 * exactly one place - duplicating them per entry point is how a slippage
 * or shortfall formula quietly drifts between strategies.
 */
void finalize_result(
    ExecutionResult& result,
    OrderSide side,
    double arrival_price,
    double market_value,
    uint64_t market_quantity,
    double first_mid,
    double first_spread,
    double last_mid
) {
    const double direction = side == OrderSide::Buy ? 1.0 : -1.0;
    double execution_value = 0.0;
    for (const auto& fill : result.fills) {
        execution_value += fill.trade.price * fill.trade.qty;
    }
    if (result.filled_quantity > 0) {
        result.average_execution_price = execution_value / result.filled_quantity;
    }
    if (market_quantity > 0) {
        result.market_vwap = market_value / market_quantity;
    }
    if (result.requested_quantity > 0) {
        result.fill_rate = static_cast<double>(result.filled_quantity) /
                           result.requested_quantity;
    }
    if (arrival_price != 0.0 && result.filled_quantity > 0) {
        result.slippage = direction *
                          (result.average_execution_price - arrival_price) /
                          arrival_price;
        result.implementation_shortfall =
            direction * (result.average_execution_price - arrival_price) *
            result.filled_quantity;
    }
    if (result.market_vwap != 0.0 && result.filled_quantity > 0) {
        result.vwap_deviation = direction *
                                (result.average_execution_price - result.market_vwap) /
                                result.market_vwap;
    }

    // Market impact decomposition - see the field doc comments in execution.h
    // for what these do and do not claim to measure.
    if (first_mid > 0.0) {
        result.market_price_drift = (last_mid - first_mid) / first_mid;
        result.estimated_spread_cost = (first_spread / 2.0) / first_mid;
    }
    if (result.filled_quantity > 0) {
        result.estimated_execution_cost =
            result.slippage - result.estimated_spread_cost;
    }
}

} // namespace

ExecutionResult ExecutionSession::run(
    MarketDataSource& source,
    const std::vector<Order>& child_orders,
    double arrival_price
) {
    ExecutionResult result;
    result.arrival_price = arrival_price;
    for (const auto& order : child_orders) {
        result.requested_quantity += order.qty;
    }

    source.reset();
    engine_.clear_book();
    MarketState state;
    size_t order_index = 0;
    double market_value = 0.0;
    uint64_t market_quantity = 0;
    uint64_t previous_cumulative_volume = 0;
    double first_mid = 0.0;
    double first_spread = 0.0;
    double last_mid = 0.0;

    while (source.next(state)) {
        normalize_market_state(state);
        engine_.clear_book();
        uint64_t level_id = 4000000000ULL;
        for (const auto& level : state.bids) {
            engine_.submit_order(Order(level_id++, OrderSide::Buy, OrderType::Limit,
                                       level.price, level.qty));
        }
        for (const auto& level : state.asks) {
            engine_.submit_order(Order(level_id++, OrderSide::Sell, OrderType::Limit,
                                       level.price, level.qty));
        }

        if (state.mid_price > 0.0) {
            if (first_mid <= 0.0) {
                first_mid = state.mid_price;
                if (state.bid > 0.0 && state.ask > 0.0) {
                    first_spread = state.ask - state.bid;
                }
            }
            last_mid = state.mid_price;
        }

        const uint64_t event_volume = state.bar_volume > 0
            ? state.bar_volume
            : state.volume >= previous_cumulative_volume
                ? state.volume - previous_cumulative_volume
                : 0;
        previous_cumulative_volume = state.volume;
        if (event_volume > 0 && state.last_price > 0.0) {
            market_value += state.last_price * event_volume;
            market_quantity += event_volume;
        }

        if (order_index >= child_orders.size()) {
            continue;
        }
        const auto& order = child_orders[order_index++];
        const auto trades = engine_.submit_order(order);
        for (const auto& trade : trades) {
            result.filled_quantity += trade.qty;
            result.fills.push_back({trade, state.timestamp_ms, state.bid, state.ask, event_volume});
        }
        if (!trades.empty()) {
            result.completion_time_ms = state.timestamp_ms;
        }
    }

    const OrderSide side = child_orders.empty() ? OrderSide::Buy : child_orders.front().side;
    finalize_result(result, side, arrival_price, market_value, market_quantity,
                    first_mid, first_spread, last_mid);
    return result;
}

ExecutionResult ExecutionSession::run_with_latency(
    MarketDataSource& source,
    const std::vector<Order>& child_orders,
    double arrival_price,
    uint64_t latency_ms
) {
    ExecutionResult result;
    result.arrival_price = arrival_price;
    for (const auto& order : child_orders) {
        result.requested_quantity += order.qty;
    }

    source.reset();
    engine_.clear_book();
    MarketState state;
    size_t order_index = 0;
    double market_value = 0.0;
    uint64_t market_quantity = 0;
    uint64_t previous_cumulative_volume = 0;
    double first_mid = 0.0;
    double first_spread = 0.0;
    double last_mid = 0.0;

    // Orders that have been "decided" (spec section 30) but are not yet
    // executable because their latency has not elapsed.
    struct PendingOrder {
        uint64_t ready_time_ms;
        Order order;
    };
    std::deque<PendingOrder> pending;

    while (source.next(state)) {
        normalize_market_state(state);
        engine_.clear_book();
        uint64_t level_id = 4000000000ULL;
        for (const auto& level : state.bids) {
            engine_.submit_order(Order(level_id++, OrderSide::Buy, OrderType::Limit,
                                       level.price, level.qty));
        }
        for (const auto& level : state.asks) {
            engine_.submit_order(Order(level_id++, OrderSide::Sell, OrderType::Limit,
                                       level.price, level.qty));
        }

        if (state.mid_price > 0.0) {
            if (first_mid <= 0.0) {
                first_mid = state.mid_price;
                if (state.bid > 0.0 && state.ask > 0.0) {
                    first_spread = state.ask - state.bid;
                }
            }
            last_mid = state.mid_price;
        }

        const uint64_t event_volume = state.bar_volume > 0
            ? state.bar_volume
            : state.volume >= previous_cumulative_volume
                ? state.volume - previous_cumulative_volume
                : 0;
        previous_cumulative_volume = state.volume;
        if (event_volume > 0 && state.last_price > 0.0) {
            market_value += state.last_price * event_volume;
            market_quantity += event_volume;
        }

        // A new order is "decided" this event, at the same one-per-event
        // cadence run() uses, then queued until its latency elapses.
        if (order_index < child_orders.size()) {
            pending.push_back({state.timestamp_ms + latency_ms, child_orders[order_index++]});
        }

        // Submit every pending order whose latency has now elapsed. A
        // while-loop (not an if) because several orders can become ready
        // on the same event when latency_ms is small relative to the
        // spacing between events.
        while (!pending.empty() && pending.front().ready_time_ms <= state.timestamp_ms) {
            const Order order = pending.front().order;
            pending.pop_front();
            const auto trades = engine_.submit_order(order);
            for (const auto& trade : trades) {
                result.filled_quantity += trade.qty;
                result.fills.push_back({trade, state.timestamp_ms, state.bid, state.ask, event_volume});
            }
            if (!trades.empty()) {
                result.completion_time_ms = state.timestamp_ms;
            }
        }
    }

    const OrderSide side = child_orders.empty() ? OrderSide::Buy : child_orders.front().side;
    finalize_result(result, side, arrival_price, market_value, market_quantity,
                    first_mid, first_spread, last_mid);
    return result;
}

ExecutionResult ExecutionSession::run_pov(
    MarketDataSource& source,
    OrderSide side,
    uint64_t total_qty,
    double limit_price,
    const POVAlgorithm& pov,
    double arrival_price
) {
    ExecutionResult result;
    result.arrival_price = arrival_price;
    result.requested_quantity = total_qty;

    source.reset();
    engine_.clear_book();
    MarketState state;
    uint64_t remaining_qty = total_qty;
    uint64_t next_child_id = 1;
    double market_value = 0.0;
    uint64_t market_quantity = 0;
    uint64_t previous_cumulative_volume = 0;
    double first_mid = 0.0;
    double first_spread = 0.0;
    double last_mid = 0.0;

    while (source.next(state) && remaining_qty > 0) {
        normalize_market_state(state);
        engine_.clear_book();
        uint64_t level_id = 4000000000ULL;
        for (const auto& level : state.bids) {
            engine_.submit_order(Order(level_id++, OrderSide::Buy, OrderType::Limit,
                                       level.price, level.qty));
        }
        for (const auto& level : state.asks) {
            engine_.submit_order(Order(level_id++, OrderSide::Sell, OrderType::Limit,
                                       level.price, level.qty));
        }

        if (state.mid_price > 0.0) {
            if (first_mid <= 0.0) {
                first_mid = state.mid_price;
                if (state.bid > 0.0 && state.ask > 0.0) {
                    first_spread = state.ask - state.bid;
                }
            }
            last_mid = state.mid_price;
        }

        const uint64_t event_volume = state.bar_volume > 0
            ? state.bar_volume
            : state.volume >= previous_cumulative_volume
                ? state.volume - previous_cumulative_volume
                : 0;
        previous_cumulative_volume = state.volume;
        if (event_volume > 0 && state.last_price > 0.0) {
            market_value += state.last_price * event_volume;
            market_quantity += event_volume;
        }

        // The only strategy-specific line in this loop: POV decides this
        // event's child order size from realized volume. Everything else
        // (book setup, fills, analytics accumulation) is identical to
        // run()/run_with_latency() - the execution engine, not the
        // strategy, still does all liquidity consumption (spec section 12).
        const uint64_t child_qty = pov.next_order_qty(event_volume, remaining_qty);
        if (child_qty > 0) {
            Order child(next_child_id++, side, OrderType::Limit, limit_price, child_qty);
            const auto trades = engine_.submit_order(child);
            for (const auto& trade : trades) {
                result.filled_quantity += trade.qty;
                result.fills.push_back({trade, state.timestamp_ms, state.bid, state.ask, event_volume});
                remaining_qty -= std::min(remaining_qty, trade.qty);
            }
            if (!trades.empty()) {
                result.completion_time_ms = state.timestamp_ms;
            }
        }
    }

    finalize_result(result, side, arrival_price, market_value, market_quantity,
                    first_mid, first_spread, last_mid);
    return result;
}