#include "../include/costs.h"
#include <cassert>
#include <cmath>
#include <iostream>

/**
 * Simple test framework (no external dependencies) - matches the style
 * used by the other test_*.cpp files in this suite.
 */
int test_count = 0;
int pass_count = 0;

void assert_true(const std::string& name, bool condition) {
    test_count++;
    if (condition) {
        pass_count++;
        std::cout << "\xE2\x9C\x93 " << name << std::endl;
    } else {
        std::cout << "\xE2\x9C\x97 " << name << std::endl;
    }
}

bool close_enough(double a, double b, double eps = 1e-9) {
    return std::fabs(a - b) < eps;
}

namespace {

ExecutionFill make_fill(double price, uint64_t qty) {
    ExecutionFill fill{Trade(1, 2, price, qty), 0, price, price, 0};
    return fill;
}

} // namespace

void test_zero_config_gives_zero_cost() {
    ExecutionResult result;
    result.fills = {make_fill(100.0, 100), make_fill(100.5, 50)};
    result.filled_quantity = 150;

    TransactionCostConfig config; // all zero by default
    const auto breakdown = compute_transaction_costs(result, config);

    assert_true("zero config: commission is zero", close_enough(breakdown.commission, 0.0));
    assert_true("zero config: exchange fees are zero", close_enough(breakdown.exchange_fees, 0.0));
    assert_true("zero config: fixed fees are zero", close_enough(breakdown.fixed_fees, 0.0));
    assert_true("zero config: spread cost is zero", close_enough(breakdown.spread_cost, 0.0));
    assert_true("zero config: total cost is zero", close_enough(breakdown.total_cost, 0.0));
    assert_true("zero config: total cost bps is zero", close_enough(breakdown.total_cost_bps, 0.0));
}

void test_commission_bps_applied_to_notional() {
    ExecutionResult result;
    result.fills = {make_fill(100.0, 1000)}; // notional = 100,000
    result.filled_quantity = 1000;

    TransactionCostConfig config;
    config.commission_bps = 1.0; // 1 bp = 0.0001

    const auto breakdown = compute_transaction_costs(result, config);
    // 100,000 * 0.0001 = 10.0
    assert_true("commission scales with notional", close_enough(breakdown.commission, 10.0));
    assert_true("commission-only total matches commission", close_enough(breakdown.total_cost, 10.0));
}

void test_exchange_fee_bps_applied_to_notional() {
    ExecutionResult result;
    result.fills = {make_fill(50.0, 200)}; // notional = 10,000
    result.filled_quantity = 200;

    TransactionCostConfig config;
    config.exchange_fee_bps = 2.0; // 2 bps

    const auto breakdown = compute_transaction_costs(result, config);
    // 10,000 * 0.0002 = 2.0
    assert_true("exchange fee scales with notional", close_enough(breakdown.exchange_fees, 2.0));
}

void test_fixed_fee_charged_per_fill() {
    ExecutionResult result;
    result.fills = {make_fill(100.0, 100), make_fill(101.0, 100), make_fill(102.0, 100)};
    result.filled_quantity = 300;

    TransactionCostConfig config;
    config.fixed_fee_per_fill = 0.5;

    const auto breakdown = compute_transaction_costs(result, config);
    assert_true("fixed fee charged once per fill (3 fills)", close_enough(breakdown.fixed_fees, 1.5));
}

void test_spread_cost_uses_estimated_spread_cost_field() {
    ExecutionResult result;
    result.fills = {make_fill(100.0, 100)}; // notional = 10,000
    result.filled_quantity = 100;
    result.estimated_spread_cost = 0.0005; // 5 bps of mid, per execution.h convention

    TransactionCostConfig config; // no commission/fees, isolate spread cost
    const auto breakdown = compute_transaction_costs(result, config);

    // 10,000 * 0.0005 = 5.0
    assert_true("spread cost derived from estimated_spread_cost", close_enough(breakdown.spread_cost, 5.0));
    assert_true("total cost equals spread cost when nothing else configured",
                close_enough(breakdown.total_cost, 5.0));
}

void test_total_cost_bps_matches_definition() {
    ExecutionResult result;
    result.fills = {make_fill(100.0, 1000)}; // notional = 100,000
    result.filled_quantity = 1000;

    TransactionCostConfig config;
    config.commission_bps = 0.5;
    config.exchange_fee_bps = 0.3;
    config.fixed_fee_per_fill = 1.0;

    const auto breakdown = compute_transaction_costs(result, config);
    // commission = 5.0, exchange = 3.0, fixed = 1.0 -> total = 9.0
    assert_true("combined total cost", close_enough(breakdown.total_cost, 9.0));
    // bps = total / notional * 10000 = 9.0 / 100000 * 10000 = 0.9
    assert_true("total cost bps matches total/notional*10000",
                close_enough(breakdown.total_cost_bps, 0.9));
}

void test_no_fills_does_not_divide_by_zero() {
    ExecutionResult result; // empty fills
    TransactionCostConfig config;
    config.commission_bps = 5.0;

    const auto breakdown = compute_transaction_costs(result, config);
    assert_true("no fills: total cost is zero", close_enough(breakdown.total_cost, 0.0));
    assert_true("no fills: total cost bps is zero (no NaN/inf)", close_enough(breakdown.total_cost_bps, 0.0));
}

int main() {
    std::cout << "Running TransactionCostModel tests...\n\n";

    test_zero_config_gives_zero_cost();
    test_commission_bps_applied_to_notional();
    test_exchange_fee_bps_applied_to_notional();
    test_fixed_fee_charged_per_fill();
    test_spread_cost_uses_estimated_spread_cost_field();
    test_total_cost_bps_matches_definition();
    test_no_fills_does_not_divide_by_zero();

    std::cout << "\n";
    std::cout << "Results: " << pass_count << "/" << test_count << " passed" << std::endl;

    if (pass_count == test_count) {
        std::cout << "All tests passed!" << std::endl;
        return 0;
    } else {
        std::cout << "Some tests failed" << std::endl;
        return 1;
    }
}