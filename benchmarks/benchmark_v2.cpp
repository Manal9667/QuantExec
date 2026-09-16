// Step 7: evidence-based benchmarking.
//
// Every claim this program prints is measured, not estimated - it exists
// specifically to replace ad-hoc "looks fast" numbers with a repeatable
// protocol: a defined workload, recorded hardware/software, warm-up +
// multiple measured iterations, separated stage timings, and memory
// usage. See docs/BENCHMARKING.md for how to read and reproduce this.
//
// Usage:
//   ./benchmark_v2 [dataset.csv]     (defaults to datasets/sample_synthetic.csv)
//
// This is intentionally a separate binary from the original
// benchmarks/benchmark.cpp (kept as-is for anyone already using it) so
// this file's stricter protocol doesn't silently change numbers someone
// may already be tracking from the older, single-shot benchmark.

#include "../include/book.h"
#include "../include/engine.h"
#include "../include/algorithms.h"
#include "../include/market_data.h"
#include "../include/execution.h"
#include "../include/costs.h"

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <numeric>
#include <sstream>
#include <string>
#include <vector>

#if defined(__unix__) || defined(__APPLE__)
#include <sys/resource.h>
#define HAVE_GETRUSAGE 1
#endif

namespace {

constexpr int kWarmupIterations = 3;
constexpr int kMeasuredIterations = 10;

double now_ms_since(const std::chrono::high_resolution_clock::time_point& start) {
    return std::chrono::duration<double, std::milli>(std::chrono::high_resolution_clock::now() - start).count();
}

long peak_rss_kb() {
#ifdef HAVE_GETRUSAGE
    struct rusage usage;
    getrusage(RUSAGE_SELF, &usage);
    return usage.ru_maxrss;  // Linux: KB. (macOS reports bytes; not a target platform here.)
#else
    return -1;  // not available on this platform
#endif
}

// Simple, non-cryptographic content fingerprint so two benchmark runs can
// confirm they used the same file without pulling in a SHA-256
// implementation into this binary. For an authoritative checksum, use
// scripts/build_dataset_manifest.py (SHA-256) - that is the checksum
// dataset.md and experiment manifests actually rely on.
uint64_t fnv1a64(const std::string& path) {
    std::ifstream f(path, std::ios::binary);
    uint64_t hash = 14695981039346656037ull;
    char c;
    while (f.get(c)) {
        hash ^= static_cast<unsigned char>(c);
        hash *= 1099511628211ull;
    }
    return hash;
}

struct StageStats {
    std::string name;
    std::vector<double> samples_ms;

    double median() const {
        auto sorted = samples_ms;
        std::sort(sorted.begin(), sorted.end());
        return sorted[sorted.size() / 2];
    }
    double p95() const {
        auto sorted = samples_ms;
        std::sort(sorted.begin(), sorted.end());
        return sorted[static_cast<size_t>(0.95 * (sorted.size() - 1))];
    }
    double mean() const {
        return std::accumulate(samples_ms.begin(), samples_ms.end(), 0.0) / samples_ms.size();
    }
    double min() const { return *std::min_element(samples_ms.begin(), samples_ms.end()); }
    double max() const { return *std::max_element(samples_ms.begin(), samples_ms.end()); }
};

// Runs `f` kWarmupIterations times (discarded) then kMeasuredIterations
// times (recorded) and returns the per-iteration timings. Warm-up exists
// because the first call into a freshly-loaded code path pays costs
// (page faults, allocator warm-up, branch predictor cold-start) that
// don't represent steady-state behavior - the exact reason Step 7 asks
// for it explicitly rather than leaving it implicit.
template <typename Func>
StageStats run_staged(const std::string& name, Func f) {
    for (int i = 0; i < kWarmupIterations; ++i) f();
    StageStats stats;
    stats.name = name;
    for (int i = 0; i < kMeasuredIterations; ++i) {
        auto start = std::chrono::high_resolution_clock::now();
        f();
        stats.samples_ms.push_back(now_ms_since(start));
    }
    return stats;
}

void print_stage(const StageStats& s) {
    std::cout << std::left << std::setw(22) << s.name
              << " median=" << std::fixed << std::setprecision(4) << std::setw(10) << s.median()
              << " p95=" << std::setw(10) << s.p95()
              << " mean=" << std::setw(10) << s.mean()
              << " min=" << std::setw(10) << s.min()
              << " max=" << std::setw(10) << s.max()
              << " (ms, n=" << s.samples_ms.size() << ")" << std::endl;
}

} // namespace

