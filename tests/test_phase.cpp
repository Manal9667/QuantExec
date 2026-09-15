#include "../include/execution.h"
#include "../include/algorithms.h"
#include "../include/market.h"
#include <cassert>
#include <cmath>
#include <fstream>
#include <iostream>

namespace {
bool close_enough(double a, double b, double eps = 1e-9) {
    return std::fabs(a - b) < eps;
}
}

void test_vector_source_and_session() {
    VectorMarketSource source({
        {100.0, 0.0, 99.0, 100.0, 100, 100, 1000, 100, 1, {{99.0, 100}}, {{100.0, 100}, {100.5, 200}}},
        {100.0, 0.0, 99.0, 100.0, 100, 100, 1200, 200, 2, {{99.0, 100}}, {{100.0, 100}, {100.5, 200}}}
    });
    TWAPAlgorithm twap;
    const auto orders = twap.generate_orders(10, OrderSide::Buy, 250, 1000.0, 2);

    ExecutionSession session;
    const auto result = session.run(source, orders, 99.5);
    // Each tick republishes the full quoted depth for that moment (see
    // market_data.h: a MarketState is "current standing liquidity", not a
    // delta) - so a 125-share TWAP slice against 300 shares of quoted
    // depth fills completely each time it's submitted. With 2 slices and
    // 2 ticks that's 250/250 filled across 4 fill records (2 per tick:
    // 100 @ 100.0 exhausts the first level, 25 @ 100.5 from the second).
    assert(result.filled_quantity == 250);
    assert(result.fills.size() == 4);
    assert(result.fills[0].trade.price == 100.0);
    assert(result.fills[0].trade.qty == 100);
    assert(result.fills[1].trade.price == 100.5);
    assert(result.fills[1].trade.qty == 25);
    assert(result.fills[2].trade.price == 100.0);
    assert(result.fills[2].trade.qty == 100);
    assert(result.fills[3].trade.price == 100.5);
    assert(result.fills[3].trade.qty == 25);
    assert(result.completion_time_ms == 2);
    assert(result.fill_rate == 1.0);
    assert(result.market_vwap == (100.0 * 100.0 + 100.0 * 200.0) / 300.0); 

    // Market impact decomposition: both ticks quote bid=99/ask=100, so the
    // market itself never moves -> drift should be exactly zero, and the
    // spread cost is just half that spread as a fraction of the first mid.
    assert(close_enough(result.market_price_drift, 0.0));
    assert(close_enough(result.estimated_spread_cost, 0.5 / 99.5));
    assert(close_enough(result.estimated_execution_cost,
                         result.slippage - result.estimated_spread_cost));
}

void test_csv_source() {
    const std::string path = "phase_market_test.csv";
    {
        std::ofstream file(path);
        file << "timestamp_ms,last,bid,ask,bid_size,ask_size,volume,bar_volume,bid_depth,ask_depth\n";
        file << "10,100,99.5,100.5,50,75,20,20,99.5:50|99:100,100.5:75|101:125\n";
    }
    CsvMarketSource source(path);
    MarketState state;
    assert(source.ok());
    assert(source.next(state));
    assert(state.mid_price == 100.0);
    assert(state.asks.size() == 2);
    assert(state.asks[1].qty == 125);
    assert(!source.next(state));
    source.reset();
    assert(source.next(state));
    std::remove(path.c_str());
}

void test_csv_replay_window_and_seek() {
    const std::string path = "phase_replay_window_test.csv";
    {
        std::ofstream file(path);
        file << "timestamp_ms,last,bid,ask,bid_size,ask_size,volume\n";
        file << "10,100,99,101,100,100,10\n";
        file << "20,100,99,101,100,100,20\n";
        file << "30,100,99,101,100,100,30\n";
        file << "40,100,99,101,100,100,40\n";
    }

    CsvMarketSource source(path);
    source.set_time_window(20, 30);
    MarketState state;
    assert(source.next(state) && state.timestamp_ms == 20);
    assert(source.current_time_ms() == 20);
    assert(source.next(state) && state.timestamp_ms == 30);
    assert(!source.next(state));

    source.seek(40);
    assert(source.next(state) && state.timestamp_ms == 40);
    assert(!source.next(state));
    std::remove(path.c_str());
}

void test_sell_side_analytics_use_adverse_price_direction() {
    VectorMarketSource source({
        {100.0, 0.0, 99.0, 100.0, 100, 100, 100, 100, 1,
         {{99.0, 100}}, {{100.0, 100}}}
    });
    ExecutionSession session;
    const auto result = session.run(
        source,
        {Order(1, OrderSide::Sell, OrderType::Limit, 0.0, 50)},
        100.0);

    assert(result.filled_quantity == 50);
    assert(close_enough(result.average_execution_price, 99.0));
    assert(close_enough(result.slippage, 0.01));
    assert(close_enough(result.implementation_shortfall, 50.0));
}

