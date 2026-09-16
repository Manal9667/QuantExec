#include "replay.h"

#include <algorithm>
#include <cmath>
#include <fstream>
#include <sstream>
#include <unordered_map>

namespace {

std::string strip_trailing_cr(const std::string& s) {
    // Defends against \r\n line endings surviving into a field's value -
    // this can happen depending on how/where a CSV was written (e.g. a
    // file written by one tool in one text mode and read by another),
    // regardless of which platform is doing the reading. Only ever
    // affects the very last field on a line (the \r sits right before
    // the \n that std::getline already consumed).
    size_t end = s.size();
    while (end > 0 && (s[end - 1] == '\r' || s[end - 1] == '\n')) --end;
    return s.substr(0, end);
}

std::vector<std::string> split_csv_line(const std::string& line) {
    std::vector<std::string> fields;
    std::stringstream stream(line);
    std::string field;
    while (std::getline(stream, field, ',')) {
        fields.push_back(field);
    }
    if (!fields.empty()) fields.back() = strip_trailing_cr(fields.back());
    return fields;
}

struct DepthLevel {
    double price;
    uint64_t qty;
};

std::vector<DepthLevel> parse_depth(const std::string& value) {
    std::vector<DepthLevel> levels;
    std::stringstream stream(value);
    std::string item;
    while (std::getline(stream, item, '|')) {
        const auto sep = item.find(':');
        if (sep == std::string::npos) continue;
        try {
            const double price = std::stod(item.substr(0, sep));
            const auto qty = std::stoull(item.substr(sep + 1));
            if (price > 0.0 && qty > 0) levels.push_back({price, qty});
        } catch (const std::exception&) {
            // skip malformed level, matches CsvMarketSource's tolerance for depth entries
        }
    }
    return levels;
}

} // namespace

