#include "market.h"
#include <algorithm>
#include <cmath>
#include <iostream>

namespace {
constexpr uint64_t kSyntheticIdBase = 1000000000;
}

/**
 * MarketSimulator constructor
 */
MarketSimulator::MarketSimulator(double initial_price, const LiquidityModel& liq,
                                                                 uint32_t seed)
        : liquidity(liq), current_price(initial_price), rng(seed),
      next_synthetic_id(kSyntheticIdBase) {}

/**
 * evolve_price()
 *
 * Simulate price movement using random walk.
 *
 * Simple model (can upgrade to GBM):
 * price_new = price_old * (1 + drift + N(0, volatility))
 */
void MarketSimulator::evolve_price(double volatility, double drift) {
    std::normal_distribution<> dist(drift, volatility);
    double change = dist(rng);

    current_price *= (1.0 + change);

    if (current_price < 0.01) {
        current_price = 0.01;
    }
}

/**
 * refresh_synthetic_quotes()
 *
 * Keep the matching engine's inside quotes aligned with the current mid.
 * Previous synthetic liquidity is cancelled (if still resting) so stale
 * prices from earlier ticks cannot fill later strategy orders.
 */
void MarketSimulator::refresh_synthetic_quotes() {
    if (synthetic_bid_id != 0) {
        engine.cancel_order(synthetic_bid_id, OrderSide::Buy, synthetic_bid_price);
        synthetic_bid_id = 0;
    }
    if (synthetic_ask_id != 0) {
        engine.cancel_order(synthetic_ask_id, OrderSide::Sell, synthetic_ask_price);
        synthetic_ask_id = 0;
    }

    const uint64_t qty = liquidity.quoted_quantity();
    synthetic_bid_price = liquidity.quoted_bid(current_price);
    synthetic_ask_price = liquidity.quoted_ask(current_price);

    synthetic_bid_id = next_synthetic_id++;
    synthetic_ask_id = next_synthetic_id++;

    engine.submit_order(Order(
        synthetic_bid_id,
        OrderSide::Buy,
        OrderType::Limit,
        synthetic_bid_price,
        qty
    ));
    engine.submit_order(Order(
        synthetic_ask_id,
        OrderSide::Sell,
        OrderType::Limit,
        synthetic_ask_price,
        qty
    ));
}

/**
 * run_backtest()
 *
 * Each tick:
 *  1. Evolve the mid price
 *  2. Quote bid/ask and size from the current mid and liquidity model
 *  3. Snapshot that market state
 *  4. Submit the next strategy order against those quotes
 */
void MarketSimulator::run_backtest(
    const std::vector<Order>& orders,
    int num_ticks,
    double volatility
) {
    double drift = 0.0;
    size_t order_idx = 0;

    for (int tick = 0; tick < num_ticks; ++tick) {
        evolve_price(volatility, drift);
        refresh_synthetic_quotes();

        const uint64_t qty = liquidity.quoted_quantity();

        // Model a plausible per-tick "market volume" independent of our own
        // strategy order. This simulator only ever matches our own strategy
        // order against static synthetic liquidity - there is no separate
        // population of other traders actually consuming that liquidity - so
        // this is an illustrative volume model (a random fraction of the
        // quoted size), NOT a quantity derived from real matched trades.
        // Without SOME per-tick volume, ExecutionSession::run() (which reads
        // bar_volume/volume, not the engine's trade list) computes
        // market_vwap as a silent zero for every synthetic backtest, which
        // makes vwap_deviation meaningless. This keeps that metric real
        // without pretending the underlying volume is anything but modeled.
        std::uniform_real_distribution<> utilization(0.10, 0.60);
        const uint64_t tick_volume = static_cast<uint64_t>(qty * utilization(rng));
        total_synthetic_volume_ += tick_volume;

        MarketSnapshot snapshot;
        snapshot.last_price = current_price;
        snapshot.mid_price = current_price;
        snapshot.bid = synthetic_bid_price;
        snapshot.ask = synthetic_ask_price;
        snapshot.bid_volume = qty;
        snapshot.ask_volume = qty;
        snapshot.volume = total_synthetic_volume_;
        snapshot.bar_volume = tick_volume;
        snapshot.timestamp_ms = static_cast<uint64_t>(tick * 100);
        snapshot.bids = {{synthetic_bid_price, qty}};
        snapshot.asks = {{synthetic_ask_price, qty}};
        snapshots.push_back(std::move(snapshot));

        if (order_idx < orders.size()) {
            engine.submit_order(orders[order_idx]);
            ++order_idx;
        }
    }
}

VectorMarketSource MarketSimulator::snapshot_source() const {
    return VectorMarketSource(snapshots);
}

/**
 * calculate_slippage()
 *
 * How much worse did you execute than the arrival price?
 *
 * Formula: (execution_price - arrival_price) / arrival_price
 */
double MarketSimulator::calculate_slippage(double arrival_price, double avg_exec_price) const {
    if (arrival_price == 0) return 0;
    return (avg_exec_price - arrival_price) / arrival_price;
}

/**
 * calculate_market_impact()
 *
 * How much did the market move due to your trades?
 *
 * Formula: (final_price - initial_mid) / initial_mid
 */
double MarketSimulator::calculate_market_impact(double initial_mid, const std::vector<Trade>& trades) const {
    if (trades.empty()) return 0;
    double final_mid = current_price;
    return (final_mid - initial_mid) / initial_mid;
}