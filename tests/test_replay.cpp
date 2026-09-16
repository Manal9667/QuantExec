#include "../include/replay.h"
#include "../include/market_data.h"
#include <cassert>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

int test_count = 0;
int pass_count = 0;
std::vector<std::string> g_temp_files;  // cleaned up in main() on exit

void assert_true(const std::string& name, bool condition) {
    test_count++;
    if (condition) {
        pass_count++;
        std::cout << "OK   " << name << std::endl;
    } else {
        std::cout << "FAIL " << name << std::endl;
    }
}

template <typename A, typename B>
void assert_eq(const std::string& name, const A& actual, const B& expected) {
    test_count++;
    if (actual == expected) {
        pass_count++;
        std::cout << "OK   " << name << std::endl;
    } else {
        std::cout << "FAIL " << name << " (got " << actual << ", expected " << expected << ")" << std::endl;
    }
}

// ---------------------------------------------------------------------------
// Helper: write a small CSV to a temp path (cross-platform - Windows has no
// /tmp, so this writes next to the test binary's working directory instead,
// which CMake sets to CMAKE_SOURCE_DIR for this target on every platform).
// Every path handed out here is removed again in main() before exit.
// ---------------------------------------------------------------------------
std::string write_temp_csv(const std::string& name, const std::string& content) {
    const std::string path = "test_tmp_" + name;
    std::ofstream out(path);
    out << content;
    out.close();
    g_temp_files.push_back(path);
    return path;
}

const char* kBasicCsv =
    "timestamp_ms,last,bid,ask,bid_size,ask_size,volume,bar_volume\n"
    "1000,100.0,99.9,100.1,500,500,1000,1000\n"
    "2000,100.2,100.1,100.3,400,400,1200,200\n"
    "3000,100.4,100.3,100.5,300,300,1500,300\n";

// ---------------------------------------------------------------------------
// 1. Parsing produces a well-formed, ordered event stream
// ---------------------------------------------------------------------------
void test_parse_produces_events_in_order() {
    const auto path = write_temp_csv("replay_basic.csv", kBasicCsv);
    auto result = parse_market_events(path, "SYN");
    assert_true("parse: basic file loads ok", result.ok());
    if (!result.ok()) {
        std::cout << "  -> parse failed: " << result.detail << std::endl;
        return;  // nothing below is safe to inspect on a failed parse
    }

    // Session markers bookend the stream.
    assert_true("parse: starts with SessionMarker", result.events.front().type == EventType::SessionMarker);
    assert_true("parse: ends with SessionMarker", result.events.back().type == EventType::SessionMarker);

    // Events for a single row are non-decreasing in timestamp and strictly
    // increasing in sequence.
    for (size_t i = 1; i < result.events.size(); ++i) {
        assert_true("parse: timestamps never decrease at event " + std::to_string(i),
                    result.events[i].timestamp_ms >= result.events[i - 1].timestamp_ms);
        assert_true("parse: sequence strictly increases at event " + std::to_string(i),
                    result.events[i].sequence > result.events[i - 1].sequence);
    }

    // Every event should carry source provenance.
    bool all_tagged = true;
    for (const auto& e : result.events) {
        if (e.source.empty()) all_tagged = false;
    }
    assert_true("parse: every event carries source metadata", all_tagged);
}

// ---------------------------------------------------------------------------
// 2. events_to_states() reproduces what CsvMarketSource would report
// ---------------------------------------------------------------------------
void test_events_to_states_matches_csv_source() {
    const auto path = write_temp_csv("replay_cross_check.csv", kBasicCsv);
    auto parsed = parse_market_events(path, "SYN");
    assert_true("cross-check: parse ok", parsed.ok());
    if (!parsed.ok()) {
        std::cout << "  -> parse failed: " << parsed.detail << std::endl;
        return;
    }

    auto derived_states = events_to_states(parsed.events);

    CsvMarketSource csv_source(path);
    assert_true("cross-check: CsvMarketSource loads ok", csv_source.ok());
    if (!csv_source.ok()) return;

    assert_eq("cross-check: same number of states", derived_states.size(), size_t(3));

    MarketState csv_state;
    size_t i = 0;
    while (csv_source.next(csv_state)) {
        assert_true("cross-check: index " + std::to_string(i) + " exists in derived states",
                    i < derived_states.size());
        if (i < derived_states.size()) {
            const auto& d = derived_states[i];
            assert_eq("cross-check: timestamp matches at " + std::to_string(i), d.timestamp_ms, csv_state.timestamp_ms);
            assert_eq("cross-check: bid matches at " + std::to_string(i), d.bid, csv_state.bid);
            assert_eq("cross-check: ask matches at " + std::to_string(i), d.ask, csv_state.ask);
            assert_eq("cross-check: last_price matches at " + std::to_string(i), d.last_price, csv_state.last_price);
        }
        ++i;
    }
}

