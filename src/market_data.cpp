#include "market_data.h"

#include <algorithm>
#include <fstream>
#include <sstream>
#include <unordered_map>
#include <cmath>
#include <iostream>
#include <stdexcept>

namespace {

std::vector<std::string> split_csv_line(const std::string& line) {
    std::vector<std::string> fields;
    std::stringstream stream(line);
    std::string field;
    while (std::getline(stream, field, ',')) {
        fields.push_back(field);
    }
    return fields;
}

std::vector<BookLevel> parse_depth(const std::string& value) {
    std::vector<BookLevel> levels;
    std::stringstream stream(value);
    std::string item;
    while (std::getline(stream, item, '|')) {
        const auto separator = item.find(':');
        if (separator == std::string::npos) {
            continue;
        }
        try {
            const double price = std::stod(item.substr(0, separator));
            const auto quantity = std::stoull(item.substr(separator + 1));
            if (price > 0.0 && quantity > 0) {
                levels.push_back({price, quantity});
            }
        } catch (const std::exception&) {
            // Ignore malformed depth entries while preserving the row.
        }
    }
    return levels;
}

bool is_finite(double value) {
    return std::isfinite(value);
}

} // namespace

VectorMarketSource::VectorMarketSource(std::vector<MarketState> states)
    : states_(std::move(states)) {
    for (auto& state : states_) {
        normalize_market_state(state);
    }
}

bool VectorMarketSource::next(MarketState& out) {
    if (index_ >= states_.size()) {
        return false;
    }
    out = states_[index_++];
    current_time_ms_ = out.timestamp_ms;
    return true;
}

void VectorMarketSource::reset() {
    index_ = 0;
    current_time_ms_ = 0;
}

void VectorMarketSource::seek(uint64_t timestamp_ms) {
    index_ = static_cast<size_t>(std::lower_bound(
        states_.begin(), states_.end(), timestamp_ms,
        [](const MarketState& state, uint64_t timestamp) {
            return state.timestamp_ms < timestamp;
        }) - states_.begin());
    current_time_ms_ = 0;
}

bool RealtimeMarketSource::publish(MarketState state) {
    if (!states_.empty() && state.timestamp_ms < last_timestamp_ms_) {
        return false;
    }
    normalize_market_state(state);
    last_timestamp_ms_ = state.timestamp_ms;
    states_.push_back(std::move(state));
    return true;
}

bool RealtimeMarketSource::next(MarketState& out) {
    if (index_ >= states_.size()) {
        return false;
    }
    out = states_[index_++];
    current_time_ms_ = out.timestamp_ms;
    return true;
}

void RealtimeMarketSource::reset() {
    index_ = 0;
    current_time_ms_ = 0;
}

void RealtimeMarketSource::seek(uint64_t timestamp_ms) {
    index_ = static_cast<size_t>(std::lower_bound(
        states_.begin(), states_.end(), timestamp_ms,
        [](const MarketState& state, uint64_t timestamp) {
            return state.timestamp_ms < timestamp;
        }) - states_.begin());
    current_time_ms_ = 0;
}

CsvMarketSource::CsvMarketSource(std::string path)
    : path_(std::move(path)) {
    load();
}

