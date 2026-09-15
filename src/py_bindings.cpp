#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include "engine.h"
#include "market.h"
#include "execution.h"
#include "algorithms.h"
#include "costs.h"
#include "impact.h"

namespace py = pybind11;

/**
 * PYBIND11_MODULE
 * 
 * This macro creates a Python module called "executor".
 * It exports all C++ classes so they can be used from Python.
 * 
 * Usage from Python:
 *   from executor import MatchingEngine, Order, OrderSide, OrderType
 *   engine = MatchingEngine()
 *   order = Order(1, OrderSide.Buy, OrderType.Limit, 100.0, 100)
 *   trades = engine.submit_order(order)
 */
PYBIND11_MODULE(executor, m) {
    m.doc() = "High-performance order matching engine";
    
    // ========================================================================
    // ENUMS
    // ========================================================================
    
    py::enum_<OrderType>(m, "OrderType")
        .value("Market", OrderType::Market)
        .value("Limit", OrderType::Limit)
        .export_values();
    
    py::enum_<OrderSide>(m, "OrderSide")
        .value("Buy", OrderSide::Buy)
        .value("Sell", OrderSide::Sell)
        .export_values();
    
    // ========================================================================
    // STRUCTS
    // ========================================================================
    
    py::class_<Order>(m, "Order")
        .def(py::init<uint64_t, OrderSide, OrderType, double, uint64_t>())
        .def_readwrite("id", &Order::id)
        .def_readwrite("side", &Order::side)
        .def_readwrite("type", &Order::type)
        .def_readwrite("price", &Order::price)
        .def_readwrite("qty", &Order::qty)
        .def_readwrite("filled", &Order::filled)
        .def("remaining", &Order::remaining)
        .def("is_filled", &Order::is_filled);
    
    py::class_<Trade>(m, "Trade")
        .def(py::init<uint64_t, uint64_t, double, uint64_t>())
        .def_readwrite("buy_order_id", &Trade::buy_order_id)
        .def_readwrite("sell_order_id", &Trade::sell_order_id)
        .def_readwrite("price", &Trade::price)
        .def_readwrite("qty", &Trade::qty);

    py::class_<BookLevel>(m, "BookLevel")
        .def(py::init<>())
        .def_readwrite("price", &BookLevel::price)
        .def_readwrite("qty", &BookLevel::qty);
    
    py::class_<MarketSnapshot>(m, "MarketSnapshot")
        .def(py::init<>())
        .def_readwrite("last_price", &MarketSnapshot::last_price)
        .def_readwrite("mid_price", &MarketSnapshot::mid_price)
        .def_readwrite("bid", &MarketSnapshot::bid)
        .def_readwrite("ask", &MarketSnapshot::ask)
        .def_readwrite("bid_volume", &MarketSnapshot::bid_volume)
        .def_readwrite("ask_volume", &MarketSnapshot::ask_volume)
        .def_readwrite("volume", &MarketSnapshot::volume)
        .def_readwrite("bar_volume", &MarketSnapshot::bar_volume)
        .def_readwrite("timestamp_ms", &MarketSnapshot::timestamp_ms)
        .def_readwrite("bids", &MarketSnapshot::bids)
        .def_readwrite("asks", &MarketSnapshot::asks);

    py::class_<MarketDataSource>(m, "MarketDataSource");

    py::class_<VectorMarketSource, MarketDataSource>(m, "VectorMarketSource")
        .def(py::init<std::vector<MarketState>>())
        .def("next", &VectorMarketSource::next)
        .def("reset", &VectorMarketSource::reset);

    py::class_<RealtimeMarketSource, MarketDataSource>(m, "RealtimeMarketSource")
        .def(py::init<>())
        .def("publish", &RealtimeMarketSource::publish)
        .def("next", &RealtimeMarketSource::next)
        .def("reset", &RealtimeMarketSource::reset);

    m.def("normalize_market_state", &normalize_market_state);

    py::class_<CsvMarketSource, MarketDataSource>(m, "CsvMarketSource")
        .def(py::init<std::string>())
        .def("next", &CsvMarketSource::next)
        .def("reset", &CsvMarketSource::reset)
        .def("ok", &CsvMarketSource::ok);

    py::class_<ExecutionFill>(m, "ExecutionFill")
        .def_readonly("trade", &ExecutionFill::trade)
        .def_readonly("timestamp_ms", &ExecutionFill::timestamp_ms)
        .def_readonly("bid", &ExecutionFill::bid)
        .def_readonly("ask", &ExecutionFill::ask)
        .def_readonly("market_volume", &ExecutionFill::market_volume);

    py::class_<ExecutionResult>(m, "ExecutionResult")
        .def_readonly("requested_quantity", &ExecutionResult::requested_quantity)
        .def_readonly("filled_quantity", &ExecutionResult::filled_quantity)
        .def_readonly("arrival_price", &ExecutionResult::arrival_price)
        .def_readonly("average_execution_price", &ExecutionResult::average_execution_price)
        .def_readonly("market_vwap", &ExecutionResult::market_vwap)
        .def_readonly("fill_rate", &ExecutionResult::fill_rate)
        .def_readonly("slippage", &ExecutionResult::slippage)
        .def_readonly("implementation_shortfall", &ExecutionResult::implementation_shortfall)
        .def_readonly("vwap_deviation", &ExecutionResult::vwap_deviation)
        .def_readonly("completion_time_ms", &ExecutionResult::completion_time_ms)
        .def_readonly("market_price_drift", &ExecutionResult::market_price_drift)
        .def_readonly("estimated_spread_cost", &ExecutionResult::estimated_spread_cost)
        .def_readonly("estimated_execution_cost", &ExecutionResult::estimated_execution_cost)
        .def_readonly("fills", &ExecutionResult::fills);

    py::class_<ExecutionSession>(m, "ExecutionSession")
        .def(py::init<>())
        .def("run", &ExecutionSession::run)
        .def("run_with_latency", &ExecutionSession::run_with_latency,
             py::arg("source"), py::arg("child_orders"), py::arg("arrival_price"), py::arg("latency_ms"),
             "Phase 2 (spec section 30): identical to run(), but each child order's "
             "submission is delayed by latency_ms after the event that decided it. "
             "latency_ms=0 is equivalent to run().")
        .def("run_pov", &ExecutionSession::run_pov,
             py::arg("source"), py::arg("side"), py::arg("total_qty"), py::arg("limit_price"),
             py::arg("pov"), py::arg("arrival_price"),
             "Phase 2 (spec section 29): live Percentage-of-Volume execution. Sizes "
             "each child order from realized market volume during replay - unlike "
             "TWAP/VWAP, there is no precomputed order list for POV.")
        .def("engine", &ExecutionSession::engine, py::return_value_policy::reference_internal);
    
    // ========================================================================
    // CLASSES
    // ========================================================================
    
    py::class_<OrderBook>(m, "OrderBook")
        .def(py::init<>())
        .def("add_order", &OrderBook::add_order)
        .def("best_bid", &OrderBook::best_bid)
        .def("best_ask", &OrderBook::best_ask)
        .def("mid_price", &OrderBook::mid_price)
        .def("volume_at", &OrderBook::volume_at)
        .def("cancel_order", &OrderBook::cancel_order)
        .def("print_state", &OrderBook::print_state);
    
    py::class_<MatchingEngine>(m, "MatchingEngine")
        .def(py::init<>())
        .def("submit_order", &MatchingEngine::submit_order)
        .def("cancel_order", &MatchingEngine::cancel_order)
        .def("match_market", &MatchingEngine::match_market)
        .def("match_limit", &MatchingEngine::match_limit)
        .def("get_book", &MatchingEngine::get_book, py::return_value_policy::reference_internal)
        .def("get_all_trades", &MatchingEngine::get_all_trades, py::return_value_policy::reference_internal)
        .def("get_trade_count", &MatchingEngine::get_trade_count);
    
    py::class_<LiquidityModel>(m, "LiquidityModel")
        .def(py::init<double, double, double>())
        .def_readwrite("base_spread", &LiquidityModel::base_spread)
        .def_readwrite("liquidity_at_level", &LiquidityModel::liquidity_at_level)
        .def_readwrite("spread_widening", &LiquidityModel::spread_widening)
        .def("get_ask_for_qty", &LiquidityModel::get_ask_for_qty)
        .def("get_bid_for_qty", &LiquidityModel::get_bid_for_qty)
        .def("quoted_bid", &LiquidityModel::quoted_bid)
        .def("quoted_ask", &LiquidityModel::quoted_ask)
        .def("quoted_quantity", &LiquidityModel::quoted_quantity);
    
    py::class_<MarketSimulator>(m, "MarketSimulator")
        .def(py::init<double, const LiquidityModel&>())
        .def(py::init<double, const LiquidityModel&, uint32_t>(),
             py::arg("initial_price"), py::arg("liquidity"), py::arg("seed"))
        .def("run_backtest", &MarketSimulator::run_backtest)
        .def("get_engine", &MarketSimulator::get_engine, py::return_value_policy::reference_internal)
        .def("get_current_price", &MarketSimulator::get_current_price)
        .def("get_snapshots", &MarketSimulator::get_snapshots)
        .def("snapshot_source", &MarketSimulator::snapshot_source)
        .def("calculate_slippage", &MarketSimulator::calculate_slippage)
        .def("calculate_market_impact", &MarketSimulator::calculate_market_impact);

    // ========================================================================
    // EXECUTION ALGORITHMS
    // ========================================================================

    py::class_<TWAPAlgorithm>(m, "TWAPAlgorithm")
        .def(py::init<>())
        .def("generate_orders", &TWAPAlgorithm::generate_orders)
        .def("name", &TWAPAlgorithm::name);

    py::class_<VWAPAlgorithm>(m, "VWAPAlgorithm")
        .def(py::init<>())
        .def("set_volume_profile", &VWAPAlgorithm::set_volume_profile)
        .def("generate_orders", &VWAPAlgorithm::generate_orders)
        .def("name", &VWAPAlgorithm::name);

    // ========================================================================
    // POV (Percentage of Volume) - Phase 2, spec section 29.
    //
    // generate_orders() is bound for interface parity with TWAP/VWAP but
    // raises a Python exception if called (it throws std::logic_error in
    // C++ - pybind11 translates that to a Python RuntimeError automatically).
    // Real POV execution goes through ExecutionSession.run_pov(), which
    // calls next_order_qty() once per replayed market event.
    // ========================================================================

    py::class_<POVAlgorithm>(m, "POVAlgorithm")
        .def(py::init<double, uint64_t, uint64_t>(),
             py::arg("participation_rate") = 0.1,
             py::arg("min_order_qty") = 1,
             py::arg("max_order_qty") = 0)
        .def("generate_orders", &POVAlgorithm::generate_orders)
        .def("next_order_qty", &POVAlgorithm::next_order_qty,
             py::arg("event_market_volume"), py::arg("remaining_qty"))
        .def_property_readonly("participation_rate", &POVAlgorithm::participation_rate)
        .def_property_readonly("min_order_qty", &POVAlgorithm::min_order_qty)
        .def_property_readonly("max_order_qty", &POVAlgorithm::max_order_qty)
        .def("name", &POVAlgorithm::name);

    // ========================================================================
    // TRANSACTION COST MODEL (Phase 1, section 19)
    // ========================================================================

    py::class_<TransactionCostConfig>(m, "TransactionCostConfig")
        .def(py::init<>())
        .def_readwrite("commission_bps", &TransactionCostConfig::commission_bps)
        .def_readwrite("exchange_fee_bps", &TransactionCostConfig::exchange_fee_bps)
        .def_readwrite("fixed_fee_per_fill", &TransactionCostConfig::fixed_fee_per_fill);

    py::class_<TransactionCostBreakdown>(m, "TransactionCostBreakdown")
        .def_readonly("commission", &TransactionCostBreakdown::commission)
        .def_readonly("exchange_fees", &TransactionCostBreakdown::exchange_fees)
        .def_readonly("fixed_fees", &TransactionCostBreakdown::fixed_fees)
        .def_readonly("spread_cost", &TransactionCostBreakdown::spread_cost)
        .def_readonly("total_cost", &TransactionCostBreakdown::total_cost)
        .def_readonly("total_cost_bps", &TransactionCostBreakdown::total_cost_bps);

    m.def("compute_transaction_costs", &compute_transaction_costs,
          py::arg("result"), py::arg("config"),
          "Compute commission/fee/spread cost breakdown for a completed ExecutionResult.");

    // ========================================================================
    // SIMPLIFIED MARKET IMPACT MODEL (Phase 2, spec section 31)
    // ========================================================================

    py::class_<MarketImpactConfig>(m, "MarketImpactConfig")
        .def(py::init<>())
        .def(py::init<double>(), py::arg("eta"))
        .def_readwrite("eta", &MarketImpactConfig::eta);

    py::class_<MarketImpactEstimate>(m, "MarketImpactEstimate")
        .def_readonly("participation_rate", &MarketImpactEstimate::participation_rate)
        .def_readonly("impact_bps", &MarketImpactEstimate::impact_bps)
        .def_readonly("impact_cost", &MarketImpactEstimate::impact_cost);

    m.def("estimate_market_impact", &estimate_market_impact,
          py::arg("executed_quantity"), py::arg("market_volume_over_window"),
          py::arg("volatility"), py::arg("avg_execution_price"), py::arg("config"),
          "Estimate the impact-attributable share of execution cost using a "
          "simplified square-root participation model. See impact.h for the "
          "formula and its explicit limitations.");
}