void test_invalid_algorithm_inputs() {
    TWAPAlgorithm twap;
    VWAPAlgorithm vwap;
    assert(twap.generate_orders(1, OrderSide::Buy, 100, 100.0, 0).empty());
    assert(vwap.generate_orders(1, OrderSide::Buy, 100, 100.0, -1).empty());
    vwap.set_volume_profile({0.0, -1.0});
    const auto orders = vwap.generate_orders(1, OrderSide::Buy, 100, 100.0, 2);
    assert(orders.size() == 2);
    assert(orders[0].qty + orders[1].qty == 100);
}

void test_synthetic_snapshots_are_replayable() {
    MarketSimulator simulator(100.0, LiquidityModel(0.02, 100, 0.0), 7);
    simulator.run_backtest({}, 2, 0.0);
    auto source = simulator.snapshot_source();
    MarketState state;
    assert(source.next(state));
    assert(state.bid == 99.99);
    assert(state.ask == 100.01);
    assert(state.bids.size() == 1);
    assert(state.asks.size() == 1);
}

void test_realtime_source_requires_ordered_events() {
    RealtimeMarketSource source;
    MarketState first;
    first.timestamp_ms = 20;
    first.bid = 99.0;
    first.ask = 101.0;
    assert(source.publish(first));
    MarketState late = first;
    late.timestamp_ms = 10;
    assert(!source.publish(late));
    MarketState out;
    assert(source.next(out));
    assert(out.mid_price == 100.0);
}

void test_historical_replay_is_reproducible() {
    // Phase 3, section 3.3: same dataset + same strategy parameters must
    // produce the same result, every time. CsvMarketSource has no
    // randomness, so this should hold trivially - but we test it explicitly
    // rather than assuming it, since a bug (e.g. iterator state leaking
    // between runs) could silently break reproducibility without any
    // single-run test catching it.
    const std::string path = "phase3_reproducibility_test.csv";
    {
        std::ofstream file(path);
        file << "timestamp_ms,last,bid,ask,bid_size,ask_size,volume,bar_volume\n";
        file << "1,100.0,99.5,100.5,200,200,1000,1000\n";
        file << "2,100.2,99.7,100.7,200,200,1500,500\n";
        file << "3,100.1,99.6,100.6,200,200,1900,400\n";
    }

    TWAPAlgorithm twap;
    const auto orders = twap.generate_orders(1, OrderSide::Buy, 300, 1000.0, 3);

    CsvMarketSource source_a(path);
    ExecutionSession session_a;
    const auto result_a = session_a.run(source_a, orders, 100.0);

    CsvMarketSource source_b(path);
    ExecutionSession session_b;
    const auto result_b = session_b.run(source_b, orders, 100.0);

    assert(result_a.filled_quantity == result_b.filled_quantity);
    assert(result_a.average_execution_price == result_b.average_execution_price);
    assert(result_a.market_vwap == result_b.market_vwap);
    assert(result_a.slippage == result_b.slippage);
    assert(result_a.market_price_drift == result_b.market_price_drift);
    assert(result_a.estimated_spread_cost == result_b.estimated_spread_cost);
    assert(result_a.fills.size() == result_b.fills.size());

    // Re-running the SAME session object again (source.reset() happens
    // inside run()) must also match - reproducibility shouldn't depend on
    // constructing fresh objects.
    const auto result_a2 = session_a.run(source_a, orders, 100.0);
    assert(result_a.filled_quantity == result_a2.filled_quantity);
    assert(result_a.average_execution_price == result_a2.average_execution_price);

    std::remove(path.c_str());
}

void test_market_state_invariants_and_quantity_conservation() {
    const MarketState state{
        100.0,
        100.0,
        99.5,
        100.5,
        250,
        300,
        4000,
        400,
        10,
        {{99.5, 250}},
        {{100.5, 300}}
    };

    assert(state.bid <= state.ask);
    assert(state.bids.front().price == 99.5);
    assert(state.asks.front().price == 100.5);
    assert(state.mid_price == 100.0);

    MatchingEngine engine;
    engine.submit_order(Order(1, OrderSide::Buy, OrderType::Limit, 100.5, 100));
    engine.submit_order(Order(2, OrderSide::Sell, OrderType::Limit, 99.5, 100));

    const auto trades = engine.get_all_trades();
    assert(!trades.empty());
    assert(trades[0].qty == 100);
}

int main() {
    test_vector_source_and_session();
    test_csv_source();
    test_csv_replay_window_and_seek();
    test_sell_side_analytics_use_adverse_price_direction();
    test_invalid_algorithm_inputs();
    test_synthetic_snapshots_are_replayable();
    test_realtime_source_requires_ordered_events();
    test_historical_replay_is_reproducible();
    test_market_state_invariants_and_quantity_conservation();
    std::cout << "Phase source/session tests passed\n";
    return 0;
}