void CsvMarketSource::load() {
    std::ifstream input(path_);
    if (!input) {
        return;
    }

    std::string line;
    if (!std::getline(input, line)) {
        return;  // Empty file
    }

    const auto headers = split_csv_line(line);
    const std::vector<std::string> required = {
        "timestamp_ms", "last", "bid", "ask", "bid_size", "ask_size", "volume"
    };
    std::unordered_map<std::string, size_t> positions;
    for (size_t i = 0; i < headers.size(); ++i) {
        positions[headers[i]] = i;
    }
    
    // Check all required columns are present
    for (const auto& header : required) {
        if (positions.find(header) == positions.end()) {
            return;  // Malformed header
        }
    }

    uint64_t last_timestamp_ms = 0;
    int row_number = 1;  // Header is row 1

    while (std::getline(input, line)) {
        row_number++;
        if (line.empty()) {
            continue;
        }
        const auto fields = split_csv_line(line);
        auto field = [&fields, &positions](const std::string& key) -> std::string {
            const auto it = positions.find(key);
            return it == positions.end() || it->second >= fields.size()
                ? std::string{}
                : fields[it->second];
        };

        try {
            MarketState state;
            
            // Parse required fields
            state.timestamp_ms = std::stoull(field("timestamp_ms"));
            state.last_price = std::stod(field("last"));
            state.bid = std::stod(field("bid"));
            state.ask = std::stod(field("ask"));
            state.bid_volume = std::stoull(field("bid_size"));
            state.ask_volume = std::stoull(field("ask_size"));
            state.volume = std::stoull(field("volume"));
            
            // Validate prices are finite
            if (!is_finite(state.last_price) || !is_finite(state.bid) || !is_finite(state.ask)) {
                states_.clear();
                return;  // Non-finite price
            }
            
            // Validate prices are positive
            if (state.last_price <= 0.0 || state.bid <= 0.0 || state.ask <= 0.0) {
                states_.clear();
                return;  // Non-positive price
            }
            
            // Validate bid <= ask relationship
            if (state.bid > state.ask) {
                states_.clear();
                return;  // Bid > ask
            }
            
            // Validate timestamps are monotonic
            if (!states_.empty() && state.timestamp_ms <= last_timestamp_ms) {
                states_.clear();
                return;  // Non-monotonic timestamp
            }
            last_timestamp_ms = state.timestamp_ms;
            
            // Parse optional fields
            if (positions.find("bar_volume") != positions.end()) {
                state.bar_volume = std::stoull(field("bar_volume"));
            }
            if (positions.find("bid_depth") != positions.end()) {
                state.bids = parse_depth(field("bid_depth"));
            }
            if (positions.find("ask_depth") != positions.end()) {
                state.asks = parse_depth(field("ask_depth"));
            }
            
            normalize_market_state(state);
            states_.push_back(std::move(state));
        } catch (const std::exception&) {
            states_.clear();
            return;  // Malformed row
        }
    }
    
    // Reject empty datasets
    if (states_.empty()) {
        return;
    }
    
    // Note: We intentionally do NOT sort by timestamp here.
    // Timestamps MUST be strictly monotonic in the file; we validate during load.
    // This preserves data order and fails fast on temporal inversions.
    loaded_ = true;
}

bool CsvMarketSource::next(MarketState& out) {
    if (index_ >= states_.size() || states_[index_].timestamp_ms > end_time_ms_) {
        return false;
    }
    out = states_[index_++];
    current_time_ms_ = out.timestamp_ms;
    return true;
}

void CsvMarketSource::reset() {
    seek(start_time_ms_);
}

void CsvMarketSource::seek(uint64_t timestamp_ms) {
    index_ = static_cast<size_t>(std::lower_bound(
        states_.begin(), states_.end(), timestamp_ms,
        [](const MarketState& state, uint64_t timestamp) {
            return state.timestamp_ms < timestamp;
        }) - states_.begin());
    current_time_ms_ = 0;
}

void CsvMarketSource::set_time_window(uint64_t start_time_ms, uint64_t end_time_ms) {
    if (end_time_ms < start_time_ms) {
        throw std::invalid_argument("Replay end time must be >= start time");
    }
    start_time_ms_ = start_time_ms;
    end_time_ms_ = end_time_ms;
    reset();
}

void normalize_market_state(MarketState& state) {
    // Derive mid_price from bid/ask if not set
    if (state.mid_price <= 0.0 && state.bid > 0.0 && state.ask > 0.0) {
        state.mid_price = (state.bid + state.ask) / 2.0;
    }
    
    // Derive last_price from mid_price if not set
    if (state.last_price <= 0.0) {
        state.last_price = state.mid_price;
    }
    
    // Populate bids depth from top-of-book if depth is empty
    if (state.bids.empty() && state.bid > 0.0 && state.bid_volume > 0) {
        state.bids.push_back({state.bid, state.bid_volume});
    }
    
    // Populate asks depth from top-of-book if depth is empty
    if (state.asks.empty() && state.ask > 0.0 && state.ask_volume > 0) {
        state.asks.push_back({state.ask, state.ask_volume});
    }
    
    // Sync top-of-book from depth
    if (!state.bids.empty()) {
        state.bid = state.bids.front().price;
        state.bid_volume = state.bids.front().qty;
    }
    if (!state.asks.empty()) {
        state.ask = state.asks.front().price;
        state.ask_volume = state.asks.front().qty;
    }
    
    // Fallback: derive mid_price from last_price
    if (state.mid_price <= 0.0 && state.last_price > 0.0) {
        state.mid_price = state.last_price;
    }
    
    // Validate invariants after normalization
    if (state.bid > 0.0 && state.ask > 0.0 && state.bid > state.ask) {
        // This should not happen if load() validated correctly, but enforce it.
        std::swap(state.bid, state.ask);
        std::swap(state.bid_volume, state.ask_volume);
        std::swap(state.bids, state.asks);
    }
}