// ---------------------------------------------------------------------------
// 3. Validation: rejects the same defects the manifest tool and
//    CsvMarketSource reject, with a specific reason each time.
// ---------------------------------------------------------------------------
void test_rejects_missing_columns() {
    const auto path = write_temp_csv("replay_missing_col.csv", "timestamp_ms,last,bid,ask\n1000,100,99.9,100.1\n");
    auto result = parse_market_events(path);
    assert_true("reject: missing columns detected", !result.ok());
    assert_eq("reject: missing columns status", int(result.status), int(ReplayLoadStatus::MissingColumns));
}

void test_rejects_duplicate_timestamp() {
    const auto path = write_temp_csv(
        "replay_dup_ts.csv",
        "timestamp_ms,last,bid,ask,bid_size,ask_size,volume\n"
        "1000,100.0,99.9,100.1,500,500,1000\n"
        "1000,100.1,99.9,100.1,500,500,1000\n");
    auto result = parse_market_events(path);
    assert_true("reject: duplicate timestamp detected", !result.ok());
    assert_eq("reject: duplicate timestamp status", int(result.status), int(ReplayLoadStatus::DuplicateTimestamp));
}

void test_rejects_non_monotonic_timestamp() {
    const auto path = write_temp_csv(
        "replay_nonmono.csv",
        "timestamp_ms,last,bid,ask,bid_size,ask_size,volume\n"
        "2000,100.0,99.9,100.1,500,500,1000\n"
        "1000,100.1,99.9,100.1,500,500,1000\n");
    auto result = parse_market_events(path);
    assert_true("reject: non-monotonic timestamp detected", !result.ok());
    assert_eq("reject: non-monotonic timestamp status", int(result.status), int(ReplayLoadStatus::NonMonotonicTimestamp));
}

void test_rejects_crossed_market() {
    const auto path = write_temp_csv(
        "replay_crossed.csv",
        "timestamp_ms,last,bid,ask,bid_size,ask_size,volume\n"
        "1000,100.0,100.5,100.1,500,500,1000\n");
    auto result = parse_market_events(path);
    assert_true("reject: crossed market detected", !result.ok());
    assert_eq("reject: crossed market status", int(result.status), int(ReplayLoadStatus::InvalidBidAsk));
}

void test_rejects_non_finite() {
    const auto path = write_temp_csv(
        "replay_nan.csv",
        "timestamp_ms,last,bid,ask,bid_size,ask_size,volume\n"
        "1000,nan,99.9,100.1,500,500,1000\n");
    auto result = parse_market_events(path);
    assert_true("reject: non-finite value detected", !result.ok());
    assert_eq("reject: non-finite value status", int(result.status), int(ReplayLoadStatus::NonFiniteValue));
}

// ---------------------------------------------------------------------------
// 4. No-lookahead: strategies driven through ReplayController can never see
//    state from a timestamp later than current_time_ms().
// ---------------------------------------------------------------------------
void test_no_lookahead() {
    const auto path = write_temp_csv("replay_lookahead.csv", kBasicCsv);
    auto parsed = parse_market_events(path, "SYN");
    ReplayController controller(parsed.events);

    MarketState state;
    uint64_t last_seen_timestamp = 0;
    bool violated = false;
    while (controller.next(state)) {
        // The controller's own clock must never be ahead of what next()
        // just handed back, and must never move backwards.
        if (controller.current_time_ms() != state.timestamp_ms) violated = true;
        if (state.timestamp_ms < last_seen_timestamp) violated = true;
        last_seen_timestamp = state.timestamp_ms;
    }
    assert_true("no-lookahead: clock never precedes or exceeds current state", !violated);
    assert_true("no-lookahead: is_end_of_stream() true after full replay", controller.is_end_of_stream());
}

