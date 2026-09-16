#ifndef EXECUTOR_REPLAY_H
#define EXECUTOR_REPLAY_H

#include "market_data.h"
#include <cstdint>
#include <string>
#include <vector>

/**
 * Formal event/replay pipeline (Step 3).
 *
 * This module exists to make the following boundary explicit and testable,
 * which CsvMarketSource (src/market_data.cpp) does not separate out:
 *
 *     raw file  -->  ordered MarketEvent[]  -->  normalized MarketState[]  -->  replay
 *      (parse)          (this is the wire        (this is what strategies    (this is
 *                        format: one fact          actually see - it is       ReplayController,
 *                        per event, nothing        derived, never the raw     which enforces
 *                        inferred)                 event stream)              no-lookahead)
 *
 * CsvMarketSource is left completely untouched - it remains the "snapshot
 * adapter" the spec asks to preserve, and every existing test that depends
 * on it keeps passing unmodified. This module is an additional, independent
 * path over the *same* CSV files, so the two can be cross-checked against
 * each other (see tests/test_replay.cpp) rather than one replacing the
 * other's behavior silently.
 *
 * Event decomposition (parse_market_events):
 *   For each CSV row (same schema as documented in dataset.md) this emits,
 *   in a fixed order, one event per observable fact in that row:
 *     1. BestBid   (side=Buy,  level=0, price=bid,  quantity=bid_size)
 *     2. BestAsk   (side=Sell, level=0, price=ask,  quantity=ask_size)
 *     3. DepthUpdate for every level beyond the top, if bid_depth/ask_depth
 *        columns are present (level=1,2,...)
 *     4. Trade, if this row's realized volume (bar_volume, or the positive
 *        delta of cumulative `volume` vs. the previous row) is > 0. Side is
 *        not observable from this schema and is recorded as Buy by
 *        convention; this is a known limitation of the schema, not
 *        something this parser invents an opinion about (see
 *        docs/EXECUTION_ASSUMPTIONS.md).
 *   A SessionMarker event is emitted once at the very start and once at the
 *   very end of the file, so replay boundaries are an explicit fact in the
 *   stream rather than "whatever index the loop happens to stop at".
 *
 * Normalization (events_to_states):
 *   Events are grouped by timestamp_ms (ties broken by `sequence`, which
 *   parse_market_events assigns in emission order). Within a group, later
 *   events overwrite the corresponding field of a MarketState that started
 *   as a copy of the previous timestamp's state (fields not touched by any
 *   event in this group carry forward - this is what makes "duplicate
 *   timestamp" and "missing quote" well-defined instead of undefined).
 *   normalize_market_state() (market_data.cpp) is then applied, exactly as
 *   CsvMarketSource applies it, so both paths use one normalization rule.
 *
 * The result of parse -> normalize for a well-formed file is, by
 * construction, the same MarketState sequence CsvMarketSource would
 * produce for that file (verified in tests/test_replay.cpp) - this module
 * is a stricter, explicit route to the same destination, not a competing
 * model of the market.
 */

/**
 * Reasons parse_market_events can refuse a file. Mirrors the validation
 * rules in dataset.md / scripts/build_dataset_manifest.py so the same
 * problem gets the same name everywhere in the codebase.
 */
enum class ReplayLoadStatus {
    Ok,
    FileNotFound,
    EmptyFile,
    MissingColumns,
    MalformedRow,
    NonFiniteValue,
    NegativeValue,
    InvalidBidAsk,
    DuplicateTimestamp,
    NonMonotonicTimestamp
};

struct ReplayLoadResult {
    ReplayLoadStatus status = ReplayLoadStatus::Ok;
    std::string detail;       // human-readable reason, includes row number when applicable
    std::vector<MarketEvent> events;

    bool ok() const { return status == ReplayLoadStatus::Ok; }
};

/**
 * Parses a CSV file (same schema as CsvMarketSource) into an ordered,
 * validated MarketEvent stream. Returns a non-Ok status with a specific
 * reason on any validation failure - never partially loads a bad file.
 */
ReplayLoadResult parse_market_events(const std::string& path, const std::string& symbol = "");

/**
 * Groups an ordered MarketEvent stream into a MarketState sequence, one
 * state per distinct timestamp_ms, applying normalize_market_state() to
 * each. `events` must already be in non-decreasing timestamp_ms order
 * (parse_market_events guarantees this); this function does not re-sort,
 * since silently reordering is exactly the failure mode Step 3 exists to
 * make explicit rather than hide.
 */
std::vector<MarketState> events_to_states(const std::vector<MarketEvent>& events);

/**
 * Explicit replay controls over a MarketEvent-derived MarketState sequence
 * (Step 3, "make replay controls explicit"). Wraps the same underlying
 * data VectorMarketSource would, but additionally exposes the raw event
 * stream (for audit / no-lookahead tests) and an explicit end-of-stream
 * query that doesn't require calling next() and inspecting its return
 * value.
 */
class ReplayController : public MarketDataSource {
public:
    explicit ReplayController(std::vector<MarketEvent> events);

    bool next(MarketState& out) override;
    void reset() override;
    void seek(uint64_t timestamp_ms) override;
    uint64_t current_time_ms() const override { return current_time_ms_; }
    std::string name() const override { return "replay_controller"; }

    /** True once next() has been called past the last available state. */
    bool is_end_of_stream() const;

    /** Restrict replay to [start_time_ms, end_time_ms] inclusive. */
    void set_time_window(uint64_t start_time_ms, uint64_t end_time_ms);

    /** The raw, ordered event stream this controller was built from - for
     * audit trails and no-lookahead tests, never consulted by strategies. */
    const std::vector<MarketEvent>& events() const { return events_; }

    /** All normalized states this controller can ever produce, i.e. the
     * full result of events_to_states() before any windowing/seeking.
     * Exposed for testing determinism against CsvMarketSource, not meant
     * to be used by strategy code (which must only see next()'s output). */
    const std::vector<MarketState>& all_states() const { return all_states_; }

private:
    std::vector<MarketEvent> events_;
    std::vector<MarketState> all_states_;   // events_to_states(events_), unfiltered
    std::vector<MarketState> window_;       // all_states_ restricted to [start,end]
    size_t index_ = 0;
    uint64_t current_time_ms_ = 0;
    uint64_t start_time_ms_ = 0;
    uint64_t end_time_ms_ = UINT64_MAX;

    void rebuild_window();
};

#endif