ReplayLoadResult parse_market_events(const std::string& path, const std::string& symbol) {
    ReplayLoadResult result;
    const std::string source_tag = "csv:" + path;

    // Opened in binary mode deliberately: text-mode \r\n<->\n translation
    // behavior differs across platforms and standard library
    // implementations, and depends on how the file was written, not just
    // which OS is reading it. Reading raw bytes and stripping \r
    // ourselves (strip_trailing_cr, above) makes parsing behave
    // identically everywhere instead of depending on that translation
    // happening to match on both ends.
    std::ifstream input(path, std::ios::binary);
    if (!input) {
        result.status = ReplayLoadStatus::FileNotFound;
        result.detail = "Could not open file: " + path;
        return result;
    }

    std::string line;
    if (!std::getline(input, line)) {
        result.status = ReplayLoadStatus::EmptyFile;
        result.detail = "File has no header row: " + path;
        return result;
    }

    const auto headers = split_csv_line(line);
    const std::vector<std::string> required = {
        "timestamp_ms", "last", "bid", "ask", "bid_size", "ask_size", "volume"
    };
    std::unordered_map<std::string, size_t> positions;
    for (size_t i = 0; i < headers.size(); ++i) positions[headers[i]] = i;
    for (const auto& h : required) {
        if (positions.find(h) == positions.end()) {
            result.status = ReplayLoadStatus::MissingColumns;
            result.detail = "Missing required column: " + h;
            return result;
        }
    }

    uint64_t sequence = 0;
    uint64_t last_timestamp = 0;
    bool have_previous_timestamp = false;
    uint64_t previous_cumulative_volume = 0;
    int row_number = 1;

    // Emit the start-of-session SessionMarker lazily once we know the
    // first row's timestamp (a marker before any data would be a made-up
    // timestamp, which Step 3 explicitly wants to avoid).
    bool emitted_start_marker = false;

    while (std::getline(input, line)) {
        row_number++;
        if (line.empty()) continue;
        const auto fields = split_csv_line(line);
        auto field = [&](const std::string& key) -> std::string {
            const auto it = positions.find(key);
            return (it == positions.end() || it->second >= fields.size()) ? std::string{} : fields[it->second];
        };

        uint64_t timestamp_ms;
        double last_price, bid, ask;
        uint64_t bid_size, ask_size, volume;
        try {
            timestamp_ms = std::stoull(field("timestamp_ms"));
            last_price = std::stod(field("last"));
            bid = std::stod(field("bid"));
            ask = std::stod(field("ask"));
            bid_size = std::stoull(field("bid_size"));
            ask_size = std::stoull(field("ask_size"));
            volume = std::stoull(field("volume"));
        } catch (const std::exception&) {
            result.status = ReplayLoadStatus::MalformedRow;
            result.detail = "Row " + std::to_string(row_number) + " has a malformed numeric field";
            return result;
        }

        if (!std::isfinite(last_price) || !std::isfinite(bid) || !std::isfinite(ask)) {
            result.status = ReplayLoadStatus::NonFiniteValue;
            result.detail = "Row " + std::to_string(row_number) + " has a non-finite price";
            return result;
        }
        if (last_price < 0.0 || bid < 0.0 || ask < 0.0) {
            result.status = ReplayLoadStatus::NegativeValue;
            result.detail = "Row " + std::to_string(row_number) + " has a negative price";
            return result;
        }
        if (bid > 0.0 && ask > 0.0 && bid > ask) {
            result.status = ReplayLoadStatus::InvalidBidAsk;
            result.detail = "Row " + std::to_string(row_number) + ": bid (" + std::to_string(bid) +
                             ") > ask (" + std::to_string(ask) + ")";
            return result;
        }
        if (have_previous_timestamp && timestamp_ms == last_timestamp) {
            result.status = ReplayLoadStatus::DuplicateTimestamp;
            result.detail = "Row " + std::to_string(row_number) + ": duplicate timestamp_ms " +
                             std::to_string(timestamp_ms);
            return result;
        }
        if (have_previous_timestamp && timestamp_ms < last_timestamp) {
            result.status = ReplayLoadStatus::NonMonotonicTimestamp;
            result.detail = "Row " + std::to_string(row_number) + ": timestamp_ms " +
                             std::to_string(timestamp_ms) + " precedes previous " + std::to_string(last_timestamp);
            return result;
        }

        if (!emitted_start_marker) {
            MarketEvent marker;
            marker.timestamp_ms = timestamp_ms;
            marker.type = EventType::SessionMarker;
            marker.symbol = symbol;
            marker.source = source_tag;
            marker.sequence = sequence++;
            result.events.push_back(marker);
            emitted_start_marker = true;
        }

        // 1. BestBid
        {
            MarketEvent e;
            e.timestamp_ms = timestamp_ms;
            e.type = EventType::BestBid;
            e.symbol = symbol;
            e.price = bid;
            e.quantity = bid_size;
            e.side = OrderSide::Buy;
            e.level = 0;
            e.source = source_tag;
            e.sequence = sequence++;
            result.events.push_back(e);
        }
        // 2. BestAsk
        {
            MarketEvent e;
            e.timestamp_ms = timestamp_ms;
            e.type = EventType::BestAsk;
            e.symbol = symbol;
            e.price = ask;
            e.quantity = ask_size;
            e.side = OrderSide::Sell;
            e.level = 0;
            e.source = source_tag;
            e.sequence = sequence++;
            result.events.push_back(e);
        }
        // 3. DepthUpdate beyond top-of-book, if present
        if (positions.find("bid_depth") != positions.end()) {
            const auto levels = parse_depth(field("bid_depth"));
            for (size_t i = 1; i < levels.size(); ++i) {  // level 0 already covered by BestBid
                MarketEvent e;
                e.timestamp_ms = timestamp_ms;
                e.type = EventType::DepthUpdate;
                e.symbol = symbol;
                e.price = levels[i].price;
                e.quantity = levels[i].qty;
                e.side = OrderSide::Buy;
                e.level = static_cast<int>(i);
                e.source = source_tag;
                e.sequence = sequence++;
                result.events.push_back(e);
            }
        }
        if (positions.find("ask_depth") != positions.end()) {
            const auto levels = parse_depth(field("ask_depth"));
            for (size_t i = 1; i < levels.size(); ++i) {
                MarketEvent e;
                e.timestamp_ms = timestamp_ms;
                e.type = EventType::DepthUpdate;
                e.symbol = symbol;
                e.price = levels[i].price;
                e.quantity = levels[i].qty;
                e.side = OrderSide::Sell;
                e.level = static_cast<int>(i);
                e.source = source_tag;
                e.sequence = sequence++;
                result.events.push_back(e);
            }
        }
        // 4. Trade, from bar_volume if present else the delta of cumulative volume
        uint64_t bar_volume = 0;
        if (positions.find("bar_volume") != positions.end()) {
            try {
                bar_volume = std::stoull(field("bar_volume"));
            } catch (const std::exception&) {
                bar_volume = 0;
            }
        }
        const uint64_t event_volume = bar_volume > 0
            ? bar_volume
            : (volume >= previous_cumulative_volume ? volume - previous_cumulative_volume : 0);
        previous_cumulative_volume = volume;
        if (event_volume > 0) {
            MarketEvent e;
            e.timestamp_ms = timestamp_ms;
            e.type = EventType::Trade;
            e.symbol = symbol;
            e.price = last_price > 0.0 ? last_price : (bid + ask) / 2.0;
            e.quantity = event_volume;
            e.side = OrderSide::Buy;  // not observable from this schema - see header comment
            e.source = source_tag;
            e.sequence = sequence++;
            result.events.push_back(e);
        }

        last_timestamp = timestamp_ms;
        have_previous_timestamp = true;
    }

    if (!have_previous_timestamp) {
        result.status = ReplayLoadStatus::EmptyFile;
        result.detail = "File has a header but no data rows: " + path;
        result.events.clear();
        return result;
    }

    // End-of-session marker at the last observed timestamp.
    {
        MarketEvent marker;
        marker.timestamp_ms = last_timestamp;
        marker.type = EventType::SessionMarker;
        marker.symbol = symbol;
        marker.source = source_tag;
        marker.sequence = sequence++;
        result.events.push_back(marker);
    }

    result.status = ReplayLoadStatus::Ok;
    return result;
}