void test_no_lookahead_after_seek() {
    const auto path = write_temp_csv("replay_seek.csv", kBasicCsv);
    auto parsed = parse_market_events(path, "SYN");
    ReplayController controller(parsed.events);

    controller.seek(2000);
    MarketState state;
    assert_true("seek: next() after seek(2000) returns state", controller.next(state));
    assert_eq("seek: first state at/after seek target", state.timestamp_ms, uint64_t(2000));

    // Nothing before the seek target should ever be reachable again from here.
    bool saw_earlier = false;
    ReplayController controller2(parsed.events);
    controller2.seek(2000);
    MarketState s2;
    while (controller2.next(s2)) {
        if (s2.timestamp_ms < 2000) saw_earlier = true;
    }
    assert_true("seek: no state earlier than seek target is ever produced", !saw_earlier);
}

// ---------------------------------------------------------------------------
// 5. Explicit replay-boundary / time-window controls
// ---------------------------------------------------------------------------
void test_time_window_filtering() {
    const auto path = write_temp_csv("replay_window.csv", kBasicCsv);
    auto parsed = parse_market_events(path, "SYN");
    ReplayController controller(parsed.events);

    controller.set_time_window(1500, 2500);
    int count = 0;
    MarketState state;
    while (controller.next(state)) {
        assert_true("window: state within [1500,2500]", state.timestamp_ms >= 1500 && state.timestamp_ms <= 2500);
        count++;
    }
    assert_eq("window: exactly one state (t=2000) falls in [1500,2500]", count, 1);
}

void test_end_of_stream_flag() {
    const auto path = write_temp_csv("replay_eos.csv", kBasicCsv);
    auto parsed = parse_market_events(path, "SYN");
    ReplayController controller(parsed.events);

    assert_true("eos: false before replay starts", !controller.is_end_of_stream());
    MarketState state;
    while (controller.next(state)) {}
    assert_true("eos: true once replay is exhausted", controller.is_end_of_stream());
}

// ---------------------------------------------------------------------------
// 6. Missing quotes: a Trade-only tick should carry forward the last known
//    bid/ask rather than fabricating a new one.
// ---------------------------------------------------------------------------
void test_missing_quote_carries_forward() {
    // Row 2 changes nothing on the quote side, only the traded volume - so
    // events_to_states() should still report row 1's bid/ask for row 2.
    const char* csv =
        "timestamp_ms,last,bid,ask,bid_size,ask_size,volume,bar_volume\n"
        "1000,100.0,99.9,100.1,500,500,1000,1000\n"
        "2000,100.05,99.9,100.1,500,500,1300,300\n";
    const auto path = write_temp_csv("replay_carry_forward.csv", csv);
    auto parsed = parse_market_events(path, "SYN");
    auto states = events_to_states(parsed.events);
    assert_eq("carry-forward: two states produced", states.size(), size_t(2));
    if (states.size() == 2) {
        assert_eq("carry-forward: bid unchanged into second state", states[1].bid, 99.9);
        assert_eq("carry-forward: ask unchanged into second state", states[1].ask, 100.1);
        assert_eq("carry-forward: last price does update", states[1].last_price, 100.05);
    }
}

int main() {
    std::cout << "Running replay/event pipeline tests...\n\n";

    test_parse_produces_events_in_order();
    test_events_to_states_matches_csv_source();
    test_rejects_missing_columns();
    test_rejects_duplicate_timestamp();
    test_rejects_non_monotonic_timestamp();
    test_rejects_crossed_market();
    test_rejects_non_finite();
    test_no_lookahead();
    test_no_lookahead_after_seek();
    test_time_window_filtering();
    test_end_of_stream_flag();
    test_missing_quote_carries_forward();

    std::cout << "\nResults: " << pass_count << "/" << test_count << " passed" << std::endl;

    for (const auto& f : g_temp_files) std::remove(f.c_str());

    return pass_count == test_count ? 0 : 1;
}