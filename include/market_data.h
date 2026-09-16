#ifndef EXECUTOR_MARKET_DATA_H
#define EXECUTOR_MARKET_DATA_H

#include "types.h"
#include <cstdint>
#include <string>
#include <vector>

/**
 * Canonical market view used by the execution session.
 *
 * Every source (synthetic, real-time adapter, historical CSV) produces this.
 * The matching engine never sees Yahoo JSON or CSV columns.
 *
 * Depth: bids/asks are best-first. Empty vectors mean "top-of-book only";
 * the session will then post a single level from bid/ask + sizes.
 */
struct MarketState {
    double last_price = 0.0;
    double mid_price = 0.0;
    double bid = 0.0;
    double ask = 0.0;
    uint64_t bid_volume = 0;
    uint64_t ask_volume = 0;
    uint64_t volume = 0;       // cumulative volume if the source provides it
    uint64_t bar_volume = 0;   // volume during this event/bar (for market VWAP)
    uint64_t timestamp_ms = 0;
    std::vector<BookLevel> bids;
    std::vector<BookLevel> asks;
};

using MarketSnapshot = MarketState;

/**
 * Internal normalized representation for a market-data event.
 *
 * This is intentionally vendor-independent. Raw data is first read, validated,
 * and then converted into these objects before the execution engine sees it.
 */
enum class EventType {
    Trade,
    BestBid,
    BestAsk,
    DepthUpdate,
    Snapshot,
    SessionMarker   // Start/end-of-session boundary (Step 3). Carries no
                     // price/quantity; `symbol` + `timestamp_ms` only.
};

struct MarketEvent {
    uint64_t timestamp_ms = 0;
    EventType type = EventType::Snapshot;
    std::string symbol;
    double price = 0.0;
    uint64_t quantity = 0;
    OrderSide side = OrderSide::Buy;
    int level = 0;              // depth level index for DepthUpdate (0 = top of book)
    std::string source;         // provenance: e.g. "csv:datasets/foo.csv" (Step 3, "source metadata")
    uint64_t sequence = 0;      // stable ordering among events sharing one timestamp_ms
};

/**
 * Pull-style feed. next() must be chronological: no future information.
 */
class MarketDataSource {
public:
    virtual ~MarketDataSource() = default;
    virtual bool next(MarketState& out) = 0;
    virtual void reset() = 0;
    virtual void seek(uint64_t timestamp_ms) = 0;
    virtual uint64_t current_time_ms() const = 0;
    virtual std::string name() const = 0;
};

/**
 * In-memory sequence. Used by tests and by Python after it has adapted
 * an external API into MarketState objects.
 */
class VectorMarketSource : public MarketDataSource {
public:
    explicit VectorMarketSource(std::vector<MarketState> states);
    bool next(MarketState& out) override;
    void reset() override;
    void seek(uint64_t timestamp_ms) override;
    uint64_t current_time_ms() const override { return current_time_ms_; }
    std::string name() const override { return "vector"; }

private:
    std::vector<MarketState> states_;
    size_t index_ = 0;
    uint64_t current_time_ms_ = 0;
};

class RealtimeMarketSource : public MarketDataSource {
public:
    bool publish(MarketState state);
    bool next(MarketState& out) override;
    void reset() override;
    void seek(uint64_t timestamp_ms) override;
    uint64_t current_time_ms() const override { return current_time_ms_; }
    std::string name() const override { return "realtime"; }

private:
    std::vector<MarketState> states_;
    size_t index_ = 0;
    uint64_t last_timestamp_ms_ = 0;
    uint64_t current_time_ms_ = 0;
};

/**
 * Historical / recorded real-market replay.
 *
 * CSV columns (header required):
 *   timestamp_ms,last,bid,ask,bid_size,ask_size,volume
 * Optional:
 *   bid_depth,ask_depth   format price:qty|price:qty  (best first)
 *
 * If depth columns are absent, only top-of-book is available.
 */
class CsvMarketSource : public MarketDataSource {
public:
    explicit CsvMarketSource(std::string path);
    bool next(MarketState& out) override;
    void reset() override;
    void seek(uint64_t timestamp_ms) override;
    uint64_t current_time_ms() const override { return current_time_ms_; }
    std::string name() const override { return "csv"; }
    bool ok() const { return loaded_; }

    void set_time_window(uint64_t start_time_ms, uint64_t end_time_ms);

private:
    std::string path_;
    std::vector<MarketState> states_;
    size_t index_ = 0;
    bool loaded_ = false;
    uint64_t start_time_ms_ = 0;
    uint64_t end_time_ms_ = UINT64_MAX;
    uint64_t current_time_ms_ = 0;

    void load();
};

void normalize_market_state(MarketState& state);

#endif