int main(int argc, char** argv) {
    const std::string dataset_path = argc > 1 ? argv[1] : "datasets/sample_synthetic.csv";

    std::cout << std::string(78, '=') << "\n";
    std::cout << "EVIDENCE-BASED BENCHMARK (Step 7)\n";
    std::cout << std::string(78, '=') << "\n\n";

    // --- Software / build info -------------------------------------------
    std::cout << "-- Build --\n";
#if defined(__VERSION__)
    std::cout << "Compiler:        " << __VERSION__ << "\n";
#endif
#ifdef NDEBUG
    std::cout << "Build type:      Release (NDEBUG defined)\n";
#else
    std::cout << "Build type:      Debug/unspecified (NDEBUG NOT defined - re-run via Release build for real numbers)\n";
#endif
    std::cout << "Warm-up iters:   " << kWarmupIterations << "\n";
    std::cout << "Measured iters:  " << kMeasuredIterations << "\n\n";

    // --- Workload definition ----------------------------------------------
    std::cout << "-- Workload --\n";
    std::cout << "Dataset:         " << dataset_path << "\n";
    std::cout << "Content hash:    0x" << std::hex << fnv1a64(dataset_path) << std::dec
              << "  (FNV-1a, non-cryptographic - see scripts/build_dataset_manifest.py for SHA-256)\n";

    CsvMarketSource probe(dataset_path);
    if (!probe.ok()) {
        std::cerr << "ERROR: could not load dataset " << dataset_path << std::endl;
        return 1;
    }
    size_t num_events = 0;
    MarketState state;
    while (probe.next(state)) ++num_events;
    std::cout << "Market events:   " << num_events << "\n";
    std::cout << "Order-book depth used: top-of-book (+2 levels where dataset provides bid_depth/ask_depth)\n\n";

    // --- Stage 1: parsing ---------------------------------------------------
    auto parsing_stats = run_staged("parsing (CSV load)", [&]() {
        CsvMarketSource source(dataset_path);
        (void)source.ok();
    });

    // --- Stage 2: replay (iterate every event, no matching) ----------------
    auto replay_stats = run_staged("replay (iterate)", [&]() {
        CsvMarketSource source(dataset_path);
        MarketState s;
        while (source.next(s)) { /* no-op: isolates pure iteration cost */ }
    });

    // --- Stage 3: matching (submit one marketable order per event) --------
    auto matching_stats = run_staged("matching", [&]() {
        CsvMarketSource source(dataset_path);
        MatchingEngine engine;
        MarketState s;
        uint64_t order_id = 0;
        while (source.next(s)) {
            engine.clear_book();
            for (const auto& lvl : s.bids) {
                engine.submit_order(Order(order_id++, OrderSide::Buy, OrderType::Limit, lvl.price, lvl.qty));
            }
            for (const auto& lvl : s.asks) {
                engine.submit_order(Order(order_id++, OrderSide::Sell, OrderType::Limit, lvl.price, lvl.qty));
            }
            Order incoming(order_id++, OrderSide::Buy, OrderType::Market, 0.0, 10);
            engine.match_market(incoming);
        }
    });

    // --- Stage 4: strategy logic (order generation only, no engine) -------
    auto strategy_stats = run_staged("strategy_logic (TWAP)", [&]() {
        TWAPAlgorithm twap;
        auto orders = twap.generate_orders(1, OrderSide::Buy, 100000, 1e9, 50);
        (void)orders;
    });

    // --- Stage 5: full replay + execution (parsing + replay + matching + strategy) --
    auto full_execution_stats = run_staged("full_execution (TWAP)", [&]() {
        CsvMarketSource source(dataset_path);
        TWAPAlgorithm twap;
        auto orders = twap.generate_orders(1, OrderSide::Buy, 1000, 1e9, 5);
        ExecutionSession session;
        auto result = session.run(source, orders, 100.0);
        (void)result;
    });

    // --- Stage 6: analytics (cost computation only) ------------------------
    CsvMarketSource for_result(dataset_path);
    TWAPAlgorithm twap_for_result;
    auto orders_for_result = twap_for_result.generate_orders(1, OrderSide::Buy, 1000, 1e9, 5);
    ExecutionSession session_for_result;
    auto sample_result = session_for_result.run(for_result, orders_for_result, 100.0);

    auto analytics_stats = run_staged("analytics (costs)", [&]() {
        TransactionCostConfig cfg;
        auto costs = compute_transaction_costs(sample_result, cfg);
        (void)costs;
    });

    std::cout << "\n-- Stage timings (Release build; run via CMAKE_BUILD_TYPE=Release for meaningful numbers) --\n";
    print_stage(parsing_stats);
    print_stage(replay_stats);
    print_stage(matching_stats);
    print_stage(strategy_stats);
    print_stage(full_execution_stats);
    print_stage(analytics_stats);

    std::cout << "\n-- Memory --\n";
    std::cout << "Peak RSS at end of run: " << peak_rss_kb() << " KB "
              << "(cumulative peak for this process - see docs/BENCHMARKING.md for what this does/doesn't isolate)\n";

    std::cout << "\n-- Regression thresholds (Step 7 'add performance regression thresholds') --\n";
    std::cout << "Fill in docs/BENCHMARKING.md §Thresholds once a baseline machine's numbers are recorded;\n";
    std::cout << "this program does not hardcode pass/fail thresholds because they are machine-specific and\n";
    std::cout << "would silently become meaningless (and falsely reassuring) on any other machine.\n";

    return 0;
}