std::vector<MarketState> events_to_states(const std::vector<MarketEvent>& events) {
    std::vector<MarketState> states;
    if (events.empty()) return states;

    MarketState current;
    bool have_current = false;
    uint64_t group_timestamp = events.front().timestamp_ms;

    auto flush = [&]() {
        if (!have_current) return;
        MarketState state = current;
        state.timestamp_ms = group_timestamp;
        normalize_market_state(state);
        states.push_back(state);
    };

    for (const auto& e : events) {
        if (e.timestamp_ms != group_timestamp) {
            flush();
            group_timestamp = e.timestamp_ms;
        }
        have_current = true;
        switch (e.type) {
            case EventType::BestBid:
                current.bid = e.price;
                current.bid_volume = e.quantity;
                if (e.level == 0) {
                    if (current.bids.empty()) current.bids.push_back({e.price, e.quantity});
                    else current.bids[0] = {e.price, e.quantity};
                }
                break;
            case EventType::BestAsk:
                current.ask = e.price;
                current.ask_volume = e.quantity;
                if (e.level == 0) {
                    if (current.asks.empty()) current.asks.push_back({e.price, e.quantity});
                    else current.asks[0] = {e.price, e.quantity};
                }
                break;
            case EventType::DepthUpdate: {
                auto& levels = (e.side == OrderSide::Buy) ? current.bids : current.asks;
                while (static_cast<int>(levels.size()) <= e.level) {
                    levels.push_back({0.0, 0});
                }
                levels[static_cast<size_t>(e.level)] = {e.price, e.quantity};
                break;
            }
            case EventType::Trade:
                current.last_price = e.price;
                current.bar_volume += e.quantity;
                current.volume += e.quantity;
                break;
            case EventType::Snapshot:
                // Full-state replacement is left to callers who construct
                // Snapshot events directly (not emitted by parse_market_events
                // for CSV input, which only emits the more granular event
                // types above); nothing to do here for the CSV path.
                break;
            case EventType::SessionMarker:
                // No state field to update; boundary is implicit in
                // events()/is_end_of_stream() on ReplayController.
                break;
        }
    }
    flush();
    return states;
}

ReplayController::ReplayController(std::vector<MarketEvent> events)
    : events_(std::move(events)) {
    all_states_ = events_to_states(events_);
    rebuild_window();
}

void ReplayController::rebuild_window() {
    window_.clear();
    for (const auto& s : all_states_) {
        if (s.timestamp_ms >= start_time_ms_ && s.timestamp_ms <= end_time_ms_) {
            window_.push_back(s);
        }
    }
    index_ = 0;
    current_time_ms_ = 0;
}

bool ReplayController::next(MarketState& out) {
    if (index_ >= window_.size()) return false;
    out = window_[index_++];
    current_time_ms_ = out.timestamp_ms;
    return true;
}

void ReplayController::reset() {
    index_ = 0;
    current_time_ms_ = 0;
}

void ReplayController::seek(uint64_t timestamp_ms) {
    index_ = static_cast<size_t>(std::lower_bound(
        window_.begin(), window_.end(), timestamp_ms,
        [](const MarketState& s, uint64_t t) { return s.timestamp_ms < t; }) - window_.begin());
    current_time_ms_ = 0;
}

bool ReplayController::is_end_of_stream() const {
    return index_ >= window_.size();
}

void ReplayController::set_time_window(uint64_t start_time_ms, uint64_t end_time_ms) {
    start_time_ms_ = start_time_ms;
    end_time_ms_ = end_time_ms;
    rebuild_window();
}